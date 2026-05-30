---
project_name: 'FindMe'
user_name: 'Barakganon'
date: '2026-04-30'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality', 'workflow', 'critical_rules']
status: 'complete'
rule_count: 76
optimized_for_llm: true
---

# Project Context for AI Agents

_Critical rules and patterns AI agents must follow when implementing code in this project. Focuses on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

**Backend**
- Python 3.11+
- FastAPI 0.115.6
- SQLAlchemy 2.0.36 (asyncio mode — use `async_sessionmaker`, `AsyncSession`)
- asyncpg 0.30.0 (runtime driver; psycopg2-binary for Alembic CLI only)
- Alembic 1.14.0 (migrations at head: 0008)
- PostgreSQL with pgvector extension + GeoAlchemy2 0.17.1
- Redis (redis[asyncio] 5.2.1) — cache + Celery broker
- Celery 5.4.0 (scraper task queue)
- OpenAI SDK 1.58.1 — pointed at Gemini (NOT OpenAI)
- Instructor 1.7.2 (structured Gemini output)
- SlowAPI 0.1.9 (rate limiting)
- python-jose[cryptography] 3.3.0 (JWT)
- passlib[bcrypt] 1.7.4 (password hashing)
- authlib 1.3.0 (Google OAuth)
- Pydantic v2 2.10.3 + pydantic-settings 2.7.0
- pytest 8.3.4 + anyio[trio] 4.7.0 (async test runner)
- Playwright 1.49.0 (scraping — memory-heavy, max 2 Celery workers)
- httpx 0.28.1 (async HTTP client)

**Frontend**
- React 18.2.0
- TypeScript 5.0.0 (strict mode enabled)
- Vite 5.0.0 (dev server proxy: `/api` → `localhost:8000`)
- Tailwind CSS 3.4.0
- Leaflet 1.9.4 + react-leaflet 4.2.1 (maps)
- No state management library — React state + localStorage only

**AI / LLM**
- Model: `gemini-2.5-flash`
- Embedding model: `text-embedding-004`
- Client base URL: `https://generativelanguage.googleapis.com/v1beta/openai/`

## Critical Implementation Rules

### Language-Specific Rules

**Python**
- All Python files must start with `from __future__ import annotations`
- All routes, DB operations, and AI calls must be `async`/`await` — no sync code in the FastAPI request path
- All new functions must have full type hints
- All new schemas go in `api/schemas.py` — never define Pydantic models inline in route handlers
- Use `pydantic_settings.BaseSettings` (not `os.getenv`) for all settings access
- Wrap all Gemini JSON parsing in `try/except`; strip ` ```json ` fences before `json.loads()`; fall back to `intent=clarify` on failure
- Never hardcode `"buyme"` in business logic — always pass `voucher_network` as a parameter through the call chain

**TypeScript / React**
- TypeScript strict mode is on — no `any`, no implicit `undefined`
- All API types must mirror the Pydantic schemas in `api/schemas.py`
- No auth library — use `fetch()` with manual `Authorization: Bearer <token>` header injection in `frontend/src/api.ts`
- JWT stored in `localStorage`; on 401 response clear token silently and fall back to anonymous mode (never redirect to a login page)
- All user-facing text must be in Hebrew (RTL)
- UI layout is RTL — use `dir="rtl"` and Tailwind `text-right` defaults

### Framework-Specific Rules

**FastAPI**
- All LLM prompts must live in `api/prompts.py` — never inline prompt strings in route handlers
- Use `get_optional_user` (not `get_current_user`) on any endpoint anonymous users can call — anonymous access must never be blocked
- Rate limiter instance is in `api/main.py`; import and apply `@limiter.limit()` on new public endpoints
- Register all new routers in `api/main.py` via `app.include_router()`
- DB dependency: `get_db()` → `AsyncSession`; AI client: `get_ai_client()` → `AsyncOpenAI` at Gemini; Redis: `get_redis()` — all from `api/dependencies.py`

**SQLAlchemy / DB**
- All models inherit `BaseMixin` (UUID pk, `created_at`, `updated_at`) and `Base`
- UUID primary keys only — never integer sequences
- Use `JSONB` for flexible metadata fields
- pgvector column is `embedding_vector` — do not rename
- All vector operations use `text()` raw SQL — pgvector syntax is not supported by the SQLAlchemy ORM
- Migrations: `NNNN_description.py` (4-digit zero-padded); current head is **0008**

**Search / AI (do not alter the core flow)**
- Hybrid search: pgvector cosine similarity first, ILIKE keyword fallback if no vector results
- Import `_embed` and `_vec_literal` from `api/routes/search.py` — never duplicate embedding logic
- Import store query builder from `api/routes/stores.py` — never duplicate
- Intent parser: `max_tokens=256`; response composer: `max_tokens=200`
- Cache intent results 2 min, search results 5 min in Redis

**React / Frontend**
- No tabs — `App.tsx` renders only `<ChatInterface />`
- Suggestion chips appear on first load only; hide permanently after first message sent
- GPS flow is inline — `📍 שתף מיקום` button inside assistant bubble; never modal or page navigation
- Max 6 result cards per response; "ועוד X" link if more
- `StoreMap` fixed at 220px height, `rounded-xl`
- `ResultCard`, `StoreCard`, `StoreMap`, `FilterBar` are reused inside chat bubbles — do not remove

### Testing Rules

- Test runner: `pytest` with `anyio` — async tests use `@pytest.mark.anyio`
- `anyio_backend` fixture returning `"asyncio"` is in `tests/conftest.py` — do not redeclare per-file
- Never make real Gemini/LLM API calls in tests — mock with `MagicMock` via the `ai_client` fixture from `conftest.py`
- Never make real DB connections in unit tests — mock at the dependency layer
- Test files live in `tests/api/` mirroring the route they test (e.g. `chat.py` → `test_chat.py`)
- Run: `pytest tests/` — current baseline is **29/29 passing**; never submit code that breaks this
- Each chat/search route needs: happy path, missing fields, anonymous fallback, clarify/error fallback
- LLM token budget enforcement and JSON parse fallback must be tested explicitly for chat routes
- Every new tool in `api/agent/tools/` MUST have a matching `tests/api/test_tool_<name>.py`
  file with at least: happy path, empty/no-result path, error path, anonymous (when
  applicable), and per-parameter coverage for each tool parameter that has documented
  behavior (W8)

### Code Quality & Style Rules

**File & Folder Structure**
- `api/schemas.py` — all Pydantic request/response models (one file, not split)
- `api/prompts.py` — all LLM prompt strings (never inline elsewhere)
- `api/routes/` — one file per route domain (search, chat, stores, auth, users, admin)
- `api/dependencies.py` — all FastAPI `Depends()` providers
- `db/models.py` — all SQLAlchemy ORM models (one file)
- `frontend/src/components/` — React components (PascalCase filenames)
- `frontend/src/api.ts` — all `fetch()` calls to the backend (one file)
- `frontend/src/types.ts` — shared TypeScript types

**Naming Conventions**
- Python: `snake_case` for files, functions, variables; `PascalCase` for classes
- TypeScript: `PascalCase` for components and interfaces; `camelCase` for functions and variables
- Migration files: `NNNN_short_description.py` (4-digit prefix)
- Branch names: `feature/`, `fix/`, `infra/`, `refactor/`, `test/`, `chore/`

**Comments & Docs**
- No comments explaining what code does — name things clearly instead
- Module-level docstrings: list what the file provides and the data flow (follow `api/routes/search.py` as the pattern)
- No multi-line comment blocks; one short line max when a WHY is non-obvious

**No Formatter Config**
- No ESLint, Prettier, or Black configs present — match existing code style by example

### Development Workflow Rules

**Git Branching & Commits**
- Branch naming: `feature/`, `fix/`, `infra/`, `refactor/`, `test/`, `chore/` + short description
- Commit format: Conventional Commits — `<type>(<scope>): <imperative description>`
  - Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `infra`
  - Example: `feat(chat): add Redis intent cache to skip Gemini on repeated queries`
- Never `git add .` — always stage specific files
- Never commit `.env` — it is in `.gitignore`
- Never force-push to `master`
- Use `--no-ff` on all merges to `master` to preserve branch history
- Minimum 8–15 commits per sprint — commit after each logical unit, not once at the end

**Task Completion Gate**
- A task is NOT done until: branch pushed to `origin`, `STATUS.md` updated, tests passing

**Local Dev Stack**
- Backend: `uvicorn api.main:app --reload --host 0.0.0.0 --port 8000`
- Frontend: `cd frontend && npm run dev` (proxies `/api` → `:8000`)
- Redis: `redis-server` (required for cache + Celery)
- Celery worker: `celery -A scraper.scheduler worker --loglevel=info -Q scraper --concurrency=2`
- DB migrations: `python -m alembic upgrade head`

**Environment Variables**
- Never hardcode secrets — always use `Settings` from `api/dependencies.py`
- Required: `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`
- Optional: `GOOGLE_MAPS_API_KEY` (geocoding), `GOOGLE_CLIENT_ID/SECRET` (OAuth)
- New dependencies must be added to `requirements.txt` before committing

### Critical Don't-Miss Rules

**Never duplicate core logic**
- Never rewrite search logic — import `_embed`, `_vec_literal` from `api/routes/search.py`
- Never rewrite store query logic — import from `api/routes/stores.py`
- Never change the search algorithm — 99.3% embedding coverage, it works

**Anonymous users must always work**
- `POST /api/chat`, `POST /search`, `POST /stores/search` must never require auth
- Use `get_optional_user` (returns `None` for anonymous) — never `get_current_user` on public endpoints

**LLM safety**
- Always strip ` ```json ` fences before `json.loads()` on Gemini output
- Always `try/except` around Gemini JSON parsing; fallback to `intent=clarify`
- Never run `api/inference.py` in the main request path — always `asyncio.create_task()` so it never delays the response
- Never cache conversation history in Redis — keep it in frontend React state only

**DB safety**
- Always run `python -m alembic upgrade head` after adding a migration
- Never modify the core SQL in `search.py` or `stores.py` — import and reuse
- `last_price_change_at` on `store_products` is updated by Celery only — do not update it from API routes

**Frontend safety**
- Never add tabs or split the chat into separate search panels
- Auth (register/login) is always inline — never navigate away from the chat
- Never store anything sensitive beyond the JWT token in `localStorage`

**Scraper safety**
- Max 2 Celery workers locally — Playwright is memory-heavy
- Never use APScheduler or cron — Celery Beat is the scheduler
- Never add a second message queue

**Security**
- CORS origins come from `CORS_ORIGINS` env var — never hardcode
- Security headers applied globally by `SecurityHeadersMiddleware` in `api/main.py` — do not add per-route
- Rate limits: `200/minute` default; `/search` and `/api/chat` have explicit stricter limits

---

## Usage Guidelines

**For AI Agents:**
- Read this file before implementing any code in this project
- Follow ALL rules exactly as documented — especially the "Critical Don't-Miss" section
- When in doubt, prefer the more restrictive option
- Never duplicate `search.py` or `stores.py` logic — always import
- Update this file if new patterns emerge during implementation

**For Humans:**
- Keep this file lean — rules only, no tutorials
- Update when the technology stack or conventions change
- Remove rules that become obvious over time

_Last Updated: 2026-04-30_
