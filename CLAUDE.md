# FindMe — CLAUDE.md
> Read at session start. Update **Current State** after completing a task.

## What This Is

Conversational search for Israeli gift-card holders. Start with BuyMe (buyme.co.il);
תו הזהב and נופשונית planned. Hebrew/English free text in, Hebrew structured answer out.

**Value prop:** "I have a BuyMe gift card. Help me use it."

## Current State (2026-05-30)

- FastAPI `:8000`, React+TS `:5173`, Postgres+pgvector `:5432`, Redis cache
- Migrations at **0008 (head)**. **135,865 products, 99.3% embedded**
- Routes: `POST /search`, `POST /stores/search`, `POST /api/chat` (v1), `POST /api/chat/v2/stream` (SSE),
  `POST /api/auth/*`, `GET/PUT /api/users/me/*`, `GET /api/admin/health[/detailed]`
- JWT auth (email + Google OAuth). **Anonymous users always work** — never block them
- Single chat screen: chips, GPS, ProfileDrawer, results tray, memory chips, SSE streaming
- **v2 agentic loop is active** — tool-calling LLM (`api/agent/`) with session memory in Redis (2h TTL)

**Pending data tasks (no sprint blocker):**
- `python -m db.run_geocoding` (needs `GOOGLE_MAPS_API_KEY`)
- `python -m normalization.deduplication`
- Re-run scrapers to populate `image_url` (1,743 done for Femina; rest pending)

## Active Sprint: Epic 5 — Agentic Conversation Refactor

Spec: `_bmad-output/planning-artifacts/findme-v2-sprint-plan.md`.
Sprint tracking: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

| Week | Story | Status |
|------|-------|--------|
| W1–W6 | 5.1–5.6 (eval, loop, tools, telemetry, streaming, prompts) | done |
| W7 | 5.7 UI polish + repair (tray, memory chips, mind-changer) | **review** (manual validation pending) |
| W8 | 5.8 test rewrite (40+ tool tests, target ≥187) | **ready-for-dev** |
| W9 | 5.9 cost/deploy hardening | backlog |

AWS deploy (Epic 1) is **superseded** — v2 pivot moved deploy target to Render.

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
