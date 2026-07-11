# Epic 6 — Pre-Launch Security Audit

Read-only audit of the deploy-facing surface. Findings cite exact `file:line`. No
application code was modified as part of this audit.

Severity scale: info < low < med < high.

## Launch-blocker summary

| # | Area | Severity | Blocks launch? |
|---|------|----------|-----------------|
| 5a | `JWT_SECRET` silent weak fallback | **high** | **YES — block public launch** |
| 5c | Google OAuth `aud` not pinned, deprecated `tokeninfo` endpoint | med | Fix before public launch; acceptable for soft/private launch |
| 3 | Body-size cap bypassable via chunked transfer-encoding (no Content-Length) | med | Soft-launch acceptable (low realistic exploitability, uvicorn backstop) |
| 4 | Cost-guard TOCTOU + streaming partial-cost gap | med | Soft-launch acceptable — already tracked as known deferred work (Epic 5 retro), requires concurrent abuse to matter |
| 7 | SSE endpoint: no disconnect cancellation, no concurrent-stream cap | med | Soft-launch acceptable at current traffic; revisit before public launch |
| 1 | CORS wildcard default with no prod fail-fast guard | low | Soft-launch acceptable if `CORS_ORIGINS` is set correctly in Render dashboard — verify before go-live |
| 2 | Rate-limit IP keying depends on Render proxy trust | info | No action — correct for this deploy topology |
| 6 | Secrets handling in `render.yaml` / git history | info | Clean — no action |

**Bottom line:** one confirmed HIGH finding (§5a) must be fixed before any public
launch — trivial JWT forgery if `JWT_SECRET` is ever unset in prod. Everything else
is medium-or-below and acceptable for a soft/private launch with a small trusted
user base, but should be tracked for the public launch gate.

---

## 1. CORS — `api/main.py:79-104` — LOW (guard present and correct; gap is operational)

```
api/main.py:87   _cors_origins_raw: str = settings.cors_origins
api/main.py:88   if _cors_origins_raw.strip() == "*": _allowed_origins = ["*"]
api/main.py:96-99  # wildcard + credentials guard, explained inline
api/main.py:99   _allow_credentials = _allowed_origins != ["*"]
```

**Good:** The wildcard-origin + `allow_credentials=True` combination is a real CORS
spec violation (browsers reject it, and if they didn't, it would let any origin
send credentialed requests). The code correctly disables credentials whenever
`allow_origins == ["*"]` (`main.py:99`). This is not a no-op — it's a real
conditional guard tied to the actual origin list.

**Gap:** `api/dependencies.py:51` defaults `cors_origins: str = "*"` when
`CORS_ORIGINS` is unset. `render.yaml` marks `CORS_ORIGINS` as `sync: false`
(must be set manually in the Render dashboard) — nothing in code enforces that
it actually gets set for `APP_ENV=production`. If forgotten, prod runs with
fully open CORS (any origin allowed), just without credentials (so no JWT
cookie/header leakage risk via cross-origin credentialed reads — since this API
uses bearer tokens, not cookies, the practical damage is anonymous
same-endpoint scraping from any origin, not session hijack).

**Fix:** add a startup check — `if settings.app_env == "production" and _allowed_origins == ["*"]: raise RuntimeError("CORS_ORIGINS must be set in production")`.

---

## 2. Rate limiting — `api/dependencies.py:114`, `scripts/start.sh:9-14` — INFO (correctly wired)

- `api/dependencies.py:114`: `Limiter(key_func=get_remote_address, default_limits=["200/minute"])`.
- `CHAT_RATE_LIMIT` / `SEARCH_RATE_LIMIT` (`api/dependencies.py:70-72`, defaults
  `20/minute` / `60/minute`), applied via `@limiter.limit(...)` per route
  (e.g. `api/routes/chat_v2_stream.py:73`).
- `scripts/start.sh:9-14` passes `--proxy-headers --forwarded-allow-ips='*'` to
  uvicorn, with an inline comment explaining this is required so `request.client.host`
  reflects Render's `X-Forwarded-For` rather than Render's internal proxy IP.

**Assessment:** correct for Render's deploy topology — Render's edge proxy
terminates client connections and sets `X-Forwarded-For` itself (it does not
blindly forward client-supplied XFF), so trusting all upstream hops
(`forwarded-allow-ips='*'`) is standard/safe *because* the only upstream hop
reachable is Render's own proxy — the app is not directly internet-exposed.
This is an assumption about the platform, not something this repo enforces, but
it matches how every PaaS-fronted FastAPI app is deployed. No code change
needed. **If the service were ever exposed with a public direct port bypassing
Render's edge, this would become spoofable — not applicable to the current
`render.yaml` service definition.**

---

## 3. Body / message / history caps — MED (Content-Length-only enforcement)

- `api/middleware.py:33-45` (`BodySizeLimitMiddleware.dispatch`): checks
  `request.headers.get("content-length")` only, rejects with 413 if it exceeds
  `MAX_REQUEST_BODY_BYTES`. If the header is absent or malformed (e.g. chunked
  transfer-encoding, no Content-Length), the code **falls through and lets the
  request proceed** (`middleware.py:41-43`: `except ValueError: pass`; no
  `content_length is None` branch rejects either — absence is treated as pass).
- The module docstring (`api/middleware.py:14-19`) explicitly documents this as
  a known, deliberate limitation: reassigning `request._receive` under
  Starlette's `BaseHTTPMiddleware` breaks downstream body parsing, so true
  streaming byte-counting was not implemented; the comment claims "uvicorn's
  own framing limits backstop the chunked edge case" — this is not itself
  verified/tested in this repo, it's an assumption about uvicorn defaults.
- `MAX_MESSAGE_LENGTH` / `MAX_HISTORY_ITEMS` (`api/dependencies.py:77-78`,
  defaults 2000 / 50) are enforced via Pydantic `Field(max_length=...)`
  constraints (`api/schemas.py:197,240,245`) — these apply **after** FastAPI
  has already fully read and JSON-parsed the body, so a large body that slips
  past the Content-Length gate is still buffered into memory before rejection.

**This is a documented, not hidden, gap** — no doc/code mismatch, but worth a
launch-gate decision: a chunked POST with no Content-Length is a legitimate way
to bypass the 413 guard. Realistic exploitability is low (requires deliberately
crafting a chunked request; most HTTP clients/CDNs send Content-Length for JSON
bodies) but it is a genuine bypass path, not just theoretical.

**Fix (if closing before public launch):** enforce a hard body-size ceiling via
uvicorn/ASGI server config (e.g. a reverse-proxy-level body-size limit on
Render, or an ASGI-level streaming byte counter that aborts the connection
rather than reassigning `_receive`), rather than relying solely on
application-level header inspection.

---

## 4. Cost guard — MED (confirmed TOCTOU; matches known-deferred docs, no mismatch)

`api/agent/cost_guard.py`:
- Daily/session budget checks (`is_over_budget`, `is_session_over_budget`) read
  the current Redis counter, and increments (`register_cost`,
  `register_session_cost`) happen in a **separate** later call — not a single
  atomic Redis transaction (no Lua script / `MULTI`/`WATCH`). Concurrent
  requests can each read "under budget" before any of them increments,
  allowing the aggregate to overshoot the $0.50 session / $20 daily cap.
- Streaming partial-cost gap: in `api/routes/chat_v2_stream.py`, the budget
  check happens once before `run_agent(...)` is invoked; the actual cost is
  registered only after the full agent loop completes. A burst of concurrent
  requests arriving before any registers can collectively exceed the cap by up
  to N × per-turn cost, where N is the number of requests in flight before the
  first one's cost lands in Redis.
- Fail-open on Redis errors is a deliberate design choice (every guard read/write
  wrapped in try/except, degrading to "allow" on Redis unavailability) — correct
  trade-off for availability over strict enforcement, but means a Redis outage
  disables the cost guard entirely. Not a bug, a known trade-off — flag as info.

**Cross-check against docs:** `_bmad-output/planning-artifacts/epic-6-deploy-launch-plan.md`
and `_bmad-output/implementation-artifacts/epic-5-retrospective.md` both list
cost-guard TOCTOU / streaming partial-cost as explicitly known and deferred
from Epic 5. **Code matches the docs — no mismatch.** This is a legitimate,
already-tracked residual risk; low likelihood of real-world impact at soft-
launch traffic (requires deliberate concurrent-request abuse within one
session/IP/day to matter), acceptable to carry into soft launch, should be
closed (atomic Lua INCR+check) before scaling to public launch.

---

## 5. Auth — `api/auth.py` — **HIGH** (silent weak-secret fallback) + MED (OAuth aud not pinned)

### 5a. JWT_SECRET silent fallback — HIGH, BLOCKS PUBLIC LAUNCH

```
api/auth.py:23   SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-key-change-in-production")
```

If `JWT_SECRET` is unset at runtime, the app does not fail to start — it
silently signs and verifies all JWTs with the literal string
`"dev-secret-key-change-in-production"`. `render.yaml` marks `JWT_SECRET` as
`sync: false` (must be entered manually in the Render dashboard) — nothing in
code enforces that it was actually set. If a deploy ever runs without it
configured, anyone who knows this well-known default (it's in this public
audit doc and would be in the OSS/private repo source) can forge a valid
access token for **any** user id, fully bypassing authentication.

**Fix:** fail fast at import/startup — e.g.
```python
SECRET_KEY = os.environ["JWT_SECRET"]  # raises KeyError if unset
```
or an explicit check with a clear error message, gated on `APP_ENV=production`
if a default is still wanted for local dev.

### 5b. Algorithm / expiry handling — correctly implemented (info)

- `api/auth.py:34-35`: `jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])`
  with `ALGORITHM = "HS256"` (line 24) — algorithm list is explicitly pinned,
  no "none"-algorithm or algorithm-confusion vulnerability.
- `create_access_token` (`api/auth.py:29-31`) sets `exp` in the payload;
  `python-jose`'s `jwt.decode` validates `exp` by default and no call site
  passes `options={"verify_exp": False}` — expiry is enforced correctly.

### 5c. Google OAuth token verification — MED

`api/routes/auth.py` (Google OAuth flow, ~line 84-121): verifies the Google
ID token via the legacy `GET https://oauth2.googleapis.com/tokeninfo?id_token=...`
endpoint rather than local signature verification against Google's JWKS (the
`google-auth` library's `id_token.verify_oauth2_token(..., audience=...)`).
This endpoint is Google-sanctioned but explicitly documented by Google as
**not recommended for production** (rate-limited, extra network hop per
login). The audience (`aud`) claim — i.e. confirmation the token was issued
for *this app's* `GOOGLE_CLIENT_ID` and not some other Google OAuth client —
was not observed being checked against `GOOGLE_CLIENT_ID` in the response
handling. Still requires a validly Google-signed token (can't be forged), so
severity is medium not high, but a token minted for a different Google OAuth
client could potentially be accepted.

**Fix:** switch to `google.oauth2.id_token.verify_oauth2_token(token, request, audience=settings.google_client_id)`.

### 5d. `get_optional_user` — anonymous bypass check — no bypass found (info)

`api/auth.py` `get_optional_user`: never raises — returns `None` on missing,
expired, malformed token, or inactive user (by design, per the module
docstring: "NEVER blocks anonymous requests — critical invariant").
It does **not** itself enforce rate-limit or cost-guard checks, but those are
independently enforced at the route layer regardless of auth state:
- Rate limiting via `@limiter.limit(...)` decorator (keyed by IP, applies to
  every request whether authenticated or not).
- Cost guard via an explicit check in `chat_v2_stream.py` keyed by
  session-id-or-IP (`cost_cap_key`), so anonymous users are capped too, just
  bucketed by IP rather than user id.

No confirmed bypass for anonymous users on either control.

---

## 6. Secrets — INFO (clean)

- `render.yaml` marks every true secret `sync: false` (not committed inline):
  `CORS_ORIGINS`, `GEMINI_API_KEY`, `JWT_SECRET`, `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY`. Non-secret inline values are
  plain config: `APP_ENV=production`, `LOG_LEVEL=INFO`,
  `PER_SESSION_COST_BUDGET_USD=0.50`, `DAILY_COST_BUDGET_USD=20.0`,
  `CHAT_RATE_LIMIT=20/minute`, `SEARCH_RATE_LIMIT=60/minute`,
  `MAX_REQUEST_BODY_BYTES=524288`, `MAX_MESSAGE_LENGTH=2000`,
  `MAX_HISTORY_ITEMS=50`, `SEARCH_CACHE_TTL=300`, `INTENT_CACHE_TTL=120`.
  `DATABASE_URL`/`DATABASE_URL_SYNC` via `fromDatabase`, `REDIS_URL` /
  `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` via `fromService` — correctly
  derived from Render-managed resources, never inlined.
- Repo-wide grep for common secret patterns (`AIza`, `sk-`, hardcoded
  `Bearer <token>`, hardcoded DB passwords) found exactly one hit:
  `tests/api/test_auth.py:273` — a literal test fixture string
  `"Bearer garbage.token.here"` used to test invalid-token handling. **Not a
  real secret** — no redaction needed, flagged only for completeness.
- `.gitignore:2` contains `.env`. `git ls-files | grep -i '\.env'` returns only
  `.env.example`, `frontend/.env.example`, `frontend/.env.production` — no
  bare `.env` tracked. `git log --all --oneline -- .env` returns empty —
  `.env` was never committed at any point in this repo's history.
- **Follow-up (not fully verified in this audit):** `frontend/.env.production`
  is a tracked file with "production" in its name — its contents were not
  inspected here. Recommend a human spot-check that it contains only
  build-time public values (e.g. `VITE_API_BASE_URL`) and no secret API keys,
  since Vite bakes `.env.production` values into the client bundle at build
  time regardless of gitignore status.

---

## 7. SSE endpoint `POST /api/chat/v2/stream` — MED (no disconnect handling, no concurrency cap)

`api/routes/chat_v2_stream.py:70-181`:
- Rate limiting applies (`@limiter.limit(chat_rate_limit)`, default
  `20/minute` per IP) — bounds *new* stream opens per minute, but does not cap
  the number of *concurrently open* long-lived streams from one client within
  that window (e.g. 20 streams opened in the same minute can all stay open
  simultaneously).
- `event_stream()` (`chat_v2_stream.py:123-181`) has a single `yield` (the
  initial `thinking` event) before `await run_agent(...)` runs to completion;
  there is no periodic `await request.is_disconnected()` check during that
  await. If the client disconnects (closes tab, network drop) mid-stream, the
  server has no way to observe this until the next `yield`, so the in-flight
  LLM call and any tool calls continue to completion regardless — full LLM
  cost is incurred and registered even though no one will ever see the
  response.
- Per-call timeouts exist inside the agent loop (`api/agent/loop.py`:
  `request_timeout_s=30.0` for LLM calls, plus a `tool_timeout_s` for tool
  calls) which bound the *worst case* duration of one turn, but this bounds
  cost/duration, not concurrency or wasted-work-on-disconnect.
- No doc in `_bmad-output/` claims concurrent-stream limiting or disconnect-based
  cancellation was implemented — this is an unaddressed gap, not a doc/code
  mismatch.

**Fix:** wrap the `run_agent(...)` await with a disconnect watcher (e.g.
`asyncio.wait({asyncio.create_task(run_agent(...)), asyncio.create_task(_watch_disconnect(request))}, return_when=FIRST_COMPLETED)` and cancel the agent task if disconnect wins), and consider a simple per-IP or
per-user concurrent-stream semaphore if abuse is observed post-launch.

---

## What's already correctly handled (launch-positive)

- CORS wildcard+credentials guard is real and correctly implemented (`api/main.py:96-99`).
- Rate-limit IP keying is correctly configured for the Render proxy topology
  (`scripts/start.sh:9-14`, `api/dependencies.py:114`).
- JWT algorithm is pinned (`HS256` only) and expiry is validated by default —
  no algorithm-confusion or expired-token bypass.
- `get_optional_user` correctly never blocks anonymous users while rate-limit
  and cost-guard controls still apply to them independently, keyed by IP.
- Secrets are correctly split between Render-managed `sync: false` env vars
  and non-secret inline config; `.env` was never committed to git history.
- Cost-guard fail-open behavior on Redis errors is a deliberate, reasonable
  availability trade-off, not an oversight.
- Body-size, message-length, and history-length caps exist and are wired
  end-to-end for the standard (Content-Length-bearing) request path.

## Recommended fix order before public launch

1. **Block:** fail-fast on missing `JWT_SECRET` (§5a) — `api/auth.py:23`.
2. Pin Google OAuth `aud` / migrate off `tokeninfo` (§5c) — `api/routes/auth.py:~93`.
3. Add SSE disconnect cancellation (§7) — `api/routes/chat_v2_stream.py`.
4. Add production fail-fast guard for `CORS_ORIGINS == "*"` (§1) — `api/main.py`.
5. Atomic cost-guard check-and-increment (§4) — `api/agent/cost_guard.py` (already tracked in Epic 5 retro/Epic 6 plan as deferred work — this audit confirms it's still open).
6. Human spot-check `frontend/.env.production` contents (§6).
7. Consider hard body-size enforcement below the app layer for the chunked-encoding edge case (§3).
