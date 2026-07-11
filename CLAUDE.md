# FindMe — CLAUDE.md
> Read at session start. Update **Current State** after completing a task.

## What This Is

Conversational search for Israeli gift-card holders. Start with BuyMe (buyme.co.il);
תו הזהב and נופשונית planned. Hebrew/English free text in, Hebrew structured answer out.

**Value prop:** "I have a BuyMe gift card. Help me use it."

## Current State (2026-07-11)

- FastAPI `:8000`, React+TS `:5173`, Postgres+pgvector `:5432`, Redis cache
- Migrations at **0009 (head, agent_traces)**. **135,865 products, 99.3% embedded**
- Routes: `POST /search`, `POST /stores/search`, `POST /api/chat` (v1), `POST /api/chat/v2/stream` (SSE),
  `POST /api/auth/*`, `GET/PUT /api/users/me/*`, `GET /api/admin/health[/detailed]`,
  `GET /api/admin/cost-summary` (daily cost-guard state)
- JWT auth (email + Google OAuth). **Anonymous users always work** — never block them
- Single chat screen: chips, GPS, ProfileDrawer, results tray, memory chips, SSE streaming
- **v2 agentic loop is active** — tool-calling LLM (`api/agent/`) with session memory in Redis (2h TTL)
- **Epic 5 merged to master** (PRs #9–#12, 2026-06-14).
- **Epic 6 pre-launch prep merged (2026-07-11, autonomous).** Test suite **287 passing**.
  Security hardening (prod fail-fast on missing `JWT_SECRET` / wildcard CORS; OAuth `aud`
  pinning — all gated on `APP_ENV=production`); `render.yaml` modernized to Render native
  pgvector via `fromDatabase`; `scripts/migrate_catalog.sh` (dry-run-safe catalog copy);
  Dockerfile fixed (missing Chromium runtime deps `libxfixes3`/`libpango`/`libcairo2`);
  frontend prod wiring (`.env.production`, `vite-env.d.ts`); Playwright E2E kill-gate suite
  (`frontend/e2e/`); +16 backend tests. Cost guard, rate limits, body guard already in from Epic 5.
- **Not yet deployed.** All go-live steps are documented + Barak-gated in
  `_bmad-output/implementation-artifacts/6-1-LAUNCH-CHECKLIST.md` (wire DB/Redis, paste
  GEMINI/GOOGLE secrets, `alembic upgrade head` + `CREATE EXTENSION vector`, load catalog,
  set `CORS_ORIGINS`, smoke `/api/chat/v2/stream`). Live service exists (`findme-rau7.onrender.com`,
  oregon/free, expires 2026-07-15); render.yaml targets frankfurt/standard — reconcile at launch.
  Security audit: `_bmad-output/implementation-artifacts/6-security-audit.md`.

**Pending data tasks (no sprint blocker):**
- `python -m db.run_geocoding` (needs `GOOGLE_MAPS_API_KEY`)
- `python -m normalization.deduplication`
- Re-run scrapers to populate `image_url` (1,743 done for Femina; rest pending)

## Sprint Status: Epic 5 complete → Epic 6 (deploy + launch) planned

Epic 5 spec: `_bmad-output/planning-artifacts/findme-v2-sprint-plan.md`.
Next epic plan: `_bmad-output/planning-artifacts/epic-6-deploy-launch-plan.md`.
Sprint tracking: `_bmad-output/implementation-artifacts/sprint-status.yaml`.
Retro: `_bmad-output/implementation-artifacts/epic-5-retrospective.md`.

| Week | Story | Status |
|------|-------|--------|
| W1–W6 | 5.1–5.6 (eval, loop, tools, telemetry, streaming, prompts) | done |
| W7 | 5.7 UI polish + repair (tray, memory chips, mind-changer) | **review** (manual validation pending) |
| W8 | 5.8 test rewrite | **done** (merged PR #9) |
| W9 | 5.9 cost/deploy hardening | **done** (merged PR #10) |

**Epic 5 is functionally complete.** Only carry-forward: 5.7 manual UI validation
(+ the flagged anon `👦 ילד 3` chip decision). Next up is **Epic 6 — Production
Deploy + Soft Launch** (the deferred deploy, now that hardening is in). AWS deploy
(Epic 1) is **superseded** — v2 pivot moved deploy target to Render.

## Architecture (v2 — agentic loop)

```
User msg (HE/EN)
   ▼
POST /api/chat/v2/stream  (SSE: thinking → tool_call → final / error)
   ▼
agent loop  (api/agent/)
   tools: search_products, search_stores, get_user_context,
          recall_history, clarify
   memory: SessionState in Redis (2h TTL), derived_facts extracted from tool args
   ▼
ChatResponseV2 { message, intent, product_results?, store_results?,
                 needs_location, chips: MemoryChip[], voucher_network, ... }
```

- v1 `POST /api/chat` (single-shot Gemini intent parser) stays as fallback for `terminated_by: 'cost_budget'`
- Inference (`api/inference.py`) runs via `asyncio.create_task()` after every turn — never blocks
- Inferred attrs **enrich** search (boost), never **restrict**. Confidence < 0.5 stored but unused

## Coding Rules

- **Async/await everywhere** in FastAPI routes and DB ops
- **Gemini via `AsyncOpenAI`** → `https://generativelanguage.googleapis.com/v1beta/openai/`
- **All LLM prompts in `api/prompts.py`** — never inline
- **Parse Gemini JSON safely** — strip ```json fences, try/except, fall back to `intent=clarify`
- **Hebrew for user-facing text**; English fine in code/comments
- **Type hints + Pydantic v2** for all new code
- **Never hardcode "buyme"** in business logic — always pass `voucher_network`
- **Use `get_optional_user`** on chat routes so anonymous always works
- **Token budgets:** intent=256, response=200, attribute extractor=300

## What NOT To Do

- Don't rewrite `search.py` / `stores.py` — import `_embed`, `_vec_literal`, query builders
- Don't change the search algorithm (99.3% coverage works)
- Don't inline LLM prompts outside `api/prompts.py`
- Don't cache chat history in Redis — frontend state owns it
- Don't add APScheduler/cron — Celery only
- Don't run Celery with >2 workers locally (Playwright is memory-heavy)
- Don't filter search results based on inferred attributes — boost only
- Don't make real Gemini/DB calls in tests — mock them

## Environment

```bash
cd /Users/barakganon/personal_projects/FindMe && source .venv/bin/activate

# Run
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev
redis-server
celery -A scraper.scheduler worker --loglevel=info -Q scraper --concurrency=2
celery -A scraper.scheduler beat --loglevel=info
docker-compose up                                # full stack

# DB
python -m alembic upgrade head
python -m db.embed_products
python -m db.run_geocoding
python -m normalization.deduplication

# Tests
.venv/bin/python -m pytest tests/ -p no:cacheprovider
```

`.env` keys: `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND`, `SEARCH_CACHE_TTL=300`, `INTENT_CACHE_TTL=120`,
`EMBED_BATCH_SIZE=100`, `SHOPIFY_SCRAPE_CONCURRENCY=5`, `GOOGLE_MAPS_API_KEY`,
`JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

## Git Workflow

- Branches: `feature/<x>`, `fix/<x>`, `infra/<x>`, `refactor/<x>`, `test/<x>`, `chore/<x>`
- Conventional commits: `<type>(<scope>): <imperative>` — `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `infra`
- One commit per logical unit; target 8–15 per sprint. Don't batch
- Merge with `--no-ff` from master after PR review

**Never:** `git add .`, commit `.env`/`__pycache__/`/`node_modules/`/`dist/`,
force-push to master, merge with failing tests, finish without pushing.
