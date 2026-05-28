# FindMe — CLAUDE.md
> Read at the start of every session. Update **Current State** after completing any task.

---

## What This Project Is

FindMe is a conversational search assistant that helps Israeli consumers find where to spend
gift card vouchers — starting with BuyMe (buyme.co.il), with תו הזהב, נופשונית, and others planned.

Users type natural Hebrew or English requests in full sentences. The assistant understands
intent, queries the right data sources, and returns a helpful structured answer in Hebrew.

**Core value proposition:** "I have a BuyMe gift card. Help me use it."

---

## Current State (as of 2026-05-02)

- FastAPI backend on `:8000`, React + TS frontend on `:5173`, Postgres + pgvector on `:5432`
- Migrations at **0008 (head)**
- **135,865 products, 134,963 embedded (99.3%)**
- Hybrid search: pgvector cosine + ILIKE fallback. Routes include `POST /search`, `POST /stores/search`,
  `POST /api/chat`, `POST /api/auth/*`, `GET/PUT /api/users/me/*`, `GET /api/admin/health[/detailed]`
- Single chat-screen UI: suggestion chips, inline GPS, ProfileDrawer, auth wired, image display
- Redis cache: search results (5 min) + intent (2 min). Graceful degradation if Redis down
- JWT auth (email + Google OAuth). **Anonymous users always work** — never block them
- User data: locations, vouchers, preferences, favorites, search history, inferred attributes
- Filters: `min_price` + `max_price`, availability (hide OOS by default), brand
- Docker Compose starts the full stack (`docker-compose up`). `docker-compose.override.yml` for dev
- **29/29 tests passing**

**Completed sprints:** Scraping → DB → Normalization → Hybrid search → React frontend →
Embeddings (99.3%) → Pagination + brand filter → Store search + map → LLM Chat → UI redesign →
Infrastructure (Redis + Celery + price_changes + admin health) → User Accounts → Data Quality →
Production infra (Docker hardening, S3 OAC, CI smoke test).

**Pending data tasks (no sprint blocker):**
- Add `GOOGLE_MAPS_API_KEY` to `.env` → `python -m db.run_geocoding` (geocodes ~500 physical stores)
- `python -m normalization.deduplication` (merges duplicate products across stores; initial run: 10 merges)
- Re-run scrapers to populate `image_url` (1,743 done for Femina; rest pending)

---

## Active Sprint: Production Deployment (AWS)

**Goal:** deploy FindMe publicly. Frontend to S3+CloudFront, backend to EC2/ECS, SSL, custom domain.

| # | Task | Where | Status |
|---|------|-------|--------|
| 1 | Containerize backend | `Dockerfile`, `docker-compose.yml` | ✅ Done |
| 2 | Deploy frontend → S3 + CloudFront | `frontend/`, AWS | TODO |
| 3 | Deploy FastAPI → EC2 or ECS | `Dockerfile`, AWS | TODO |
| 4 | SSL cert + custom domain | ACM, Route53 | TODO |
| 5 | Rate limiting on `/search`, `/api/chat` | `api/main.py` | ✅ Done |
| 6 | Uptime monitoring | UptimeRobot / CloudWatch | TODO |

---

## Upcoming Sprint: Store Enrichment & Chain Support

**Goal:** improve store-level search and geo grouping by understanding chains and multi-category context.

| # | Task | Where |
|---|------|-------|
| 1 | DB: add `parent_chain_id`, `buyme_categories` (JSONB), `metadata_json` (JSONB) | `db/models.py` + migration |
| 2 | Save full category list + redemption links | `scraper/buyme_store_scraper.py` |
| 3 | LLM enrichment: identify chains, extract meta from slogans/terms | `scraper/enrich_stores.py` (new) |
| 4 | Geo search: group results by chain | `api/routes/stores.py` |

---

## Architecture (LLM Chat Layer)

```
User message (HE/EN free text)
     ▼
POST /api/chat
     ▼
Intent Parser (Gemini) → ParsedIntent {
   intent: product_search | store_search | help | clarify,
   product_query, brand, max_price, city, location_hint,
   needs_user_location, store_type, voucher_network
}
     ├── product_search → reuse POST /search logic
     ├── store_search   → reuse POST /stores/search logic
     ├── clarify        → return question to user
     └── help           → canned text
     ▼
Response Composer (Gemini) → short Hebrew answer
     ▼
ChatResponse { message, intent, product_results?, store_results?,
               needs_location, location_prompt?, voucher_network }
```

**Location resolution:**
| User says | Resolution |
|---|---|
| "לידי" / "באזור שלי" / "קרוב אלי" | `needs_location=true` → frontend prompts GPS |
| "בתל אביב" / "באילת" | city extracted directly |
| "ליד המלון הזה" with URL in history | Gemini extracts from history |
| GPS already in `session_context` | coordinates passed automatically |

For logged-in users, `chat_utils.build_user_context_block()` injects preferences/history into
the intent parser prompt; `merge_preferences_into_search()` fills in unstated values from prefs.
Inference (`api/inference.py`) runs via `asyncio.create_task()` after every turn — never blocks
the response. Inferred attributes **enrich** search (boost), never **restrict**. Anything with
confidence < 0.5 is stored for transparency but unused.

---

## Coding Rules

- **Async/await everywhere** in FastAPI routes and DB ops
- **Gemini for LLM calls** via `AsyncOpenAI` pointed at `https://generativelanguage.googleapis.com/v1beta/openai/`
- **All LLM prompts in `api/prompts.py`** — never inline in route handlers
- **Parse Gemini JSON safely** — strip ```json fences, `json.loads()` in try/except, fall back to `intent=clarify`
- **Hebrew for user-facing text**; English fine in code/comments
- **Type hints + Pydantic models** for all new code
- **Never hardcode "buyme"** in business logic — always pass `voucher_network`
- **Env vars only** for keys — `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `GOOGLE_MAPS_API_KEY`, etc.
- **LLM token budgets:** intent=256, response=200, attribute extractor=300
- **Use `get_optional_user`** (not `get_current_user`) on `/api/chat` so anonymous always works

## What NOT To Do

- Don't rewrite `search.py` or `stores.py` — import and reuse `_embed`, `_vec_literal`, query builders
- Don't change the search algorithm — 99.3% coverage works
- Don't hardcode `"buyme"` anywhere business-logic facing
- Don't inline LLM prompts outside `api/prompts.py`
- Don't add a queue other than Redis/Celery; don't add APScheduler or cron
- Don't cache chat conversation history in Redis — frontend state owns it
- Don't run Celery with >2 workers locally (Playwright is memory-heavy)
- Don't add APM/monitoring stacks now (Prometheus, Grafana) — comes with deployment
- Don't filter search results based on inferred attributes — boost only

---

## Environment

```bash
cd /Users/barakganon/personal_projects/FindMe
source .venv/bin/activate

# Backend
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm run dev

# Redis (Celery + cache)
redis-server
redis-cli ping            # should return PONG

# Celery
celery -A scraper.scheduler worker --loglevel=info -Q scraper --concurrency=2
celery -A scraper.scheduler beat --loglevel=info

# DB
psql postgresql://barakganon@localhost/buyme_search
python -m alembic upgrade head
python -m db.embed_products            # re-embed unembedded products
python -m db.run_geocoding             # needs GOOGLE_MAPS_API_KEY
python -m normalization.deduplication
python -m scraper.sitemap_scraper      # re-run failed scrapers

# Full stack
docker-compose up
```

`.env` keys: `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND`, `SEARCH_CACHE_TTL=300`, `INTENT_CACHE_TTL=120`,
`EMBED_BATCH_SIZE=100`, `SHOPIFY_SCRAPE_CONCURRENCY=5`, `GOOGLE_MAPS_API_KEY`,
`JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

---

## Multi-Agent Architecture

Multiple Claude Code agents can work in parallel. Each owns a folder; agents never edit outside
their domain.

| Agent | Owns | Reads-only | Never touches |
|---|---|---|---|
| Orchestrator | `CLAUDE.md`, `STATUS.md`, coordination | Everything | Nothing |
| API | `api/` | `db/models.py`, `api/schemas.py` | `scraper/`, `frontend/`, `normalization/` |
| DB | `db/`, `alembic.ini`, migrations | `api/schemas.py` | `api/routes/`, `scraper/`, `frontend/` |
| Scraper | `scraper/` | `db/models.py` | `api/`, `frontend/`, `normalization/` |
| Normalization | `normalization/` | `db/models.py` | `scraper/`, `api/`, `frontend/` |
| Frontend | `frontend/src/` | `api/schemas.py` (for types) | Everything else |
| Test | `tests/` | All source (read-only) | All source |

**Coordination:** if an agent needs work from another domain, it writes `# NEEDS: <agent> to <action>`
in its own file and flags the orchestrator. Status flows through `STATUS.md` only (append, never overwrite).

**Shared-file rules:**
- `api/schemas.py`, `api/prompts.py` → orchestrator writes first, read-only for others
- `api/main.py` → only API agent
- `db/models.py` → only DB agent
- `requirements.txt`, `CLAUDE.md` → only orchestrator

---

## Git Workflow

**Branches:** `feature/<x>`, `fix/<x>`, `infra/<x>`, `refactor/<x>`, `test/<x>`, `chore/<x>`.

**Every task:**
```bash
git checkout master && git pull origin master
git checkout -b <branch>
# work, commit often with conventional-commit messages
git push origin <branch>
# when done (orchestrator merges):
git checkout master && git pull
git merge --no-ff <branch> -m "Merge branch '<branch>': <summary>"
git push origin master
git branch -d <branch>
```

**Commit messages:** `<type>(<scope>): <imperative description>`
Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `infra`.
Example: `feat(cache): add Redis intent cache to skip Gemini on repeats`.

**Commit frequency:** one per logical unit (new file, wired file, migration, test, bug fix).
Target 8–15 commits per sprint — don't batch.

**Never:**
- `git add .` — always stage specific files
- commit `.env`, `__pycache__/`, `node_modules/`, `dist/`
- force-push to master
- merge a branch with failing tests
- finish a task without pushing the branch