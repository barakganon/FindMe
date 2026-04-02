# FindMe — BuyMe Smart Search: Project Guide

## Project Purpose

**FindMe** is a product discovery platform that lets Israeli consumers find where to buy specific products using their BuyMe gift card. A user pastes any product URL (from Amazon IL, KSP, Zap, iHerb, etc.) and the system finds that exact product — or the closest alternatives — available at BuyMe partner stores, with prices and locations.

**Core flow:** buyme.co.il → scrape stores → scrape product catalogs → normalize with AI → unified DB → semantic search → user results

---

## Current Status

> **Update this section every session so agents always know where things stand.**

- **Phase:** Week 4 — Electronics focus, search quality improvements
- **Last completed (2026-04-01):**
  - **Electronics strategy**: Identified key electronics/appliances BuyMe stores: CrypTech (7,846 products), Intech (593), Alltech (245), ליאור מוצרי חשמל (228+)
  - **Sitemap scraper fixes**: (1) JSON-LD `@graph` support (Yoast SEO WooCommerce pattern), (2) processes ALL product sitemaps (not just first), (3) increased cap to 2,000 URLs/store
  - **Frontend type fix**: `SearchResult` → `ProductResult` with nested `StoreInfo` — ResultCard now shows correct fields, StoreMap uses `store.lat/lng`
  - **Search improvements**: ILIKE fallback now searches brand + canonical_name, deduplicates by (product_id, store_id), sorted by word-overlap score
  - **API schema**: Added `lat`/`lng` to `StoreInfo` response for map display
  - **Embed script**: Added `--store-id` flag to prioritize embedding per store; 4 embed processes running in background
  - **DB stats**: 134,036 products, 179,487 store_products, 2,070 embedded (1.5%), 426 stores geocoded
- **In progress:**
  - CrypTech embedding: ~980/7,846 (background, throttled by Gemini free tier)
  - ליאור מוצרי חשמל re-scraping with @graph fix + all-sitemaps support
  - Alltech re-scraping for full catalog
- **Blocked:** Gemini free tier ~1,500 requests/day; 4 parallel embed processes may hit daily quota; consider upgrading Gemini plan
- **Electronics stores confirmed** (BuyMe partners):
  - CrypTech (7,846): computers, GPUs, peripherals, networking
  - Intech (593): tech accessories
  - Alltech (245): measurement/science tools
  - ליאור מוצרי חשמל (2,500+ URLs): home appliances (refrigerators, dishwashers, BBQ)
  - Note: KSP, iDigital, Bug are NOT BuyMe partners
- **Restaurants/fashion/hotels**: Keep geocoding for location filter; skip product scraping
- **Next priority:**
  1. Wait for CrypTech embedding to complete (7,846 → full semantic coverage for electronics)
  2. Re-run geocoding for ungeocoded stores (improve location filtering)
  3. Add pagination to frontend (currently limited to 20 results)
  4. Consider Gemini paid tier for faster embedding throughput

---

## Tech Stack

### Backend
- **Python 3.11 / FastAPI** — async REST API (`POST /search`, `GET /stores`)
- **async SQLAlchemy + Alembic** — ORM + migrations for PostgreSQL
- **Celery + Redis** — scheduled scrape jobs
- **Playwright** — scraping JS-heavy store sites
- **requests / BeautifulSoup4** — scraping static HTML sites
- **PostgreSQL** — primary data store
- **pgvector** — vector index for semantic product search
- **PostGIS** — geolocation filtering
- **S3 / local file store** — raw scraped HTML + JSON archive

### AI / ML
- **Claude API (claude-sonnet-4-20250514)** — product normalization, category classification, spec extraction, URL-based product extraction
- **Instructor library** — structured Pydantic output from Claude (never parse raw JSON manually)
- **OpenAI embeddings (text-embedding-3-small)** — product embeddings for semantic search + dedup

### Frontend
- **React + TypeScript** — UI
- **Tailwind CSS** — styling
- **RTL support** — Hebrew-first layout (`dir="rtl"`)
- **Leaflet.js** — store map view
- Mobile-first responsive design

---

## Coding Conventions

> Claude Code agents must follow these at all times.

- **Always use async/await** in FastAPI routes and DB operations — never blocking calls
- **All Claude API calls use Instructor** for structured output — never parse raw text
- **Hebrew + English both supported** in all text fields — never assume ASCII
- **All scrapers inherit from `BaseScraper`** in `scraper/base.py`
- **Never insert raw scraped data** — always normalize before DB insertion
- **Type hints everywhere** — all functions must have full type annotations
- **Pydantic models for all API schemas** — defined in `api/schemas.py`
- **Environment variables via python-dotenv** — never hardcode API keys
- **Tests live in `tests/`** mirroring the source structure — e.g. `tests/scraper/test_ksp.py`
- **Commits:** small and frequent, descriptive messages, after each working feature

---

## Multi-Agent Work Split

> When spawning sub-agents, assign ownership strictly by folder. Agents must NOT touch files outside their domain without explicit instruction.

| Agent | Owns | Never touches |
|-------|------|---------------|
| **Scraper Agent** | `scraper/` | `api/`, `frontend/` |
| **Normalization Agent** | `normalization/` | `scraper/`, `api/`, `frontend/` |
| **API Agent** | `api/`, `db/` | `scraper/`, `frontend/` |
| **Frontend Agent** | `frontend/` | Everything else |

**Coordination rule:** If an agent needs something from another domain (e.g. scraper needs a DB model), it should note the requirement in a comment and flag it to the orchestrator — not reach into the other module itself.

**Typical multi-agent session example:**
```
"Spawn a subagent to build the KSP scraper in scraper/ksp.py 
while you build the Stores SQLAlchemy model in db/models.py. 
Keep work strictly in those files."
```

---

## File Structure

```
FindMe/
├── CLAUDE.md                    ← This file — read every session
├── .env                         ← API keys (never commit)
├── .env.example                 ← Template for env vars
├── requirements.txt
├── main.py                      ← Entry point
│
├── scraper/
│   ├── base.py                  ← BaseScraper class (all scrapers inherit this)
│   ├── buyme_store_scraper.py   ← Scrape buyme.co.il store list
│   ├── shopify_detector.py      ← Check /products.json fast-path first
│   ├── scheduler.py             ← Celery tasks for scheduled scraping
│   └── stores/
│       ├── ksp.py
│       ├── ivory.py
│       └── ...                  ← One file per store chain
│
├── normalization/
│   ├── name_normalizer.py       ← Claude: canonical product names (HE+EN)
│   ├── category_classifier.py   ← Claude: unified taxonomy classification
│   ├── spec_extractor.py        ← Claude: brand, model, color, size extraction
│   └── deduplication.py         ← Embedding-based same-product detection
│
├── db/
│   ├── models.py                ← SQLAlchemy models (see schema below)
│   ├── vector_index.py          ← pgvector setup + embedding queries
│   └── migrations/              ← Alembic migrations
│
├── api/
│   ├── main.py                  ← FastAPI app init
│   ├── schemas.py               ← All Pydantic request/response models
│   └── routes/
│       ├── search.py            ← POST /search
│       └── stores.py            ← GET /stores
│
├── tests/
│   ├── scraper/
│   ├── normalization/
│   ├── api/
│   └── conftest.py
│
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── SearchBox.tsx
    │   │   ├── ResultCard.tsx
    │   │   ├── StoreMap.tsx
    │   │   └── AdminDashboard.tsx
    │   └── App.tsx
    └── package.json
```

---

## Database Schema

```sql
-- Partner stores from buyme.co.il
stores (
  id, name_he, name_en, url, buyme_category,
  is_online, address, lat, lng,
  last_scraped_at, scrape_status
)

-- Canonical deduplicated products
products (
  id, canonical_name, brand, model,
  category_path, specs_json,
  embedding_vector,  -- pgvector
  first_seen_at
)

-- One product → many store listings
store_products (
  product_id, store_id, price,
  availability, product_url, last_updated
)

-- Raw scrape archive (for reprocessing)
scrape_runs (
  id, store_id, run_at, status,
  raw_json_path, products_found, errors
)
```

---

## Architecture — 5 Layers

### Layer 1: Data Ingestion
| Component | Description | Tech |
|---|---|---|
| BuyMe Store Scraper | Scrape buyme.co.il → partner stores (name, URL, category, location) | Playwright + BS4 |
| Shopify Detector | Check `/products.json` before any HTML scraping | requests |
| Per-Store Scrapers | Crawl each retail store catalog | Playwright / requests+BS4 |
| Scrape Scheduler | Re-scrape on schedule; detect price/availability changes | Celery + Redis |
| Raw Data Archive | Store raw HTML + JSON per run for reprocessing | PostgreSQL + S3 |

### Layer 2: AI Normalization Pipeline
| Component | Description | Tech |
|---|---|---|
| Name Normalizer | Canonicalize Hebrew/English names | Claude API + Instructor |
| Category Classifier | Unified taxonomy, bilingual | Claude API + Instructor |
| Spec Extractor | Brand, model, color, size from descriptions | Claude API + Instructor |
| Deduplication Engine | Same product across stores → master product record | Embeddings + cosine similarity |

### Layer 3: Product Database
pgvector on `products.embedding_vector` for semantic search. PostGIS on `stores.lat/lng` for distance queries.

### Layer 4: Search & Matching Engine
| Component | Description | Tech |
|---|---|---|
| User Product Extractor | Any URL → structured product info | Claude API + tool use |
| Exact Match Search | Near-exact product in dedup index | pgvector |
| Similar Product Search | Semantic fallback + Claude explanation | RAG + Claude API |
| Location Filter | Distance, online-only, city filter | PostGIS |

### Layer 5: Frontend & API
React + Tailwind + RTL. FastAPI async backend. Leaflet.js map. Admin dashboard for scrape health.

---

## Scraping Strategy

| Store Type | Approach | Priority |
|---|---|---|
| Large retail chains (KSP, Ivory, Bug) | Sitemaps + structured pages; one scraper per chain | 🔴 First |
| Shopify stores | `/products.json` fast-path — free structured data | 🔴 First |
| Restaurants | Name + location + cuisine only — no product scraping | 🟡 Second |
| Small unique stores | On-demand scraping when user query hits uncrawled store | 🟢 Later |

**Always check Shopify first** — many Israeli online stores expose `/products.json` for free.

---

## Key Design Decisions

- **Hebrew-first:** All normalization, classification, and search must handle mixed Hebrew/English
- **Master product record:** One canonical product → many store listings. Critical for "where can I buy THIS exact product?" queries
- **Shopify fast-path:** Check `/products.json` before scraping HTML — covers a large portion of stores for free
- **Scrape on demand for long tail:** Small stores trigger scraping when first queried, not pre-emptively
- **Raw data archive:** Store everything raw so catalog can be rebuilt without re-scraping
- **Instructor over raw Claude output:** Always use Instructor for structured data — never parse raw LLM text manually

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://localhost:6379
AWS_S3_BUCKET=           # optional, for raw data archive
CELERY_BROKER_URL=redis://localhost:6379
```

---

## Build Timeline

| Weeks | Milestone |
|---|---|
| 1–2 | Scrape BuyMe store list. Build Stores table. Categorize stores. |
| 3–4 | Scrapers for top 5 retail chains. Normalize with Claude. First product data. |
| 5–6 | Search API + basic React UI. First end-to-end demo. |
| 7–8 | Vector search + similar product fallback. Location filtering. |
| 9–10 | Expand to 20+ stores. Scrape scheduler. Admin dashboard. |
| 11–12 | Polish UI (Hebrew RTL, mobile). Auth + saved searches. Deploy publicly. |
Read ai-docs/seo-llmo-guide.md for SEO/LLMO practices.

Read ai-docs/aws-spa-deployment-guide.md for AWS SPA deployment.

Read ai-docs/web-accessibility-guide.md for web accessibility (WCAG 2.2).

Read ai-docs/web-performance-guide.md for web performance and Core Web Vitals.
