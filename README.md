# FindMe — BuyMe Smart Search

**FindMe** lets Israeli consumers discover where to buy specific products using their [BuyMe](https://buyme.co.il) gift card. Paste any product URL or type a Hebrew/English search query — FindMe finds that exact product, or the closest alternatives, across BuyMe partner stores with prices and locations.

---

## How It Works

```
User query (URL or free text)
        │
        ▼
  Gemini AI extracts product name
        │
        ▼
  Gemini embedding (gemini-embedding-001)
        │
        ▼
  pgvector cosine similarity search
        │                     │
  128k+ products         ILIKE fallback
  across 182 stores      (while embeddings build)
        │
        ▼
  Results ranked by similarity + filters
  (price, city, online-only, radius)
```

---

## Current Data

| Metric | Count |
|---|---|
| BuyMe partner stores | 1,226 |
| Scraped Shopify stores | 182 |
| Products in DB | 128,981 |
| Store-product listings | 172,946 |
| Products with embeddings | ~990 (growing daily) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | Python 3.13 · FastAPI · async SQLAlchemy |
| Database | PostgreSQL · pgvector (semantic search) |
| AI | Gemini 2.0 Flash (extraction) · gemini-embedding-001 (768-dim vectors) |
| Scraping | httpx · BeautifulSoup4 · Playwright |
| Frontend | React 18 · TypeScript · Tailwind CSS · Leaflet.js (RTL Hebrew) |
| Migrations | Alembic |

---

## Project Structure

```
FindMe/
├── api/
│   ├── main.py               # FastAPI app entry point
│   ├── dependencies.py       # Gemini client, DB session
│   ├── schemas.py            # Pydantic request/response models
│   └── routes/
│       ├── search.py         # POST /search — vector + ILIKE search
│       └── stores.py         # GET /stores — paginated store list
│
├── scraper/
│   ├── base.py               # BaseScraper (all scrapers inherit this)
│   ├── buyme_store_scraper.py  # Scrapes buyme.co.il partner store list
│   ├── shopify_product_scraper.py  # /products.json fast-path (182 stores)
│   ├── woocommerce_product_scraper.py  # /wp-json/wc/v3/products fast-path
│   ├── sitemap_scraper.py    # WordPress sitemap + JSON-LD scraper
│   ├── shopify_detector.py   # Detects Shopify stores
│   └── scheduler.py          # Celery scheduled scrape jobs
│
├── db/
│   ├── models.py             # SQLAlchemy ORM models
│   ├── seed_stores.py        # Load BuyMe stores into DB
│   ├── embed_products.py     # Batch-embed products with Gemini
│   ├── vector_index.py       # pgvector query helpers
│   └── migrations/           # Alembic migration versions
│
├── normalization/
│   ├── name_normalizer.py    # Canonical product names (HE+EN)
│   ├── category_classifier.py
│   ├── spec_extractor.py
│   └── deduplication.py      # Embedding-based dedup
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # Main app (search + results + map)
│   │   ├── components/
│   │   │   ├── SearchBox.tsx   # Hebrew RTL search input
│   │   │   ├── ResultCard.tsx  # Product result card
│   │   │   └── StoreMap.tsx    # Leaflet store map
│   │   ├── api.ts            # API client (POST /search)
│   │   └── types.ts          # TypeScript interfaces
│   └── package.json
│
└── tests/
    ├── scraper/
    ├── normalization/
    └── api/
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL with pgvector extension
- Node.js 18+
- Gemini API key (free tier works)

### 1. Clone & Install

```bash
git clone <repo>
cd FindMe
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env:
#   DATABASE_URL=postgresql+asyncpg://localhost/buyme_search
#   GEMINI_API_KEY=your_key_here
```

### 3. Database Setup

```bash
createdb buyme_search
python -m alembic upgrade head
```

### 4. Seed Data

```bash
# Scrape BuyMe store list (~1,226 stores)
python -m scraper.buyme_store_scraper

# Seed stores into DB
python -m db.seed_stores

# Scrape Shopify store products (fast-path, ~182 stores)
python -m scraper.shopify_product_scraper

# Generate product embeddings (runs in background, respects rate limits)
python -m db.embed_products &
```

### 5. Start API

```bash
uvicorn api.main:app --reload
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### 6. Start Frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
```

---

## API Reference

### `POST /search`

Search for products using natural language or a product URL.

**Request:**
```json
{
  "query": "אוזניות של sony",
  "filters": {
    "online_only": false,
    "city": null,
    "max_price": 500,
    "min_match_score": 0.3
  }
}
```

**Response:**
```json
{
  "results": [
    {
      "canonical_name": "Sony WH-1000XM5 אוזניות אלחוטיות",
      "brand": "Sony",
      "store": {
        "name_he": "שילב",
        "is_online": true,
        "city": null
      },
      "price": 1299.0,
      "currency": "ILS",
      "availability": true,
      "product_url": "https://...",
      "match_score": 0.91
    }
  ],
  "total": 12,
  "exact_matches": 3,
  "similar_matches": 9,
  "search_time_ms": 540
}
```

### `GET /stores`

```
GET /stores?page=1&page_size=20&category=retail&online_only=true
```

### `GET /health`

```json
{"status": "ok", "version": "0.1.0"}
```

---

## Scraping Strategy

| Approach | Coverage | Status |
|---|---|---|
| Shopify `/products.json` | ~15% of stores | ✅ Complete |
| WooCommerce REST API | Most IL stores lock it (401) | ⚠️ Limited |
| WordPress Sitemaps + JSON-LD | ~30% of stores | 🔄 Running |
| Playwright HTML scraping | Remaining stores | 🔜 Planned |

Most Israeli retail stores use Shopify or WordPress/WooCommerce. The Shopify fast-path gives free structured data — no HTML parsing needed.

---

## Embeddings

Products are embedded with **Gemini `gemini-embedding-001`** (768 dimensions) for semantic similarity search.

```bash
# Embed all products (prioritizes most-popular first)
python -m db.embed_products

# Embed a specific batch
python -m db.embed_products --limit 500 --batch-size 20
```

> **Note:** Gemini free tier allows ~1,500 embedding requests/day. Full coverage of 128k products takes ~4 days. Search falls back to ILIKE keyword matching for unembedded products.

---

## Database Schema

```sql
stores          -- 1,226 BuyMe partner stores (name, URL, category, location)
products        -- 128k+ canonical deduplicated products (name, brand, embedding)
store_products  -- 172k+ store-specific listings (price, availability, URL)
scrape_runs     -- Scrape audit log (status, counts, timestamps)
```

---

## Multi-Agent Development

This project uses Claude Code multi-agent sessions. Each agent owns a specific folder:

| Agent | Owns | Never touches |
|---|---|---|
| Scraper Agent | `scraper/` | `api/`, `frontend/` |
| API Agent | `api/`, `db/` | `scraper/`, `frontend/` |
| Frontend Agent | `frontend/` | Everything else |
| Normalization Agent | `normalization/` | Everything else |

---

## Roadmap

- [x] BuyMe store list scraping (1,226 stores)
- [x] Shopify fast-path product scraping (128k products)
- [x] Natural language + URL search with pgvector
- [x] React frontend with Hebrew RTL layout
- [ ] Sitemap scraper for WordPress stores
- [ ] Vector search coverage >50% of products
- [ ] Location-based filtering (PostGIS)
- [ ] Celery scheduled re-scraping
- [ ] AI normalization pipeline (dedup, canonical names)
- [ ] Admin dashboard for scrape health
- [ ] Public deployment
