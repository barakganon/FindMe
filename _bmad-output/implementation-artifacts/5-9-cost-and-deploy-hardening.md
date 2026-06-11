# Story 5.9 — Cost + Deploy Hardening (W9)

> Epic 5, Week 9. Spec line from `findme-v2-sprint-plan.md`:
> **"Caching, batching, rate limits — Can a stranger break it?"**
> Wall-list constraint: *"Cost guard is non-negotiable: 50¢/session, $20/day,
> circuit-breaks to old `/api/chat`."*

**Status:** in-progress (autonomous build 2026-06-11)
**Base branch:** `feature/5-9-cost-deploy-hardening` (off `master`)
**Build model:** Opus plans + foundation; Sonnet subagents implement workstreams
in isolated git worktrees, each pushing its own branch; Opus integrates.

---

## Goal

Make the v2 agentic chat safe to expose to strangers and bounded in cost,
without changing search behavior or the agent loop's tool surface.

## Recon baseline (what already exists on master)

| Area | Present | Gap |
|------|---------|-----|
| Cost guard | per-turn `$0.10` cap in `loop.run_agent`; daily `$20` in `api/agent/cost_guard.py` (Redis `INCRBYFLOAT`, fully wired in `chat_v2.py`) | **no per-session `$0.50` cap** |
| Caching | `api/cache.py` search (300s) + intent (120s); wired in `search.py`/`chat.py` | TTLs **hardcoded**, not env-driven; not in `Settings` |
| Rate limiting | slowapi `Limiter` instantiated (`200/min` default) + middleware in `main.py` | **no `@limiter.limit()` on any route** → effectively absent |
| Deploy | `Dockerfile`, `docker-compose.yml`, `/api/admin/health` | **no `render.yaml`**, hardcoded port 8000 (Render injects `PORT`) |
| Abuse surface | `get_optional_user` anon path; 30s LLM timeout | **no body-size cap, no message length cap** |

## Foundation (DONE — committed on base branch by Opus)

Centralizes all shared-config edits so parallel workstreams don't collide:

- `api/dependencies.py` `Settings`: added `per_session_cost_budget_usd=0.50`,
  `daily_cost_budget_usd=20.0`, `search_cache_ttl=300`, `intent_cache_ttl=120`,
  `chat_rate_limit="20/minute"`, `search_rate_limit="60/minute"`,
  `max_message_length=2000`, `max_history_items=50`,
  `max_request_body_bytes=262144`, `port=8000`.
- `.env.example`: documented all the above.
- `api/schemas.py` `ChatRequest`/`ChatMessage`: `message` `min_length=1,max_length=2000`;
  `history` `max_length=50`; `content` `max_length=2000`. **(Workstream D / abuse-surface validation — done in foundation.)**
- `api/middleware.py` + `api/main.py`: `BodySizeLimitMiddleware` (413 on
  oversized Content-Length). **(Workstream D — done in foundation.)**
- `.gitignore`: ignore `.worktrees/` + `.claude/worktrees/`.
- Full suite green at foundation: **141 passed**.

## Workstreams (Phase B — parallel Sonnet agents, each own worktree+branch)

### A — Per-session cost cap → branch `feature/5-9-cost`
Files: `api/agent/cost_guard.py`, `api/routes/chat_v2.py`, `api/routes/chat_v2_stream.py`, `tests/api/test_cost_guard.py`.
- Add session-scoped cost accumulation in Redis (mirror `cost_guard` daily
  pattern; key `findme:agent:session_cost_usd:{session_id}`, TTL = session 2h).
- Read both ceilings from `Settings` (`per_session_cost_budget_usd`,
  `daily_cost_budget_usd`) instead of raw `os.environ`.
- In `chat_v2.py`/stream: before `run_agent`, if session cost ≥ session budget →
  return the existing advisory `503 {fallback: "/api/chat"}` circuit-break
  (same shape as the daily guard). After each turn, register the turn cost to
  the session key too.
- Tests: session cap trips at the boundary; daily cap still trips; fail-open on
  Redis error; cost registered to both keys.

### B — Env-driven cache TTLs → branch `feature/5-9-cache`
Files: `api/cache.py`, `api/routes/search.py`, `api/routes/chat.py`, `tests/api/test_cache.py`.
- `set_search_cache`/`set_intent_cache` read TTL from `Settings`
  (`search_cache_ttl`/`intent_cache_ttl`) instead of hardcoded 300/120 defaults.
  Keep params overridable for tests.
- Tests: TTL passed to Redis `setex` matches Settings; env override respected.

### C — Apply rate limits → branch `feature/5-9-ratelimit`
Files: `api/routes/chat.py`, `chat_v2.py`, `chat_v2_stream.py`, `search.py`, `stores.py`, `tests/api/test_rate_limit.py` (new).
- Decorate chat routes with `@limiter.limit(settings.chat_rate_limit)` and
  search/store routes with `settings.search_rate_limit`. slowapi needs the
  handler to take `request: Request` — add where missing.
- Anon must still work under the limit (CLAUDE.md rule) — limit is per-IP, not auth-gated.
- Tests: exceeding the limit returns 429; under the limit returns 200.

### E — Render deploy config → branch `feature/5-9-deploy`
Files: `render.yaml` (new), `Dockerfile`, `_bmad-output/implementation-artifacts/5-9-cost-and-deploy-hardening.md` (deploy notes).
- `render.yaml`: web service (Docker), `PORT` from Render, env var declarations
  (sync:false for secrets), Redis + Postgres refs, health check `/api/admin/health`.
- `Dockerfile` CMD: bind to `${PORT:-8000}` so Render's injected port is honored.
- **No actual deploy** — config + docs only.

## Acceptance criteria

- [ ] AC-1 Per-session `$0.50` cost cap enforced, circuit-breaks to `/api/chat`.
- [ ] AC-2 Daily `$20` cap still enforced; both read from `Settings`.
- [ ] AC-3 Cache TTLs env-driven via `Settings`.
- [ ] AC-4 Rate limits applied to all chat + search routes; 429 on breach; anon still works.
- [ ] AC-5 Request body size + message length capped (413 / 422). *(foundation)*
- [ ] AC-6 `render.yaml` present and port-agnostic; no live deploy.
- [ ] AC-7 Full test suite green; new tests for cost/cache/rate-limit.

## Integration (Opus, after agents finish)
Merge `feature/5-9-cost|cache|ratelimit|deploy` into
`feature/5-9-cost-deploy-hardening`, resolve any overlap in route files, run the
full suite, push. Update `sprint-status.yaml` 5.9 → review. Do NOT open PRs / merge to master / deploy.
