# FindMe — BuyMe Smart Search: Live Status
> Last updated: 2026-04-02

---

## System Overview

FindMe lets Israeli users search for products purchasable with a BuyMe gift card.
Users type a product name (Hebrew/English) or paste a product URL → system returns matching products at BuyMe partner stores with prices and locations.

**Services currently running:**
| Service | URL | Status |
|---|---|---|
| FastAPI backend | http://localhost:8000 | ✅ Running |
| React frontend | http://localhost:5173 | ✅ Running |
| PostgreSQL + pgvector | localhost:5432 | ✅ Running |

---

## Database Stats (as of 2026-04-02)

| Metric | Value |
|---|---|
| Total stores | 1,226 |
| Total products | 135,263 |
| Store-product links | 180,716 |
| Products with embeddings | 2,076 (1.5%) |
| Products with category | 91,202 (67%) |
| Products with null price | 3,709 |
| In-stock products | 115,021 (63%) |
| Geocoded stores | 426 / 1,226 |
| Physical retail stores without geocoding | 333 |

### Store Scrape Status
| Status | Count | Meaning |
|---|---|---|
| `no_sitemap` | 754 | No accessible sitemap — mostly restaurants/hotels/redirect-only stores |
| `done` | 200 | Sitemap scraped, products upserted |
| `success` | 182 | Shopify `/products.json` scraped |
| `failed` | 59 | Had a sitemap but scrape crashed (parser errors, timeouts, encoding) |
| `pending` | 31 | In queue / currently scraping |

---

## Electronics Stores (Priority Focus)

| Store | Products | Embedded | Status | Notes |
|---|---|---|---|---|
| CrypTech | 7,846 | 980 (12%) | ✅ done | Computers, GPUs, peripherals, networking. Main electronics store in BuyMe. |
| Alltech | 975 | 4 | ✅ done | Scientific/measurement tools, digital gadgets, microscopes |
| ליאור מוצרי חשמל | 727 | 0 | ✅ done | Home appliances: refrigerators, dishwashers, BBQ grills |
| Intech | 593 | 2 | ✅ done | Tech accessories |

**Confirmed NOT BuyMe partners:** KSP, iDigital, Bug, Ivory — these chains are not in the store list at all.

---

## Top 10 Stores by Product Count

| Store | Products | Category |
|---|---|---|
| REPLAY | 8,486 | Fashion |
| CrypTech | 7,846 | Electronics ✅ |
| SOHO | 6,951 | Fashion |
| BIMBA Y LOLA | 6,213 | Fashion |
| CHOZEN | 6,213 | Fashion |
| תחביבן | 5,919 | Crafts/Hobbies |
| שילב | 5,405 | Fashion |
| FOX | 4,500 | Fashion |
| STORY / קבוצת story | 4,485 | Fashion |

Observation: BuyMe's catalog is dominated by **fashion**. Electronics (CrypTech) is #2 by product count but the only major tech store.

---

## Search Engine

### How it works (current implementation)
1. Query sent to `POST /search`
2. Gemini `gemini-embedding-001` generates 768-dim embedding (~1s)
3. **ILIKE keyword search** runs in parallel — searches `canonical_name` + `brand` for query words
4. **pgvector cosine search** runs on the 2,076 embedded products
5. Results merged: ILIKE word-matches first → high-similarity vector hits (>0.5) → remaining
6. Filters: `online_only`, `city`, `max_price`, `min_match_score`
7. Returns top 20 results

### Search quality by query type
| Query type | Quality | Notes |
|---|---|---|
| Hebrew product name ("מקרר", "אוזניות") | 🟡 Good | ILIKE finds exact keyword matches |
| Hebrew + brand ("מדיח Miele", "Bosch מקרר") | 🟡 Good | Word-overlap similarity handles multi-word |
| English brand + model ("Logitech MX Master") | 🟢 Excellent | Vector search finds semantically similar products |
| English category ("gaming headphones") | 🟢 Good | Vector search handles semantic meaning |
| Specific model number ("RTX 4090") | 🟢 Excellent | Both ILIKE and vector match |
| URL → product extraction | 🟡 Fair | Gemini extracts name from URL, then searches |
| Rare/niche products | 🔴 Poor | Low embedding coverage; ILIKE only if exact keyword match |

---

## Known Problems 🔴

### Critical

**1. Only 1.5% of products embedded**
The biggest bottleneck. Gemini free tier allows ~1,500 requests/day. With 135k products, full embedding coverage takes ~90 days at this rate. Vector search is meaningless for most of the catalog. Solution: upgrade to Gemini paid tier (~$2.70 total for all products).

**2. CrypTech embedding very slow (12%)**
The main electronics store is 88% on ILIKE fallback. Users searching for specific hardware (CPU models, GPU names) often get poor results if the exact product name isn't in their query. This will improve as embedding progresses, but slowly.

**3. No pagination — hard 20 result limit**
If the best match is result #21 it's invisible to the user. No "load more" button, no page numbers.

**4. Stale product data**
Shopify stores scraped ~March 25, sitemap stores ~April 1. Prices and stock change daily. There is **no scheduled re-scraping** — the Celery scheduler skeleton exists in `scraper/scheduler.py` but tasks are not wired up. Data will get increasingly wrong over time.

### Significant

**5. 333 physical stores ungeocoded**
The Leaflet map and location filter don't work for 78% of physical stores. The `db/geocode_stores.py` script exists and works; it just needs to be run again (takes ~6 min at 1.1s/request).

**6. 59 failed scrapes**
These stores have sitemaps but crashed during scraping. Some were due to `ParserRejectedMarkup` (now fixed), others are timeouts or encoding errors. Re-running on these may recover many.

**7. No product deduplication**
"Samsung T7 SSD 1TB" appears as separate `products` rows for each store. The `normalization/deduplication.py` module with embedding-based dedup exists but is **never called**. This means "find everywhere I can buy this" shows duplicates instead of one product with multiple store prices.

**8. Brand field null on appliance products**
ליאור's JSON-LD schema doesn't include a `brand` field — so all 727 home appliance products have `brand=null`. Searching "Miele" or "Bosch" by brand alone returns nothing from ליאור.

**9. Search is slow (~1.5–2 seconds)**
Running both ILIKE + pgvector + Gemini embedding in series/parallel adds up. The Gemini embedding API call alone takes ~1s on free tier. This is noticeable in the UI.

### Minor

**10. No category-based browsing**
No way to say "show me all electronics" or "all refrigerators." The UI is search-only. Category data exists (67% of products have `category_path`) but isn't exposed to users.

**11. 3,709 products with null price**
Show up in results with a blank price field — looks broken. Should either filter these out or show "price not available."

**12. AdminDashboard.tsx is a stub**
The component file exists but contains only `export {}`. No way to monitor scrape health or embedding progress in the UI.

**13. Intech barely embedded (2/593)**
Small batch of tech accessories — would complete in ~2 min on free tier. Should be prioritized when quota resets.

**14. No error state for Gemini failures**
If Gemini embedding is down or rate-limited during a search, the API falls through to ILIKE-only silently. The user doesn't know results might be degraded.

---

## Improvement Suggestions 💡

### High Priority (biggest impact)

| # | Improvement | Effort | Impact |
|---|---|---|---|
| 1 | **Upgrade Gemini to paid tier** | 5 min (billing) | 🔥 Critical — enables full embedding in hours, not months |
| 2 | **Run geocoding for 333 stores** | `python -m db.geocode_stores` | High — enables location filtering |
| 3 | **Add pagination** to search API + frontend | Small | High — users see more results |
| 4 | **Wire Celery scheduler** for re-scraping | Medium | High — keeps data fresh |
| 5 | **Re-run scraper on 59 failed stores** | `python -m scraper.sitemap_scraper` | Medium — recovers missed products |

### Medium Priority

| # | Improvement | Effort | Impact |
|---|---|---|---|
| 6 | **Brand filter in UI** (`FilterBar.tsx`) | Small | Medium — useful for electronics users |
| 7 | **Availability filter** — hide out-of-stock | Small | Medium — UX improvement |
| 8 | **Cache search results in Redis** | Medium | Medium — cuts latency for common queries |
| 9 | **Wire deduplication pipeline** | Large | High — "buy X across multiple stores" becomes accurate |
| 10 | **Embed Intech (593 products)** | `python -m db.embed_products --store-id 8ea8c70b...` | Low — improves tech accessories search |
| 11 | **Fix brand=null for ליאור products** | Small | Medium — enable brand search for home appliances |

### Longer Term

| # | Improvement | Notes |
|---|---|---|
| 12 | **Implement AdminDashboard** | Scrape health, embedding progress, per-store stats |
| 13 | **Similar products explanation** | Use Gemini to explain why a result is similar (builds user trust) |
| 14 | **URL scraping improvements** | Better extraction from KSP/Zap URLs which users paste |
| 15 | **Mobile UI testing** | RTL + mobile has known edge cases in Hebrew UI |
| 16 | **Min price filter** | Currently only max_price; add min to support "show me products ₪500–₪2000" |
| 17 | **Expand electronics coverage** | 754 `no_sitemap` stores — manual review may find more electronics/hardware stores |
| 18 | **Product image display** | URLs are scraped but not shown in `ResultCard` |
| 19 | **Search history / saved searches** | Requires auth but useful for repeat users |

---

## How to Resume Work

```bash
cd /path/to/FindMe
source .venv/bin/activate

# Start API
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Start frontend
cd frontend && npm run dev

# Run geocoding for 333 missing stores (~6 min)
python -m db.geocode_stores

# Embed products for a specific store (run after midnight when Gemini quota resets)
python -m db.embed_products --store-id c032bb0b-a854-49bd-999e-dc1150a6cfc4  # CrypTech
python -m db.embed_products --store-id 8ea8c70b-55fb-493c-bfb2-13b9bb692192  # Intech

# Re-scrape failed stores
python -m scraper.sitemap_scraper  # processes stores with status='pending'

# Check quick DB stats
psql postgresql://barakganon@localhost/buyme_search -c "
  SELECT scrape_status, COUNT(*) FROM stores GROUP BY scrape_status;
  SELECT COUNT(*) as products, COUNT(embedding_vector) as embedded FROM products;
"
```

---

## File Map

```
FindMe/
├── api/
│   ├── main.py              — FastAPI app, CORS, /health
│   ├── schemas.py           — Pydantic models (ProductResult, StoreInfo, SearchResponse, etc.)
│   ├── dependencies.py      — DB session, Gemini client, Settings
│   └── routes/
│       ├── search.py        — POST /search: hybrid ILIKE + pgvector search
│       └── stores.py        — GET /stores: paginated store list
├── scraper/
│   ├── buyme_store_scraper.py      — Playwright scraper for buyme.co.il store list
│   ├── shopify_product_scraper.py  — Shopify /products.json scraper
│   ├── sitemap_scraper.py          — WordPress/WooCommerce sitemap + JSON-LD scraper
│   ├── woocommerce_product_scraper.py — WC REST API (mostly 401 on IL stores)
│   └── scheduler.py                — Celery task skeleton (not wired)
├── db/
│   ├── models.py            — SQLAlchemy ORM: Store, Product, StoreProduct, ScrapeRun
│   ├── embed_products.py    — Gemini embedding pipeline (--store-id flag supported)
│   ├── geocode_stores.py    — Nominatim geocoding for store lat/lng
│   └── migrations/          — Alembic: 0001 init, 0002 unique constraint, 0003 vector 768-dim
├── normalization/
│   ├── name_normalizer.py   — Claude: canonical product names (HE+EN)
│   ├── category_classifier.py — Claude: unified taxonomy
│   ├── spec_extractor.py    — Claude: brand/model/color/size
│   └── deduplication.py     — Embedding-based dedup engine (NOT wired into pipeline)
└── frontend/src/
    ├── App.tsx              — Main layout, state, search flow
    ├── api.ts               — POST /search fetch wrapper
    ├── types.ts             — TypeScript: ProductResult, StoreInfo, SearchFilters, etc.
    └── components/
        ├── SearchBox.tsx    — Search input
        ├── FilterBar.tsx    — online_only, max_price, city filters
        ├── ResultCard.tsx   — Product card: name, brand, price, availability, store
        ├── StoreMap.tsx     — Leaflet map (shows geocoded results)
        └── AdminDashboard.tsx — STUB, not implemented
```
