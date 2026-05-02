# FindMe — CLAUDE.md
> Read this file at the start of every session. Update the "Current Status" section after completing any task.

---

## What This Project Is

FindMe is a conversational search assistant that helps Israeli consumers find where to spend
gift card vouchers — starting with BuyMe (buyme.co.il), with תו הזהב, נופשונית, and others
planned for the future.

Users type natural Hebrew or English requests — full sentences, not just keywords — and the
assistant understands intent, extracts parameters, queries the right data sources, and returns
a helpful structured answer.

**The core value proposition:**
"I have a BuyMe gift card. Help me use it."

---

## Current State (as of 2026-05-02)

- FastAPI backend running at http://localhost:8000
- React + TypeScript frontend at http://localhost:5173
- PostgreSQL + pgvector at localhost:5432 — **migrations at 0008 (head)**
- **135,865 products, 134,963 embedded (99.3%)** — full vector search coverage ✅
- **POST /api/chat working** — intent parser + response composer, personalized for logged-in users ✅
- Hybrid search: pgvector cosine + ILIKE keyword fallback
- Routes: `POST /search`, `POST /stores/search`, `POST /api/chat`, `POST /api/auth/*`, `GET/PUT /api/users/me/*`, `GET /api/admin/health`, `GET /api/admin/health/detailed`
- Frontend: single chat screen (no tabs), suggestion chips, inline GPS, ProfileDrawer, auth wired, image display, "מחיר לא זמין"
- Redis cache: search results (5 min) + intent (2 min) — graceful degradation if Redis down
- JWT auth: register/login/Google OAuth, anonymous users always work
- User accounts: locations, vouchers, preferences, favorites, search history, inferred attributes
- Search filters: min_price + max_price range, availability filter (hide out-of-stock default), brand
- Deduplication: infrastructure wired (migration 0008, Celery task) — run `python -m normalization.deduplication` to execute
- Geocoder: Google Maps ready — add `GOOGLE_MAPS_API_KEY` to `.env`, then `python -m db.run_geocoding`
- **29/29 tests passing** ✅
- Docker Compose: `docker-compose up` starts full stack (api service now included)
- `docker-compose.override.yml` — dev overrides (ports, volume mounts) auto-applied locally
- BMad Method v6.6.1 installed — `_bmad-output/project-context.md` generated ✅

**Completed sprints:**
- ✅ Week 1–4: scraping, DB, normalization, hybrid search, React frontend
- ✅ Gemini paid tier → 99.3% embedding coverage
- ✅ Pagination + brand filter
- ✅ `POST /stores/search` + nearby stores tab
- ✅ Multi-agent sprint: `api/prompts.py`, `api/routes/chat.py`, `ChatInterface.tsx`, 6 tests
- ✅ `voucher_network` column (migration 0004)
- ✅ **UI Sprint** — single chat screen, suggestion chips, inline GPS, compact cards, PWA meta
- ✅ **Infrastructure Sprint** — Redis cache, Celery scheduler (5 tasks), price_changes table, Docker, admin health endpoint
- ✅ **User Accounts Sprint** — JWT auth, user tables (migration 0006), preferences, inference engine, ProfileDrawer
- ✅ **Data Quality Sprint** — image_url column (0007), dedup flag (0008), brand fix (312 products), Google Maps geocoder, min_price filter, availability filter, ResultCard images + "מחיר לא זמין"
- ✅ **Production Deployment Sprint (infra)** — Docker hardening, health latency monitoring, CI smoke test, S3 OAC security, bug fixes (see below)

**Bug fixes shipped 2026-05-02:**
- Fixed circular import: `limiter` moved from `api/main.py` → `api/dependencies.py`
- Fixed SlowAPI + `from __future__ import annotations` incompatibility: removed per-route `@limiter.limit()` decorators (global 200/min via SlowAPIMiddleware applies)
- Fixed `chat.py` parameter naming (`http_request`/`request` → `request`/`body`) to match SlowAPI convention
- Fixed S3 bucket policy JSON (`Statement` must be array not object)
- Fixed `admin.py` hardcoded version, bare `except:`, inline imports, removed `"uptime: N/A"` placeholder

**Sprint queue (do in this order):**
1. **Production Deployment (AWS)** — deploy to S3+CloudFront, EC2, SSL, domain ← NEXT
2. **Store Enrichment & Chain Support** — multi-category support, chain detection, LLM-based metadata, redemption details
3. **Remaining data tasks** — run geocoding (needs `GOOGLE_MAPS_API_KEY`), complete bulk deduplication, re-run scrapers for image URLs

---

## Active Sprint: Production Deployment ← NEXT

**Goal:** Deploy FindMe publicly. Frontend to S3+CloudFront, backend to EC2/ECS, SSL, domain, monitoring.

### Task List

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Containerize backend with Dockerfile + docker-compose | `Dockerfile`, `docker-compose.yml` | ✅ Done |
| 2 | Deploy frontend to AWS S3 + CloudFront | `frontend/`, AWS | TODO |
| 3 | Deploy FastAPI to EC2 or ECS (Docker) | `Dockerfile`, AWS | TODO |
| 4 | SSL certificate + custom domain | AWS ACM, Route53 | TODO |
| 5 | Rate limiting on `/search` and `/api/chat` | `api/main.py` | ✅ Done |
| 6 | Basic uptime monitoring | External (UptimeRobot / AWS CloudWatch) | TODO |

**Also pending (no sprint blocker):**
- Add `GOOGLE_MAPS_API_KEY` to `.env` → run `python -m db.run_geocoding` (geocodes 500 physical stores)
- Run `python -m normalization.deduplication` (merges duplicate products across stores) — **Initial run: 10 merges confirmed.**
- Scrape `image_url` into `store_products` — **Updated scrapers, 1,743 images populated for Femina.**

## Upcoming Sprint: Store Enrichment & Chain Support
**Goal:** Improve store-level search and geographic grouping by understanding chains and multi-category contexts.

### Task List
| # | Task | File | Status |
|---|------|------|--------|
| 1 | DB Migration: Add `parent_chain_id`, `buyme_categories` (JSONB), `metadata_json` (JSONB) | `db/models.py` | TODO |
| 2 | Update `buyme_store_scraper.py` to save full category list and redemption links | `scraper/buyme_store_scraper.py` | TODO |
| 3 | LLM Enrichment Script: Identify chains and extract "meta" from slogans/terms | `scraper/enrich_stores.py` | TODO |
| 4 | Geo-search update: Group results by chain for better map/list UX | `api/routes/stores.py` | TODO |

## Completed Sprint: Data Quality ✅

---

## Completed Sprint: LLM-Powered Conversational Search ✅

> All tasks done as of 2026-04-02. Kept here for reference only.

**What was built:** `POST /api/chat` with Gemini intent parser, response composer,
`ChatInterface.tsx` (WhatsApp-style), `api/prompts.py`, `api/schemas.py` additions,
`voucher_network` migration, 6 passing tests.

**Post-sprint bugs fixed:** gemini-2.5-flash model, JSON truncation fix, city-filter fallback.

All 5 integration test queries passed. See STATUS.md for details.

---

---

## Architecture: How the LLM Layer Works

```
User types message (Hebrew/English, free text)
         │
         ▼
POST /api/chat   ← new unified endpoint
         │
         ▼
┌─────────────────────────────────────────────────┐
│  Intent Parser (Gemini)                          │
│  Input: user message + conversation history      │
│  Output: ParsedIntent (structured Pydantic)      │
│    - intent: "product_search" | "store_search"   │
│              | "help" | "clarify"                │
│    - product_query: str | None                   │
│    - brand: str | None                           │
│    - max_price: float | None                     │
│    - city: str | None                            │
│    - location_hint: str | None  (place name)     │
│    - needs_user_location: bool                   │
│    - store_type: "restaurant"|"retail"|None      │
│    - voucher_network: "buyme" (default)          │
└─────────────────────────────────────────────────┘
         │
         ├── intent == "product_search" ──► call existing POST /search logic
         ├── intent == "store_search"   ──► call existing POST /stores/search logic
         ├── intent == "clarify"        ──► return clarifying question to user
         └── intent == "help"           ──► return canned help text
         │
         ▼
┌─────────────────────────────────────────────────┐
│  Response Composer (Gemini)                      │
│  Input: ParsedIntent + search results            │
│  Output: natural language answer in Hebrew       │
│    + structured results list                     │
└─────────────────────────────────────────────────┘
         │
         ▼
ChatResponse {
  message: str          ← Hebrew natural language answer
  results: list[...]    ← structured product or store results
  needs_location: bool  ← frontend should prompt for GPS if true
  intent: str           ← for frontend to choose display mode
  voucher_network: str  ← "buyme" (future: "tav_hazahav", etc.)
}
```


---

## Files Created in LLM Chat Sprint ✅

> All done. Listed for reference only — do not rebuild.

- `api/prompts.py` — intent parser + response composer prompts
- `api/routes/chat.py` — `POST /api/chat` with intent parsing + search dispatch
- `api/schemas.py` — added `ChatMessage`, `SessionContext`, `ParsedIntent`, `ChatRequest`, `ChatResponse`
- `frontend/src/components/ChatInterface.tsx` — WhatsApp-style chat UI
- `tests/api/test_chat.py` — 6 passing tests
- `db/migrations/versions/0004_voucher_network.py` — `voucher_network` column on stores

**No user accounts in this sprint.** Location and session context are handled in two ways:

### 1. Session context (passed by frontend, never stored in DB)
The frontend keeps a `sessionContext` object in React state.
Once the user shares GPS or types a location, it's stored there and
sent with every subsequent message automatically.

```typescript
// Frontend React state — persists for the tab session only
interface SessionContext {
  user_lat: number | null
  user_lng: number | null
  location_label: string | null   // e.g. "תל אביב מרכז"
  voucher_network: string          // "buyme" for now
}
```

When the backend returns `needs_location: true`, the frontend shows
a GPS button inline in the chat bubble. The user taps once →
`sessionContext` is updated → all future messages include coordinates.
**No login required. No DB write.**

### 2. Conversational context (resolved by LLM from history)
References like "שם", "אותו מקום", "המלון הזה" are resolved by
passing the full `history` array to the intent parser.
Gemini reads previous turns and extracts the referenced location.
This is already in the design — `history: list[ChatMessage]`.

### What "באזור שלי" means in practice
| User says | Resolution |
|-----------|-----------|
| "לידי" / "באזור שלי" | `needs_location=true` → frontend prompts GPS |
| "באילת" / "בתל אביב" | city extracted directly from message |
| "ליד המלון הזה" + URL in history | Gemini extracts location from history |
| GPS already in sessionContext | Pass coordinates automatically, no prompt |

### Future: user accounts (not this sprint)
Full design is documented below in the "Future: User Accounts" section.
**Do not build this now.** Build it after the chat interface is live and
you have real returning users.

---

### New: `api/routes/chat.py`
The main new file. A single `POST /api/chat` endpoint.

```python
# Request
class ChatRequest(BaseModel):
    message: str                        # user's free-text input
    history: list[ChatMessage] = []     # previous turns for context
    session_context: SessionContext | None = None  # location + voucher, from frontend state
    voucher_network: str = "buyme"      # future: "tav_hazahav", "nofshonit"

class SessionContext(BaseModel):
    user_lat: float | None = None       # GPS coordinates if already acquired
    user_lng: float | None = None
    location_label: str | None = None  # human-readable label, e.g. "תל אביב מרכז"

# Response
class ChatResponse(BaseModel):
    message: str                        # Hebrew natural language answer
    intent: str                         # "product_search" | "store_search" | "help" | "clarify"
    product_results: list[ProductResult] | None = None
    store_results: list[StoreResult] | None = None
    needs_location: bool = False        # true → frontend should ask for GPS
    location_prompt: str | None = None  # e.g. "באיזה אזור אתה נמצא?"
    voucher_network: str = "buyme"
    search_time_ms: float = 0
```

**Implementation steps inside `POST /api/chat`:**

1. Call `_parse_intent(message, history, gemini_client)` → returns `ParsedIntent`
2. If `intent == "clarify"` or `needs_user_location` and no GPS provided → return clarifying question immediately
3. If `intent == "product_search"` → call the existing search logic from `search.py` (import and reuse `_embed`, the SQL, and filter logic — do NOT duplicate)
4. If `intent == "store_search"` → call the existing store search logic from `stores.py`
5. Call `_compose_response(intent, results, parsed, gemini_client)` → Hebrew answer string
6. Return `ChatResponse`

### New: `api/prompts.py`
All LLM prompt templates live here. Never inline prompt strings in route handlers.

```python
INTENT_PARSER_SYSTEM = """
אתה עוזר חכם שמסייע למשתמשים למצוא היכן לנצל את כרטיסי המתנה שלהם.
כרגע אתה עובד עם רשת BuyMe בלבד.

המשימה שלך: קרא את הודעת המשתמש והחזר JSON מובנה בלבד (ללא טקסט נוסף).

פורמט הפלט:
{
  "intent": "product_search" | "store_search" | "help" | "clarify",
  "product_query": "<שם מוצר באנגלית או עברית, או null>",
  "brand": "<מותג, או null>",
  "max_price": <מספר בשקלים, או null>,
  "city": "<עיר בעברית, או null>",
  "location_hint": "<שם מקום / כתובת שהוזכרה, או null>",
  "needs_user_location": <true אם המשתמש אמר 'ליד', 'לידי', 'באזור שלי'>,
  "store_type": "restaurant" | "retail" | null,
  "voucher_network": "buyme"
}

כללים:
- אם המשתמש מחפש מסעדה/אוכל/לאכול → intent=store_search, store_type=restaurant
- אם המשתמש מחפש מוצר ספציפי → intent=product_search
- אם חסר מידע קריטי (למשל: ציין "לידי" אבל אין מיקום) → intent=clarify
- city: רק עיר מפורשת (תל אביב, אילת וכו׳), לא "ליד" או "באזור"
- needs_user_location: true כאשר המשתמש אמר "ליד", "לידי", "באזור שלי", "קרוב אלי"
"""

RESPONSE_COMPOSER_SYSTEM = """
אתה עוזר שמציג תוצאות חיפוש בכרטיסי מתנה BuyMe.
כתוב תשובה קצרה וידידותית בעברית (2-3 משפטים).
אל תמציא מידע — השתמש רק בנתונים שסופקו לך.
אם אין תוצאות, הצע חיפוש אחר.
"""
```

### Edit: `api/main.py`
Add: `app.include_router(chat_router, prefix="/api")`

### Edit: `api/schemas.py`
Add `ChatMessage`, `ChatRequest`, `ChatResponse` models.

### New: `frontend/src/components/ChatInterface.tsx`
**Replace the entire two-tab layout entirely.** The chat IS the app.
There are no tabs. There is no separate product search or store search UI.
The LLM understands all query types — tabs are redundant.

- Full-screen chat layout (no header tabs, no filter bars)
- Single RTL text input fixed at bottom (like WhatsApp)
- User messages: right-aligned blue bubbles
- Assistant messages: left-aligned white bubbles
- When `needs_location=true` → GPS button inline inside the assistant bubble
- Results (product cards or store cards) render below the assistant bubble
- Map renders below cards when results have lat/lng
- Keep `ResultCard`, `StoreCard`, `StoreMap` — just render them inside bubbles
- Opening message on load (no user action needed):
  "שלום! אני FindMe 🔍 תגיד לי מה אתה מחפש ואני אמצא לך היכן להשתמש בכרטיס BuyMe שלך."

### Edit: `frontend/src/App.tsx`
**Delete the tab switcher and both existing search panels entirely.**
Replace all content with just `<ChatInterface sessionContext={sessionContext} onLocationUpdate={setSessionContext} />`.
The old product search and store search components (`SearchBox`, `FilterBar`, etc.)
are no longer rendered — they can stay in the codebase but are not used.

### Edit: `frontend/src/api.ts`
Add:
```typescript
export async function sendChatMessage(
  message: string,
  history: ChatMessage[],
  userLat?: number,
  userLng?: number,
  voucherNetwork: string = 'buyme'
): Promise<ChatResponse>
```


---

## Voucher Network Abstraction (Future-Proofing)

Design the system so adding תו הזהב, נופשונית, etc. requires only:
1. A new row in a `voucher_networks` table (name, scrape_url, logo_url, color)
2. A new scraper for that network's store list
3. Stores table already has a `voucher_network` column (add it in this sprint)

**Do NOT hardcode "buyme" anywhere in business logic.** Always pass `voucher_network`
as a parameter through the call chain. Default is "buyme" for now.

**DB migration needed this sprint:**
```sql
ALTER TABLE stores ADD COLUMN voucher_network VARCHAR(50) DEFAULT 'buyme' NOT NULL;
CREATE INDEX idx_stores_voucher_network ON stores(voucher_network);
```

All existing stores get `voucher_network = 'buyme'` via the migration default.

---

## What Already Exists — Do Not Rewrite

### `api/routes/search.py` — `POST /search`
Full hybrid search: Gemini embedding + pgvector cosine + ILIKE fallback.
Handles URL extraction, pagination, all filters.
**Reuse this logic from `chat.py` — import `_embed`, `_vec_literal`, the SQL strings.**

### `api/routes/stores.py` — `POST /stores/search`
Geo-filtered store search with haversine distance, product count, pagination.
**Reuse this logic from `chat.py` — import the store query builder.**

### `db/models.py` — ORM models
`Store`, `Product`, `StoreProduct`, `ScrapeRun` — do not change column names.

### `frontend/src/components/`
`ResultCard.tsx`, `StoreCard.tsx`, `StoreMap.tsx`, `FilterBar.tsx` — keep all of these.
`ChatInterface.tsx` uses them; it does not replace them.

### `db/embed_products.py`
Background embedding script — not touched in this sprint.

---

## Coding Rules (Follow Exactly)

- **Always async/await** in FastAPI routes and DB operations
- **Gemini for LLM calls** — use the existing `AsyncOpenAI` client pointed at Gemini
  (`base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"`)
- **All LLM prompts in `api/prompts.py`** — never inline in route handlers
- **Parse Gemini JSON output safely** — strip ```json fences, use `json.loads()` in try/except
  Fallback: if JSON parse fails, return `intent=clarify`
- **Hebrew + English** — all response text to user must be in Hebrew
- **Type hints everywhere** — all new functions must have full annotations
- **Pydantic models for all new schemas** — in `api/schemas.py`
- **Never hardcode "buyme"** in business logic — always pass `voucher_network` parameter
- **Environment variables** — `GEMINI_API_KEY` already in `.env`; never hardcode
- **LLM token budgets:**
  - Intent parsing: max_tokens=256 (JSON output only)
  - Response composition: max_tokens=200 (short Hebrew answer)

---

## Task List — Do In Order

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Add `voucher_network` column migration | `db/migrations/` | TODO |
| 2 | Add `ChatMessage`, `ChatRequest`, `ChatResponse` to schemas | `api/schemas.py` | TODO |
| 3 | Create `api/prompts.py` with intent parser + response composer prompts | new file | TODO |
| 4 | Create `api/routes/chat.py` with `POST /api/chat` | new file | TODO |
| 5 | Register chat router in `api/main.py` | `api/main.py` | TODO |
| 6 | Create `frontend/src/components/ChatInterface.tsx` with inline GPS prompt | new file | TODO |
| 7 | Add `SessionContext` state to `App.tsx`, pass to all chat messages | `frontend/src/App.tsx` | TODO |
| 8 | Update `frontend/src/api.ts` with `sendChatMessage(message, history, sessionContext)` | `frontend/src/api.ts` | TODO |
| 9 | Update `frontend/src/App.tsx` to use `<ChatInterface />` | `frontend/src/App.tsx` | TODO |
| 9 | Test all 5 example query types end-to-end | manual | TODO |

**Run the backend after task 5. Run the full frontend after task 8.**
**Do NOT skip tasks or batch them — each task depends on the previous.**

---

## Environment

```bash
cd /Users/barakganon/personal_projects/FindMe
source .venv/bin/activate

# Backend
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm run dev

# Redis (needed for Celery + caching)
redis-server
redis-cli ping   # should return PONG

# Celery worker (scraper tasks)
celery -A scraper.scheduler worker --loglevel=info -Q scraper --concurrency=2

# Celery beat (scheduled jobs)
celery -A scraper.scheduler beat --loglevel=info

# DB
psql postgresql://barakganon@localhost/buyme_search

# Alembic migration
python -m alembic upgrade head

# Re-embed any unembedded products
python -m db.embed_products

# Re-run failed store scrapers
python -m scraper.sitemap_scraper
```

`.env` keys (current + needed for infrastructure sprint):
```
# Existing
GEMINI_API_KEY=
DATABASE_URL=postgresql+asyncpg://barakganon@localhost/buyme_search

# Add for infrastructure sprint
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
SEARCH_CACHE_TTL=300
INTENT_CACHE_TTL=120
EMBED_BATCH_SIZE=100
SHOPIFY_SCRAPE_CONCURRENCY=5

# Add for data quality sprint
GOOGLE_MAPS_API_KEY=
```

---

## What NOT To Do (All Sprints)

- Do not rewrite `search.py` or `stores.py` — import and reuse their logic
- Do not hardcode "buyme" in business logic — always pass `voucher_network` parameter
- Do not inline LLM prompts outside `api/prompts.py`
- Do not parse Gemini output without a try/except fallback
- Do not add new dependencies without updating `requirements.txt`
- Do NOT keep the existing two-tab UI — replace entirely with ChatInterface
- Do not change the search algorithm — 99.3% coverage, it works
- Do not add a message queue other than Redis/Celery — already chosen
- Do not use APScheduler or cron directly — Celery Beat is already set up
- Do not cache chat conversation history in Redis — keep it in frontend state
- Do not run Celery with more than 2 workers locally — Playwright is memory-heavy
- Do not add monitoring/APM (Prometheus, Grafana) — that's deployment infra, not now
- All user-facing text must be in Hebrew

---

## Future Sprint: User Accounts + Preference-Based Search

> **Do not implement this sprint yet.** Complete UI + Infrastructure + Data Quality sprints first.
> Trigger: when you have real returning users.
> Full design below — Claude Code can implement directly from this document.

---

### Core Design Principle: Anonymous First, Registration as Upgrade

The app works fully without an account. Registration is never required.
Anonymous users get the full chat experience with GPS-based location.
Registered users get the same experience PLUS persistent memory and better search.

```
Anonymous user:
  - Full chat, full search
  - Location via GPS per session
  - History lives in frontend state only (lost on tab close)
  - No personalization

Registered user (same UI, enhanced behavior):
  - Saved home/work locations → "לידי" resolves automatically
  - Search history persisted in DB → LLM can reference past searches
  - Explicit preferences → search results weighted accordingly
  - Implicit preferences → learned from behavior over time
  - Saved favorites → "הראה לי את המסעדות ששמרתי"
  - Voucher cards → "מה אפשר לקנות עם הכרטיס שלי"
```

The soft registration prompt appears in the chat after the 3rd search:
> "רוצה שאזכור את ההעדפות שלך לפעם הבאה? [צור חשבון חינם] [המשך בלי חשבון]"

If the user registers mid-session, their current session history and GPS location
are imported into their new account automatically.

---

### DB Schema

```sql
-- Core identity
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    display_name  VARCHAR(100),
    password_hash VARCHAR(255),       -- null for Google OAuth users
    google_id     VARCHAR(255) UNIQUE, -- null for email/password users
    created_at    TIMESTAMPTZ DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    is_active     BOOLEAN DEFAULT true
);

-- Saved named locations
CREATE TABLE user_locations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label      VARCHAR(100) NOT NULL,  -- "בית", "עבודה", "אמא", free text
    lat        DOUBLE PRECISION NOT NULL,
    lng        DOUBLE PRECISION NOT NULL,
    address    VARCHAR(255),
    is_default BOOLEAN DEFAULT false,  -- one default per user
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_user_locations_user ON user_locations(user_id);
CREATE UNIQUE INDEX idx_user_locations_default ON user_locations(user_id)
    WHERE is_default = true;  -- enforces only one default per user

-- Voucher cards the user holds
CREATE TABLE user_voucher_cards (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    voucher_network VARCHAR(50) NOT NULL,  -- "buyme", "tav_hazahav", "nofshonit"
    nickname        VARCHAR(100),          -- "כרטיס יום הולדת מאמא"
    balance         NUMERIC(10,2),         -- optional, user-entered
    expiry_date     DATE,
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_user_vouchers_user ON user_voucher_cards(user_id);

-- Explicit user preferences (set consciously in profile)
CREATE TABLE user_preferences (
    user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key       VARCHAR(100) NOT NULL,
    value     TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, key)
);
-- Supported preference keys and their effect on search:
-- "default_max_price"      → auto-apply max_price filter (value: "300")
-- "preferred_cities"       → boost results from these cities (value: '["תל אביב","רמת גן"]')
-- "preferred_categories"   → boost these category paths (value: '["Fashion","Electronics"]')
-- "show_online_only"       → default online_only filter (value: "true"/"false")
-- "default_radius_km"      → default location radius (value: "5")
-- "language"               → "he" or "en" (future multilingual support)

-- Implicit preferences (learned from behavior, written by backend)
CREATE TABLE user_implicit_signals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signal_type VARCHAR(50) NOT NULL,
    -- signal types:
    -- "city_search"    → user searched in this city
    -- "category_click" → user clicked a result in this category
    -- "store_visit"    → user clicked through to this store
    -- "price_range"    → user searched with this price range
    signal_value VARCHAR(255) NOT NULL,
    weight      FLOAT DEFAULT 1.0,     -- increases with repetition
    last_seen   TIMESTAMPTZ DEFAULT now(),
    count       INTEGER DEFAULT 1
);
CREATE UNIQUE INDEX idx_implicit_user_type_val
    ON user_implicit_signals(user_id, signal_type, signal_value);
-- On conflict: UPDATE weight = weight + 0.1, count = count + 1, last_seen = now()

-- LLM-inferred user attributes (transparent, user-visible, user-deletable)
-- The LLM extracts these passively from conversation and search patterns.
-- PRIVACY RULES:
--   1. Users can view all inferred attributes via GET /api/users/me/inferred
--   2. Users can delete any attribute via DELETE /api/users/me/inferred/{id}
--   3. Attributes are used to ENRICH search (boost relevant results)
--      never to RESTRICT search (never hide results based on inferred gender/age)
--   4. Confidence < 0.5 attributes are never used for search — stored for transparency only
--   5. Must be disclosed in privacy policy
CREATE TABLE user_inferred_attributes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    attribute   VARCHAR(100) NOT NULL,
    value       VARCHAR(255) NOT NULL,
    confidence  FLOAT NOT NULL DEFAULT 0.5,   -- 0.0 to 1.0
    source      TEXT,                          -- what message/behavior triggered this
    inferred_at TIMESTAMPTZ DEFAULT now(),
    last_updated TIMESTAMPTZ DEFAULT now(),
    is_confirmed BOOLEAN DEFAULT false         -- true if user explicitly confirmed it
);
CREATE INDEX idx_inferred_user ON user_inferred_attributes(user_id);
CREATE UNIQUE INDEX idx_inferred_user_attr ON user_inferred_attributes(user_id, attribute);
-- On conflict (same user + attribute): UPDATE value, confidence, source, last_updated

-- Supported inferred attributes and how they improve search:
-- "age_range"        → "25-35", "35-50" — boost age-appropriate products
-- "has_children"     → "yes" — surface baby/kids stores when relevant
-- "child_age_range"  → "0-3", "3-10" — refine kids product results
-- "gender"           → "female", "male", "unknown" — inform category defaults
-- "lifestyle"        → "sporty", "homebody", "fashionable", "tech-enthusiast"
-- "price_sensitivity"→ "budget", "mid-range", "premium" — inform default price range
-- "occasions"        → '["birthdays","holidays","work"]' — context for gift queries
-- "interests"        → '["wine","art","cooking","gaming"]' — boost relevant categories

-- Full search history
CREATE TABLE user_search_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message         TEXT NOT NULL,      -- original user message
    intent          VARCHAR(50),        -- "product_search" | "store_search"
    resolved_query  TEXT,               -- what the LLM extracted
    city_used       VARCHAR(100),       -- city that was searched
    result_count    INTEGER,
    top_result_name TEXT,               -- first result shown (for "last time you searched...")
    voucher_network VARCHAR(50) DEFAULT 'buyme',
    searched_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_search_history_user ON user_search_history(user_id, searched_at DESC);

-- Saved favorite stores
CREATE TABLE user_favorite_stores (
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    store_id   UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    saved_at   TIMESTAMPTZ DEFAULT now(),
    note       VARCHAR(255),
    PRIMARY KEY (user_id, store_id)
);
```

---

### How Preferences Improve Search Results

This is the critical part. Preferences don't just filter — they improve what the LLM
understands about the user and how the search is weighted.

#### 1. Injected into the intent parser prompt

When a registered user sends a message, their preferences are summarized and appended
to the `INTENT_PARSER_SYSTEM` prompt:

```python
def build_user_context_block(prefs: dict, implicit: list, history: list) -> str:
    """Build a Hebrew context block injected into the intent parser."""
    lines = ["--- הקשר אישי של המשתמש ---"]

    if prefs.get("default_max_price"):
        lines.append(f"תקציב רגיל: עד ₪{prefs['default_max_price']}")

    if prefs.get("preferred_cities"):
        cities = json.loads(prefs["preferred_cities"])
        lines.append(f"ערים מועדפות: {', '.join(cities)}")

    if prefs.get("preferred_categories"):
        cats = json.loads(prefs["preferred_categories"])
        lines.append(f"קטגוריות מועדפות: {', '.join(cats)}")

    # Top implicit signals
    top_cities = [s for s in implicit if s["type"] == "city_search"][:3]
    if top_cities:
        lines.append(f"ערים שחיפש לאחרונה: {', '.join(s['value'] for s in top_cities)}")

    # Recent search context (last 3)
    if history:
        lines.append("חיפושים אחרונים:")
        for h in history[:3]:
            lines.append(f"  - {h['message']} ({h['searched_at'][:10]})")

    lines.append("--- סוף הקשר ---")
    return "\n".join(lines)
```

This block is added to the system prompt so Gemini can:
- Infer "לידי" means their preferred city even without GPS
- Default to their usual budget when none is stated
- Suggest alternatives from their preferred categories when no results found
- Reference their recent searches: "כמו שחיפשת בפעם שעברה, אוזניות סוני..."

#### 2. LLM Attribute Inference (passive, runs after every chat turn)

After every search, a lightweight background call to Gemini scans the message
and updates inferred attributes. This is separate from the main chat call —
it runs async, never delays the response.

```python
# api/inference.py — new file
ATTRIBUTE_EXTRACTOR_SYSTEM = """
אתה מנתח שיחה ומחלץ מידע דמוגרפי ועדפות מהודעות המשתמש.
החזר JSON בלבד. אם אין מספיק מידע לשדה מסוים, החזר null.
אל תנחש — רק מה שמפורש או מרומז בבירור בהודעה.

פורמט הפלט:
{
  "age_range": "25-35" | "35-50" | "50+" | null,
  "has_children": true | false | null,
  "child_age_range": "0-3" | "3-10" | "10-18" | null,
  "gender": "female" | "male" | null,
  "lifestyle": ["sporty","fashionable","tech-enthusiast","homebody"] | [],
  "price_sensitivity": "budget" | "mid-range" | "premium" | null,
  "occasions": ["birthday","holiday","work","wedding"] | [],
  "interests": ["wine","art","cooking","gaming","fitness"] | [],
  "confidence_notes": "<brief explanation of what triggered each inference>"
}

דוגמאות:
- "קניתי מתנה לבן 3 שלי" → has_children=true, child_age_range="0-3"
- "אני מחפשת שמלה לחתונה" → gender=female, occasions=["wedding"]
- "GPU חדש לגיימינג" → lifestyle=["tech-enthusiast"], interests=["gaming"]
- "יין טוב לא יקר מדי" → interests=["wine"], price_sensitivity="mid-range"
"""

async def extract_and_update_attributes(
    user_id: UUID,
    message: str,
    db: AsyncSession,
    ai: AsyncOpenAI
) -> None:
    """
    Run after every chat turn for logged-in users.
    Extracts inferred attributes and upserts into user_inferred_attributes.
    Low confidence (<0.5) results are stored but never used for search.
    Never blocks the main chat response — call with asyncio.create_task().
    """
    try:
        response = await ai.chat.completions.create(
            model="gemini-2.5-flash",
            max_tokens=300,
            messages=[
                {"role": "system", "content": ATTRIBUTE_EXTRACTOR_SYSTEM},
                {"role": "user", "content": message}
            ]
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw.strip("```json").strip("```"))

        # Map extracted fields to attribute rows
        attribute_map = {
            "age_range": data.get("age_range"),
            "has_children": str(data.get("has_children")) if data.get("has_children") is not None else None,
            "child_age_range": data.get("child_age_range"),
            "gender": data.get("gender"),
            "price_sensitivity": data.get("price_sensitivity"),
        }
        list_map = {
            "lifestyle": data.get("lifestyle", []),
            "occasions": data.get("occasions", []),
            "interests": data.get("interests", []),
        }

        for attr, value in attribute_map.items():
            if value:
                await upsert_inferred_attribute(db, user_id, attr, value,
                    confidence=0.7, source=message[:200])

        for attr, values in list_map.items():
            if values:
                await upsert_inferred_attribute(db, user_id, attr,
                    json.dumps(values, ensure_ascii=False),
                    confidence=0.65, source=message[:200])

    except Exception:
        pass  # inference failure never affects the user experience
```

**How inferences improve search (boost, never restrict):**
```python
def apply_inferred_attributes(
    parsed: ParsedIntent,
    inferred: list[dict]
) -> ParsedIntent:
    """
    Use inferred attributes to enrich search intent.
    NEVER filters out results — only boosts relevance signals.
    Only applies attributes with confidence >= 0.5.
    """
    high_conf = {a["attribute"]: a["value"]
                 for a in inferred if a["confidence"] >= 0.5}

    # Price sensitivity → suggest default budget only if none stated
    if parsed.max_price is None:
        if high_conf.get("price_sensitivity") == "budget":
            parsed.search_hint = "budget-friendly"  # passed to response composer
        elif high_conf.get("price_sensitivity") == "premium":
            parsed.search_hint = "premium"

    # Interests → enrich product query with relevant terms
    interests = json.loads(high_conf.get("interests", "[]"))
    if interests and parsed.product_query:
        # Don't modify the query — pass as a hint to the response composer
        parsed.user_interests_hint = interests

    return parsed
```

**User transparency — profile screen shows all inferred data:**
```
GET /api/users/me/inferred
→ [
    { "id": "...", "attribute": "gender", "value": "female",
      "confidence": 0.7, "source": "אני מחפשת שמלה", "inferred_at": "..." },
    { "id": "...", "attribute": "has_children", "value": "true",
      "confidence": 0.85, "source": "מתנה לבן 3 שלי", "inferred_at": "..." }
  ]

DELETE /api/users/me/inferred/{id}   → remove single attribute
DELETE /api/users/me/inferred         → clear all inferred attributes

PUT /api/users/me/inferred/{id}/confirm → user explicitly confirms it's correct
                                          (sets is_confirmed=true, confidence=1.0)
```

In the profile drawer, show a section: **"מה FindMe יודע עליך"**
List inferred attributes in plain Hebrew with confidence as a bar:
```
👦 יש לך ילד קטן (0-3)   ████░ גבוה
👗 קניות נשים            ███░░ בינוני    [✓ אשר] [✗ מחק]
💰 תקציב בינוני          ██░░░ נמוך      [✓ אשר] [✗ מחק]
```
Low-confidence items are shown but grayed out with a note:
"לא בטוח — לא משפיע על חיפושים עד שתאשר"

After intent parsing, preferences are merged with the parsed intent:

```python
def merge_preferences_into_search(
    parsed: ParsedIntent,
    prefs: dict,
    implicit: list
) -> ParsedIntent:
    """Apply user preferences to parsed intent before running search."""

    # Budget: use parsed max_price if stated, otherwise fall back to preference
    if parsed.max_price is None and prefs.get("default_max_price"):
        parsed.max_price = float(prefs["default_max_price"])

    # City: use parsed city if stated, otherwise check preferred cities
    if parsed.city is None and not parsed.needs_user_location:
        preferred_cities = json.loads(prefs.get("preferred_cities", "[]"))
        if preferred_cities:
            parsed.city = preferred_cities[0]  # use top preferred city as default

    # Online only: apply preference if not explicitly stated in message
    if prefs.get("show_online_only") == "true":
        parsed.online_only = True

    return parsed
```

#### 3. Response composer knows about history

The response composer receives a summary of the user's history so it can
personalize the answer:

```
"מצאתי 8 מסעדות בתל אביב. הפעם האחרונה שחיפשת מסעדות מצאת את 'קפה אוסישקין' —
אפשר לחפש שוב שם אם תרצה."
```

---

### Anonymous → Registered Upgrade Path

When an anonymous user registers mid-session:

```
Frontend:
1. User clicks "צור חשבון" soft prompt
2. Show inline registration form (name + email + password) — no page navigation
3. On success: receive JWT
4. POST /api/auth/import-session with { token, session_history, session_context }
5. Backend creates user, imports session_history into user_search_history,
   saves session GPS as default location if user confirms

Backend POST /api/auth/import-session:
1. Verify JWT → get user_id
2. Insert session_history rows into user_search_history
3. If session GPS provided + user says "save as home":
   INSERT into user_locations (label="בית", lat=..., lng=..., is_default=true)
4. Return updated user profile
```

This means the user doesn't lose anything by waiting to register.

---

### Auth Strategy

**JWT, stateless.** Works perfectly with FastAPI's `Depends()` pattern.

```
POST /api/auth/register    → email + password → create user → return JWT
POST /api/auth/login       → email + password → return JWT
POST /api/auth/google      → Google OAuth token → find/create user → return JWT
GET  /api/auth/me          → validate JWT → return user profile
POST /api/auth/import-session → JWT + session data → import anonymous history
POST /api/auth/logout      → client-side only (discard JWT from localStorage)
```

JWT payload: `{ user_id, email, exp }`. Sign with `JWT_SECRET` env var.
Token lifetime: 30 days. No refresh token needed for this use case.

**Anonymous request detection:**
```python
async def get_optional_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)
) -> User | None:
    """Returns User if valid JWT present, None for anonymous requests.
    Use this instead of get_current_user() for endpoints that work for both."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await _decode_and_fetch_user(authorization[7:], db)
    except Exception:
        return None
```

Use `get_optional_user` (not `get_current_user`) on `POST /api/chat` so anonymous
users are never blocked.

---

### Updated ChatRequest with Optional Auth

```python
class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    session_context: SessionContext | None = None
    voucher_network: str = "buyme"
    # user_id is set by backend from JWT — never sent by client directly
```

In `POST /api/chat` handler:
```python
@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    ai: AsyncOpenAI = Depends(get_ai_client),
    current_user: User | None = Depends(get_optional_user),  # None = anonymous
) -> ChatResponse:

    # Build user context block if logged in
    user_context = ""
    if current_user:
        prefs = await load_user_preferences(db, current_user.id)
        implicit = await load_implicit_signals(db, current_user.id)
        history = await load_recent_history(db, current_user.id, limit=3)
        user_context = build_user_context_block(prefs, implicit, history)

    # Parse intent (with or without user context)
    parsed = await _parse_intent(request.message, request.history, ai, user_context)

    # Merge preferences if logged in
    if current_user and prefs:
        parsed = merge_preferences_into_search(parsed, prefs, implicit)

    # ... rest of search flow unchanged ...

    # Save to history if logged in
    if current_user:
        await save_search_history(db, current_user.id, request.message, parsed, results)
        await update_implicit_signals(db, current_user.id, parsed)
```

---

### User Profile API

```
GET    /api/users/me                        → profile + active vouchers + default location
PUT    /api/users/me                        → update display_name

GET    /api/users/me/locations              → list saved locations
POST   /api/users/me/locations              → add { label, lat, lng, address, is_default }
PUT    /api/users/me/locations/{id}         → update / set as default
DELETE /api/users/me/locations/{id}         → remove

GET    /api/users/me/vouchers               → list voucher cards
POST   /api/users/me/vouchers               → add { voucher_network, nickname, balance, expiry }
PUT    /api/users/me/vouchers/{id}          → update balance / nickname
DELETE /api/users/me/vouchers/{id}          → remove

GET    /api/users/me/preferences            → all preferences as key/value dict
PUT    /api/users/me/preferences            → bulk update { key: value, ... }
DELETE /api/users/me/preferences/{key}      → reset one preference to default

GET    /api/users/me/favorites              → list favorite stores with notes
POST   /api/users/me/favorites              → { store_id, note }
DELETE /api/users/me/favorites/{store_id}   → remove

GET    /api/users/me/history?limit=20       → recent searches
DELETE /api/users/me/history                → clear all history
```

---

### Frontend — Auth UX

**No separate login page.** Auth is always inline — never navigates away from the chat.

**Registration flow:**
1. After 3rd search, soft prompt appears as assistant bubble:
   "רוצה שאזכור את ההעדפות שלך לפעם הבאה? 📝"
   Buttons: [צור חשבון] [המשך בלי חשבון]
2. Clicking "צור חשבון" expands an inline form inside the bubble:
   - שם (optional), אימייל, סיסמה, [כניסה עם Google]
3. On success: JWT stored in localStorage, user greeted by name, session imported

**Profile access:**
- Small avatar / initials circle in the header top-left (anonymous = gray circle)
- Clicking opens a side drawer (not a new page):
  - My locations (edit/add/set default)
  - My voucher cards (add/edit)
  - Preferences (budget, preferred cities, categories, radius)
  - Search history (last 20, with "clear history" button)
  - Favorites
  - Logout

**Auth state in App.tsx:**
```typescript
interface AuthState {
  user: User | null
  token: string | null       // stored in localStorage
  isAuthenticated: boolean
}
```
Token stored in `localStorage`. On app load: validate with `GET /api/auth/me`.
On 401: clear token silently (don't redirect — anonymous mode takes over).

---

### New Dependencies for This Sprint

```
# requirements.txt additions:
python-jose[cryptography]==3.3.0   # JWT signing/verification
passlib[bcrypt]==1.7.4             # password hashing
authlib==1.3.0                     # Google OAuth
httpx                              # already present — for OAuth HTTP calls

# No new frontend deps needed — use fetch() for auth, no auth library
```

---

### Implementation Order

| # | Task | File | Notes |
|---|------|------|-------|
| 1 | Alembic migration 0006 — all 6 user tables | `db/migrations/0006_user_accounts.py` | Note: 0005 = price_changes |
| 2 | SQLAlchemy ORM models for user tables | `db/models.py` | |
| 3 | JWT auth utilities + `get_optional_user` dependency | `api/auth.py` | `get_optional_user` is critical — never block anonymous |
| 4 | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/import-session` | `api/routes/auth.py` | |
| 5 | Google OAuth route `POST /auth/google` | `api/routes/auth.py` | Requires `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` in `.env` |
| 6 | User preferences + locations + vouchers + favorites + history routes | `api/routes/users.py` | |
| 7 | `build_user_context_block()` + `merge_preferences_into_search()` + `apply_inferred_attributes()` in `api/chat_utils.py` | `api/chat_utils.py` | New file |
| 8 | Wire `get_optional_user` into `POST /api/chat` | `api/routes/chat.py` | Anonymous still works |
| 9 | Wire preference injection + history saving + inference extraction into chat handler | `api/routes/chat.py` | `asyncio.create_task()` for inference — never blocks response |
| 9b | Create `api/inference.py` with `extract_and_update_attributes()` | `api/inference.py` | New file — runs async after every turn |
| 10 | `GET/DELETE /api/users/me/inferred` endpoints | `api/routes/users.py` | Transparency endpoints — required |
| 11 | Frontend `AuthState` + localStorage token handling | `frontend/src/store/auth.ts` | |
| 12 | Inline soft registration prompt after 3rd search | `frontend/src/components/ChatInterface.tsx` | |
| 13 | Profile side drawer — includes "מה FindMe יודע עליך" inferred section | `frontend/src/components/ProfileDrawer.tsx` | Show confidence bars, confirm/delete buttons |
| 14 | Avatar/initials in header + drawer toggle | `frontend/src/components/ChatInterface.tsx` | |
| 15 | Add auth header to API calls | `frontend/src/api.ts` | |
| 16 | Tests: auth routes + preference injection + inference extraction + anonymous fallback | `tests/api/test_auth.py`, `tests/api/test_inference.py` | Mock Gemini for inference tests |

---

## Multi-Agent Architecture

This project uses Claude Code multi-agent sessions for parallel development.
Each agent owns a specific folder and a specific concern. Agents must never
touch files outside their assigned domain without an explicit orchestrator instruction.

---

### Agent Roster

| Agent | Owns | Reads (but never edits) | Never touches |
|-------|------|--------------------------|---------------|
| **Orchestrator** | `CLAUDE.md`, `STATUS.md`, task coordination | Everything | Nothing — coordinates only |
| **API Agent** | `api/` | `db/models.py`, `api/schemas.py` | `scraper/`, `frontend/`, `normalization/` |
| **DB Agent** | `db/`, `alembic.ini`, migrations | `api/schemas.py` | `api/routes/`, `scraper/`, `frontend/` |
| **Scraper Agent** | `scraper/` | `db/models.py` | `api/`, `frontend/`, `normalization/` |
| **Normalization Agent** | `normalization/` | `db/models.py` | `scraper/`, `api/`, `frontend/` |
| **Frontend Agent** | `frontend/src/` | `api/schemas.py` (for types) | Everything else |
| **Test Agent** | `tests/` | All source files (read-only) | All source files |

**Coordination rule:** if an agent needs something from another domain
(e.g. API Agent needs a new DB column), it writes a comment in its own file:
`# NEEDS: DB Agent to add column X to table Y` and flags it to the orchestrator.
It does NOT reach into the other module itself.

---

### Sprint Task Split — LLM Conversational Search

These tasks can run in parallel once the shared schemas are agreed on.
The orchestrator defines schemas first, then spawns agents.

#### Phase 1 — Schemas first (Orchestrator, ~5 min, sequential)
The orchestrator writes `api/schemas.py` additions (`ChatMessage`, `SessionContext`,
`ChatRequest`, `ChatResponse`) and `api/prompts.py` before spawning any agents.
This gives all agents a stable contract to build against.

#### Phase 2 — Parallel (spawn all 4 agents simultaneously)

**Agent A — DB Agent**
```
Task: Add voucher_network column migration.
Files: db/migrations/versions/0002_voucher_network.py
Instructions:
  - Create Alembic migration that adds voucher_network VARCHAR(50)
    DEFAULT 'buyme' NOT NULL to the stores table
  - Add index: CREATE INDEX idx_stores_voucher_network ON stores(voucher_network)
  - Run: python -m alembic upgrade head
  - Confirm the column exists in the DB before marking done
  - Update STATUS.md with result
```

**Agent B — API Agent**
```
Task: Implement POST /api/chat endpoint.
Files: api/routes/chat.py, api/main.py
Instructions:
  - Read api/schemas.py and api/prompts.py (written by orchestrator) first
  - Read api/routes/search.py and api/routes/stores.py — import and REUSE
    _embed, _vec_literal, and the store query logic. Do NOT duplicate.
  - Implement _parse_intent(message, history, client) → ParsedIntent
  - Implement _compose_response(intent, results, parsed, client) → str
  - Implement POST /api/chat handler using the flow in CLAUDE.md
  - Register router in api/main.py
  - All LLM prompts must be imported from api/prompts.py — never inline
  - Wrap all Gemini JSON parsing in try/except, fallback to intent=clarify
  - Do NOT touch search.py or stores.py
```

**Agent C — Frontend Agent**
```
Task: Build ChatInterface component and wire it into App.tsx.
Files: frontend/src/components/ChatInterface.tsx,
       frontend/src/api.ts (add sendChatMessage),
       frontend/src/App.tsx (add SessionContext state, render ChatInterface)
Instructions:
  - Read api/schemas.py for TypeScript type shapes
  - Build ChatInterface.tsx:
      * Single RTL text input fixed at bottom (like WhatsApp)
      * User messages: right-aligned bubbles
      * Assistant messages: left-aligned bubbles
      * When response.needs_location=true: show GPS button inline
        in the assistant bubble, not as a separate screen
      * Results (ProductResult[] or StoreResult[]) render below
        the assistant bubble using existing ResultCard / StoreCard
      * Keep existing ResultCard, StoreCard, StoreMap — just use them
  - Add SessionContext to App.tsx React state
    (user_lat, user_lng, location_label, voucher_network)
  - Add sendChatMessage() to api.ts
  - Do NOT add ChatInterface as a third tab — replace the entire UI
  - Delete the tab switcher, SearchBox panel, and StoreSearch panel from App.tsx
  - All visible text must be in Hebrew
```

**Agent D — Test Agent**
```
Task: Write tests for POST /api/chat.
Files: tests/api/test_chat.py
Instructions:
  - Wait for Agent B to finish api/routes/chat.py before starting
  - Write pytest tests covering:
      1. Product search intent: "אוזניות סוני" → intent=product_search
      2. Store search intent: "מסעדות באילת" → intent=store_search
      3. Needs location: "מסעדות לידי" → needs_location=True in response
      4. Location in session_context: same query + lat/lng → returns results
      5. Help intent: "מה אפשר לקנות ב-BuyMe" → intent=help
      6. Clarify intent: malformed/empty message → intent=clarify
  - Mock Gemini API calls — do not make real LLM calls in tests
  - Tests must pass with: pytest tests/api/test_chat.py
```

#### Phase 3 — Integration (sequential, after all agents done)
Orchestrator runs both servers and manually tests the 5 example queries
from the task list. Marks STATUS.md complete.

---

### How to Spawn Agents in Claude Code

In Claude Code, use the `Task` tool to spawn subagents in parallel:

```
I need to implement the LLM conversational search sprint.
The schemas are already written in api/schemas.py and api/prompts.py.

Please spawn 3 parallel subagents:

Subagent 1 (DB Agent):
[paste Agent A instructions above]

Subagent 2 (API Agent):
[paste Agent B instructions above]

Subagent 3 (Frontend Agent):
[paste Agent C instructions above]

Run all 3 in parallel. Report back when all are done.
Then I will run Agent D (Test Agent) sequentially.
```

**Important:** Agent D (tests) must run after Agent B completes,
because it imports from `api/routes/chat.py`. Do not parallelize it
with Agent B.

---

### Agent Communication Protocol

Agents signal completion and blockers through `STATUS.md` only.
No agent edits another agent's files directly.

**STATUS.md format for agent updates:**
```markdown
## Agent Status — [date]

| Agent | Task | Status | Notes |
|-------|------|--------|-------|
| DB Agent | voucher_network migration | ✅ Done | Column added, index created |
| API Agent | POST /api/chat | 🔄 In progress | _parse_intent done, composing response |
| Frontend Agent | ChatInterface.tsx | ✅ Done | GPS prompt working |
| Test Agent | test_chat.py | ⏳ Waiting | Waiting for API Agent |
```

---

### Conflict Prevention Rules

These rules prevent agents from colliding on the same files:

1. **`api/schemas.py`** — written by orchestrator in Phase 1, then READ-ONLY for all agents
2. **`api/prompts.py`** — written by orchestrator in Phase 1, then READ-ONLY for all agents
3. **`api/main.py`** — only API Agent edits this (router registration)
4. **`db/models.py`** — only DB Agent edits this
5. **`requirements.txt`** — only orchestrator edits this after agents flag new deps
6. **`CLAUDE.md`** — only orchestrator edits this
7. **`STATUS.md`** — all agents append to this, never overwrite

If two agents need to edit the same file, the orchestrator serializes them:
finish Agent A on that file, then hand off to Agent B.


---

## UI Design Spec — ChatInterface (Active)

> The backend is complete. This section defines exactly how the frontend should look and behave.
> Claude Code should implement this from `START_PROMPT.md`.

### The one-screen layout

No tabs. The chat IS the app. `App.tsx` renders only `<ChatInterface />`.

```
┌─────────────────────────────────────────────┐
│  HEADER (fixed, 56px)                        │
│  🔍 FindMe  חיפוש חכם לכרטיסי BuyMe  [BuyMe✓]│
├─────────────────────────────────────────────┤
│                                              │
│  MESSAGES (flex-1, overflow-y scroll)        │
│  Welcome + suggestion chips (first load)     │
│  User bubble (right, blue)                   │
│  Assistant bubble (left, white)              │
│    └─ GPS button if needs_location           │
│    └─ Product/Store cards grid               │
│    └─ Map if coordinates available           │
│                                              │
├─────────────────────────────────────────────┤
│  INPUT BAR (fixed, 64px)                     │
│  [שאל אותי על BuyMe...        ] [↑ send]     │
└─────────────────────────────────────────────┘
```

### Colors (Tailwind)
- Primary: `blue-600` (#2563eb)
- User bubble: `bg-blue-600 text-white`
- Assistant bubble: `bg-white border-gray-100 shadow-sm`
- Background: `bg-gray-50`
- Header/input bar: `bg-white`
- Category badges: מסעדה=`bg-orange-50 text-orange-700`, חנות=`bg-blue-50 text-blue-700`, ספא=`bg-purple-50 text-purple-700`

### Typography
- System font stack: `-apple-system, 'Segoe UI', sans-serif`
- All Hebrew, RTL

### Suggestion chips (first load only)
Four pills below the welcome message. Clicking sends the message immediately.
Hide permanently once any message sent.
- "🍽️ מסעדות בתל אביב"
- "🎧 אוזניות סוני"
- "👗 חנויות אופנה לידי"
- "💄 ספא וטיפוח"

### GPS flow (inline, no modal)
When `needs_location=true`: blue pill button "📍 שתף מיקום" inside assistant bubble.
After GPS acquired: auto-resend the last message with coordinates → show results.

### Result cards (inside bubbles)
- Max 6 cards, "ועוד X" text link if more
- Horizontal scroll on mobile, 3-col grid ≥640px
- Product card: store name, product name (line-clamp-2), price (green or "מחיר לא זמין"), availability dot, "לרכישה →" link
- Store card: name, category badge, city + distance, product count, BuyMe link
- Map: StoreMap component, 220px height, rounded-xl, below cards


---

## Infrastructure Sprint: Redis + Scheduler + Data Freshness

> This is the next major sprint after the UI redesign is done.
> The backend is feature-complete. This sprint makes it production-ready.

---

### The Problem

The catalog is a snapshot from April 2026. Every day it gets more wrong:
- Prices change (stores run sales, restock, change pricing)
- Availability changes (products sell out or come back)
- New stores join BuyMe
- Old stores leave

Without a scheduler, FindMe is a museum, not a live search engine.
Without Redis, every search pays ~1s Gemini embedding cost even for "אוזניות" — a query that runs 100 times a day.

---

### Component 1: Redis — Three Uses

Redis is already in `requirements.txt` and configured in Celery.
It just needs to be running and wired into 3 places.

**Start Redis locally:**
```bash
brew install redis   # macOS
redis-server         # start
redis-cli ping       # should return PONG
```

**Use 1: Celery broker + result backend (already designed, just needs Redis running)**
```
CELERY_BROKER_URL=redis://localhost:6379/0
REDIS_URL=redis://localhost:6379/1        # separate DB for results
```

**Use 2: Search result cache (new)**
Cache `POST /search` responses by query hash for 5 minutes.
The Gemini embedding call (~1s) is the main bottleneck — caching eliminates it for repeated queries.

```python
# api/cache.py — new file
import hashlib, json
from redis.asyncio import Redis

async def get_search_cache(redis: Redis, query: str, filters: dict) -> dict | None:
    key = "search:" + hashlib.sha256((query + json.dumps(filters, sort_keys=True)).encode()).hexdigest()
    val = await redis.get(key)
    return json.loads(val) if val else None

async def set_search_cache(redis: Redis, query: str, filters: dict, result: dict, ttl: int = 300):
    key = "search:" + hashlib.sha256((query + json.dumps(filters, sort_keys=True)).encode()).hexdigest()
    await redis.setex(key, ttl, json.dumps(result))
```

Wire into `api/routes/search.py`: check cache before embedding, set cache after search.
Wire into `api/routes/chat.py`: same — cache parsed intents for 2 min, search results for 5 min.

**Use 3: Chat intent cache (new)**
Same user query = same intent. Cache `_parse_intent()` results for 2 minutes.
Key: `intent:{sha256(message)}`
Saves a full Gemini LLM call for repeated or similar messages.

**Redis connection in FastAPI:**
```python
# api/dependencies.py — add:
from redis.asyncio import Redis, from_url

_redis_client: Redis | None = None

async def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(settings.redis_url, decode_responses=True)
    return _redis_client
```

Add `REDIS_URL=redis://localhost:6379/0` to `.env` and `.env.example`.

---

### Component 2: Scheduler — 4 Tasks Wired to DB

The skeleton in `scraper/scheduler.py` has the right structure.
The TODOs need to be filled in. Here are the 4 real tasks:

#### Task A: `scrape_buyme_store_list` (daily, 02:00 IL)
Already defined. Needs to be wired to DB upsert.

```
Flow:
1. Run BuyMeStoreScraper → list of store dicts
2. For each store: upsert into stores table (match on buyme_url)
3. For new stores: set scrape_status='pending', enqueue scrape_store_products task
4. Write ScrapeRun audit row (type=STORE_LIST)
5. Log: N stores found, M new, K updated
```

#### Task B: `scrape_shopify_stores` (weekly, Sunday 03:00 IL)
Fast path — only for stores where scrape_status='success' (Shopify stores).

```
Flow:
1. Query DB: SELECT id, store_url FROM stores WHERE scrape_status='success'
2. For each store: run ShopifyProductScraper (/products.json)
3. For each product:
   - Upsert into products (match on canonical_name + brand)
   - Upsert into store_products (match on store_id + product_url)
   - If price changed: update last_price_change_at, write to price_changes table
4. Write ScrapeRun row per store
5. Enqueue embed_new_products for any new products without embeddings
```

#### Task C: `scrape_sitemap_stores` (bi-weekly, 1st+15th of month, 04:00 IL)
Slower path — for stores with sitemaps (scrape_status='done').

```
Flow: same as Task B but using SitemapScraper instead of ShopifyProductScraper
```

#### Task D: `embed_new_products` (daily, 05:00 IL)
Pick up any products added since last run that don't have embeddings.

```
Flow:
1. Query: SELECT id, canonical_name, brand FROM products WHERE embedding_vector IS NULL LIMIT 5000
2. Batch embed using Gemini (batch 100, respect rate limits)
3. Update embedding_vector for each product
4. Log: N products embedded
```

**Wiring pattern for all DB tasks:**
```python
@celery_app.task(...)
def scrape_shopify_stores(self) -> dict:
    import asyncio
    from db.session import get_sync_session  # new: sync session for Celery
    
    async def _run():
        # use asyncpg directly (faster than SQLAlchemy for bulk upserts)
        conn = await asyncpg.connect(os.getenv("DATABASE_URL").replace("+asyncpg", ""))
        try:
            stores = await conn.fetch("SELECT id, store_url FROM stores WHERE scrape_status='success'")
            for store in stores:
                products = await scrape_one_store(store["store_url"])
                await upsert_products(conn, store["id"], products)
        finally:
            await conn.close()
    
    asyncio.run(_run())
```

**Beat schedule additions to `scheduler.py`:**
```python
celery_app.conf.beat_schedule = {
    "scrape-buyme-store-list-daily": {
        "task": "scraper.scheduler.scrape_buyme_store_list",
        "schedule": crontab(hour=2, minute=0),
    },
    "scrape-shopify-stores-weekly": {
        "task": "scraper.scheduler.scrape_shopify_stores",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sunday
    },
    "scrape-sitemap-stores-biweekly": {
        "task": "scraper.scheduler.scrape_sitemap_stores",
        "schedule": crontab(hour=4, minute=0, day_of_month="1,15"),
    },
    "embed-new-products-daily": {
        "task": "scraper.scheduler.embed_new_products",
        "schedule": crontab(hour=5, minute=0),
    },
}
```

---

### Component 3: Price Changes Table (new DB table)

The `store_products` table has `last_price_change_at` but no history.
Add a `price_changes` table to track every price event:

```sql
CREATE TABLE price_changes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_product_id UUID NOT NULL REFERENCES store_products(id) ON DELETE CASCADE,
    old_price    NUMERIC(10,2),
    new_price    NUMERIC(10,2),
    old_availability BOOLEAN,
    new_availability BOOLEAN,
    detected_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_price_changes_store_product ON price_changes(store_product_id, detected_at DESC);
CREATE INDEX idx_price_changes_detected ON price_changes(detected_at DESC);
```

This enables:
- "This product dropped in price since last week" (future feature)
- Monitoring scrape freshness via the Admin Dashboard
- Alert when popular products go out of stock

Add Alembic migration: `db/migrations/versions/0005_price_changes.py`
Add SQLAlchemy model: `PriceChange` class in `db/models.py`

---

### Component 4: Admin Health API (new endpoint)

Right now the only way to check system health is `psql`. Add a proper endpoint:

```
GET /api/admin/health
```

Returns:
```json
{
  "database": "ok",
  "redis": "ok",
  "products_total": 135865,
  "products_embedded": 134963,
  "embedding_coverage_pct": 99.3,
  "stores_total": 1226,
  "stores_geocoded": 426,
  "last_shopify_scrape": "2026-04-02T03:00:00Z",
  "last_sitemap_scrape": "2026-04-02T04:00:00Z",
  "last_store_list_scrape": "2026-04-02T02:00:00Z",
  "celery_workers_active": 2,
  "recent_scrape_runs": [
    {"store": "CrypTech", "status": "success", "products": 7846, "finished_at": "..."},
    ...
  ]
}
```

Simple FastAPI route in `api/routes/admin.py`. No auth needed for now (internal only).
Query the DB directly — no LLM involved.

---

### Component 5: Docker Compose (dev environment)

Make it trivial to start the full stack:

```yaml
# docker-compose.yml (new file at project root)
version: "3.9"
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["redis_data:/data"]
    command: redis-server --appendonly yes

  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: buyme_search
      POSTGRES_USER: barakganon
      POSTGRES_PASSWORD: ""
    volumes: ["postgres_data:/var/lib/postgresql/data"]

  celery-worker:
    build: .
    command: celery -A scraper.scheduler worker --loglevel=info -Q scraper --concurrency=2
    env_file: .env
    depends_on: [redis, postgres]
    volumes: [".:/app"]

  celery-beat:
    build: .
    command: celery -A scraper.scheduler beat --loglevel=info
    env_file: .env
    depends_on: [redis, postgres]
    volumes: [".:/app"]

volumes:
  redis_data:
  postgres_data:
```

Also add `Dockerfile` for the Python services:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium --with-deps
COPY . .
```

---

### New `.env` variables needed

```bash
# Already exists
GEMINI_API_KEY=
DATABASE_URL=postgresql+asyncpg://barakganon@localhost/buyme_search

# Add these:
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Cache TTLs (seconds)
SEARCH_CACHE_TTL=300        # 5 min
INTENT_CACHE_TTL=120        # 2 min

# Scraper limits
EMBED_BATCH_SIZE=100
EMBED_DAILY_LIMIT=50000     # paid tier allows much more
SHOPIFY_SCRAPE_CONCURRENCY=5
```

---

### Infrastructure Sprint Task List

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 1 | Start Redis + add `REDIS_URL` to `.env` and `.env.example` | `.env`, `.env.example` | Trivial |
| 2 | Add `get_redis()` dependency to `api/dependencies.py` | `api/dependencies.py` | Small |
| 3 | Create `api/cache.py` with `get_search_cache` / `set_search_cache` | `api/cache.py` | Small |
| 4 | Wire cache into `api/routes/search.py` (check before embed, set after) | `api/routes/search.py` | Small |
| 5 | Wire intent cache into `api/routes/chat.py` (cache `_parse_intent` 2 min) | `api/routes/chat.py` | Small |
| 6 | Add `price_changes` table + Alembic migration 0005 | `db/models.py`, `db/migrations/versions/0005_price_changes.py` | Small |
| 7 | Fill in `scrape_shopify_stores` Celery task with real DB upsert | `scraper/scheduler.py` | Medium |
| 8 | Fill in `embed_new_products` Celery task (daily, picks up unembedded) | `scraper/scheduler.py` | Small |
| 9 | Fill in `detect_price_changes` task (diff prices, write to price_changes) | `scraper/scheduler.py` | Medium |
| 10 | Fill in `scrape_sitemap_stores` task with DB upsert | `scraper/scheduler.py` | Medium |
| 11 | Fill in `scrape_buyme_store_list` task with DB upsert + enqueue new stores | `scraper/scheduler.py` | Medium |
| 12 | Add `api/routes/admin.py` with `GET /api/admin/health` | `api/routes/admin.py`, `api/main.py` | Small |
| 13 | Create `docker-compose.yml` + `Dockerfile` | root | Small |
| 14 | Update `requirements.txt` — add `redis[asyncio]`, verify `celery` version | `requirements.txt` | Trivial |

**Run after task 5:** `redis-cli ping` → PONG, then `uvicorn api.main:app --reload` and confirm `/search` is faster on second call.
**Run after task 13:** `docker-compose up` → all services start cleanly.

---

## Data Quality Sprint Task List

> Do this sprint after Infrastructure Sprint is done.

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| 1 | Switch geocoding to Google Maps API for 500 remaining stores | `db/geocode_stores.py`, `.env` | Small | Add `GOOGLE_MAPS_API_KEY` to `.env`. Nominatim confirmed unable to handle Israeli mall/complex addresses. |
| 2 | Wire `normalization/deduplication.py` into post-scrape pipeline | `scraper/scheduler.py`, `normalization/deduplication.py` | Large | File exists but is never called. After each store scrape, run dedup to merge same-product rows across stores. Critical for "buy X everywhere" use case. |
| 3 | Display product images in `ResultCard.tsx` | `frontend/src/components/ResultCard.tsx` | Small | `image_url` is scraped and stored but never shown. Add `<img>` with fallback placeholder. |
| 4 | Fix `brand=null` for ליאור מוצרי חשמל products | `normalization/spec_extractor.py` or migration script | Small | 727 home appliance products have `brand=null` because JSON-LD doesn't include brand. Parse brand from product name with regex or Gemini. |
| 5 | Filter null-price products from results or show "מחיר לא זמין" | `api/routes/search.py`, `frontend/src/components/ResultCard.tsx` | Small | 3,898 products show blank price — looks broken. |
| 6 | Add min_price filter alongside existing max_price | `api/schemas.py`, `api/routes/search.py`, `frontend/src/components/FilterBar.tsx` | Small | Enables ₪500–₪2000 range queries. |
| 7 | Add availability filter — hide out-of-stock by default | `api/schemas.py`, `api/routes/search.py` | Small | 36% of products are out of stock. |
| 8 | Re-run scraper on 82 stores still in retry queue | `scraper/sitemap_scraper.py` | Trivial | Run: `python -m scraper.sitemap_scraper` |
| 9 | Store-level dedup — STORY / קבוצת story are same chain | DB migration or cleanup script | Small | Two store rows for same chain — merge them. |

---


---

## Git Workflow — Mandatory for All Agents

> This section is enforced. A task is NOT done until the branch is pushed and STATUS.md is updated.
> Claude Code agents must follow this workflow exactly — no exceptions.

---

### Branch naming convention

```
feature/<short-description>     # new feature
fix/<short-description>         # bug fix
infra/<short-description>       # infrastructure, Docker, CI
refactor/<short-description>    # code cleanup, no behavior change
test/<short-description>        # adding or fixing tests
chore/<short-description>       # deps, config, docs
```

Examples:
```
feature/chat-interface
feature/redis-cache
fix/gemini-json-truncation
infra/docker-compose
test/auth-routes
chore/update-requirements
```

---

### Workflow every agent MUST follow

#### 1. Before starting any work
```bash
cd /Users/barakganon/personal_projects/FindMe
git checkout master
git pull origin master
git checkout -b <branch-name>
# Example: git checkout -b feature/redis-cache
```

#### 2. Commit frequently — after every logical unit of work
Do NOT batch everything into one commit at the end.
Each of these warrants its own commit:
- New file created and working
- Existing file modified with a coherent change
- Tests written and passing
- Migration created and applied
- Bug fixed

```bash
git add <specific-files>   # never: git add .  — always be explicit
git commit -m "<type>(<scope>): <what and why>"
```

#### 3. Commit message format (Conventional Commits)
```
<type>(<scope>): <imperative description>

[optional body: why this change, what problem it solves]
[optional footer: Breaking Change, closes #issue]
```

Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `infra`

Good examples:
```
feat(chat): add Redis intent cache to skip Gemini on repeated queries
feat(auth): implement JWT get_optional_user dependency
fix(search): fall back to no-city filter when city returns 0 results
test(auth): add 8 tests for register/login/anonymous fallback
infra(docker): add docker-compose with redis and celery services
chore(deps): add python-jose and passlib to requirements.txt
refactor(chat): extract build_user_context_block into chat_utils.py
docs(claude): update sprint status after infrastructure sprint
```

Bad examples (do not use):
```
update files          ← too vague
fix bug               ← which bug?
WIP                   ← never commit WIP without a clear description
changes               ← meaningless
```

#### 4. Push branch and open PR description
```bash
git push origin <branch-name>
```

After pushing, append to STATUS.md:
```
Branch: feature/redis-cache → pushed to origin ✅
Commits: 4 commits (see git log)
```

#### 5. When the task is fully complete: merge to master
```bash
git checkout master
git pull origin master
git merge --no-ff <branch-name> -m "Merge branch '<branch-name>': <summary>"
git push origin master
git branch -d <branch-name>   # delete local branch after merge
```

Use `--no-ff` (no fast-forward) always — this preserves the branch history in the graph.

---

### Commit frequency targets

| Task type | Minimum commits |
|-----------|----------------|
| New file (e.g. api/cache.py) | 1 commit when file works end-to-end |
| Wiring existing file (e.g. search.py + cache) | 1 commit per file edited |
| Alembic migration | 1 commit (migration file + model update together) |
| Test file | 1 commit when tests pass |
| Bug fix | 1 commit with clear description of what was wrong |
| Multi-task sprint | Minimum 1 commit per task — ideally more |

Target: **at least 8–15 commits per sprint**. If you finish a sprint with 2 commits, you batched too much.

---

### Multi-agent branch strategy

Each agent works on its own branch. Agents never commit to master directly.
The orchestrator merges branches in dependency order after Phase 3 tests pass.

```
master
  ├── feature/ui-redesign          ← UI Agent
  ├── infra/redis-cache            ← API Infra Agent  
  ├── infra/celery-tasks           ← Scraper Agent
  ├── infra/docker-compose         ← DevOps Agent
  ├── feature/auth-backend         ← API Auth Agent
  └── feature/auth-frontend        ← Frontend Auth Agent
```

Merge order (orchestrator does this in Phase 4):
1. `infra/docker-compose` → master (no conflicts, standalone files)
2. `infra/redis-cache` → master
3. `infra/celery-tasks` → master
4. `feature/ui-redesign` → master
5. `feature/auth-backend` → master (after DB migration merged)
6. `feature/auth-frontend` → master (after auth-backend merged)

---

### What NOT to do with git

- Never `git add .` — always stage specific files
- Never commit `.env` — it's in .gitignore, keep it there
- Never force push to master (`git push --force origin master`)
- Never commit generated files: `__pycache__/`, `*.pyc`, `node_modules/`, `dist/`
- Never commit without a meaningful message
- Never finish a task without pushing the branch
- Never merge your own branch without tests passing

---

### Quick reference

```bash
# Start new feature
git checkout master && git pull origin master
git checkout -b feature/my-feature

# Save progress (do this often)
git add api/cache.py api/dependencies.py
git commit -m "feat(cache): add Redis search result cache with SHA256 key"

# Push branch
git push origin feature/my-feature

# Merge when done (orchestrator only)
git checkout master && git pull origin master
git merge --no-ff feature/my-feature -m "Merge branch 'feature/my-feature': add Redis cache layer"
git push origin master
git branch -d feature/my-feature
```

