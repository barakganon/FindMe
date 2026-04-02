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

## Store Progress by Industry

> Status key: ✅ success/done = scraped | 🔄 skipped = retry in progress | ⬜ no_sitemap = no product catalog found

### Electronics & Tech
| Store | Products | Embedded | Status |
|---|---|---|---|
| CrypTech (מחשוב, GPU, רשתות) | 7,846 | 7,823 (99%) | ✅ success |
| Alltech (כלי מדידה, גאדג'טים) | 975 | 975 (100%) | ✅ done |
| Intech (אביזרי טק) | 593 | 593 (100%) | ✅ success |
| ליאור מוצרי חשמל (מכשירי חשמל ביתיים) | 727 | 727 (100%) | ✅ done |
| IROBOT | 0 | 0 | 🔄 skipped |
| **Total** | **10,141** | **10,118 (99.8%)** | |

### Fashion & Clothing
| Store | Products | Embedded | Status |
|---|---|---|---|
| REPLAY | 8,486 | 8,466 (99%) | ✅ success |
| SOHO | 6,951 | 6,950 (99%) | ✅ success |
| BIMBA Y LOLA | 6,213 | 6,213 (100%) | ✅ success |
| CHOZEN | 6,213 | 6,213 (100%) | ✅ success |
| שילב | 5,405 | 5,401 (99%) | ✅ success |
| FOX | 4,500 | 4,500 (100%) | 🔄 skipped |
| STORY | 4,485 | 4,485 (100%) | ✅ success |
| קבוצת story | 4,485 | 4,485 (100%) | ✅ success |
| ALLSAINTS | 4,467 | 4,467 (100%) | ✅ success |
| מותגי קבוצת INTER JEANS | 4,105 | 4,099 (99%) | ✅ success |
| ITAY BRANDS | 3,925 | 3,920 (99%) | ✅ success |
| חנות בוטיק AYO | 2,312 | 2,312 (100%) | ✅ success |
| Mia Inspiration | 2,266 | 2,232 (98%) | ✅ success |
| אהבה קטנה | 2,095 | 2,095 (100%) | ✅ success |
| Miss Nori | 1,968 | 1,947 (98%) | ✅ success |
| Femina | 1,614 | 1,614 (100%) | ✅ success |
| WORKER | 1,543 | 1,528 (99%) | ✅ success |
| Dé Rococo | 1,503 | 1,503 (100%) | ✅ success |
| SWEETWEET | 1,176 | 1,176 (100%) | ✅ success |
| קולומביה, שבילים ואווטסיידרס | 1,153 | 1,153 (100%) | ✅ success |
| ICE CUBE | 1,015 | 973 (95%) | ✅ success |
| GOVANA Fashion | 982 | 975 (99%) | ✅ success |
| TRES | 425 | 2 (0%) | ✅ done ⚠️ |
| GANT | 250 | 250 (100%) | ✅ done |
| Desigual | 250 | 250 (100%) | ✅ done |
| RONEN CHEN | 601 | 575 (95%) | ✅ success |
| CASTRO | 77 | 77 (100%) | ✅ done |
| + ~40 more fashion stores | ~20,000 | ~19,800 | ✅ |
| H&O | 0 | 0 | ⬜ no_sitemap |
| VILEBREQUIN | 0 | 0 | ⬜ no_sitemap |
| INTOTO | 0 | 0 | ⬜ no_sitemap |
| **Total (scraped)** | **~97,000** | **~96,000 (99%)** | |

### Shoes & Bags
| Store | Products | Embedded | Status |
|---|---|---|---|
| STEVE MADDEN | 2,914 | 2,911 (99%) | ✅ success |
| תיק התיקים | 1,443 | 1,443 (100%) | ✅ success |
| נעלי נימרוד | 1,246 | 1,246 (100%) | ✅ success |
| מגה ספורט | 1,953 | 1,953 (100%) | ✅ success |
| אליטל | 977 | 977 (100%) | ✅ success |
| WE BAGS | 176 | 176 (100%) | ✅ done |
| iBags וקיפלינג | 72 | 72 (100%) | ✅ done |
| TIMBERLAND | 42 | 42 (100%) | ✅ done |
| ד"ר גב | 46 | 46 (100%) | ✅ done |
| **Total** | **~8,900** | **~8,870 (99%)** | |

### Home & Interior
| Store | Products | Embedded | Status |
|---|---|---|---|
| KUALA (שטיחים) | 2,941 | 2,941 (100%) | ✅ success |
| השטיח האדום | 2,837 | 2,837 (100%) | ✅ success |
| Pozitive (שטיחים) | 2,837 | 2,837 (100%) | ✅ success |
| Start Home | 1,646 | 1,644 (99%) | ✅ success |
| Fox Home | 1,637 | 1,637 (100%) | ✅ success |
| Casa Bella | 1,140 | 1,139 (99%) | ✅ success |
| SHAZLONG BY UNICO | 1,335 | 1,335 (100%) | ✅ success |
| Floralis (פרחים ועיצוב) | 1,805 | 1,805 (100%) | ✅ success |
| Buona Casa | 206 | 206 (100%) | ✅ success |
| HOME DECOR | 0 | 0 | 🔄 skipped |
| **Total** | **~16,400** | **~16,380 (99.9%)** | |

### Jewelry & Accessories
| Store | Products | Embedded | Status |
|---|---|---|---|
| Shiree Odiz | 1,648 | 1,648 (100%) | ✅ success |
| שלומית אופיר | 1,199 | 1,199 (100%) | ✅ success |
| TOUS | 250 | 250 (100%) | ✅ done |
| תכשיטי דנון | 661 | 661 (100%) | ✅ success |
| She-Ra Jewelry | 591 | 591 (100%) | ✅ success |
| GLO jewelries | 565 | 565 (100%) | ✅ success |
| HOTCROWN Jewelry | 865 | 865 (100%) | ⬜ no_sitemap* |
| Signet Collection | 376 | 376 (100%) | ✅ success |
| תכשיטי חביב | 325 | 325 (100%) | ✅ success |
| MON'E תכשיטים | 179 | 179 (100%) | ✅ success |
| + ~15 more jewelry stores | ~2,000 | ~2,000 | ✅ |
| **Total** | **~9,000** | **~9,000 (100%)** | |

*HOTCROWN had products loaded via Shopify despite `no_sitemap` status.

### Baby & Kids
| Store | Products | Embedded | Status |
|---|---|---|---|
| מוצצים | 3,697 | 3,697 (100%) | ✅ success |
| Babystar | 2,626 | 2,625 (99%) | ✅ success |
| רשת Bגוד | 1,537 | 1,534 (99%) | ✅ success |
| אליסיום עולם בריא לתינוקות | 114 | 114 (100%) | ✅ done |
| Bugaboo | 115 | 115 (100%) | ✅ done |
| Babybjorn | 28 | 28 (100%) | ✅ done |
| BABY BREZZA | 55 | 55 (100%) | ✅ success |
| **Total** | **~8,200** | **~8,170 (99.6%)** | |

### Sports & Fitness
| Store | Products | Embedded | Status |
|---|---|---|---|
| Under Armour | 1,953 | 1,953 (100%) | ✅ success |
| ENERGYM | 1,729 | 1,728 (99%) | ✅ success |
| Gon Surfing | 600 | 600 (100%) | ✅ success |
| KAHIKO Swimwear | 443 | 441 (99%) | ✅ success |
| JUV activewear | 335 | 335 (100%) | ✅ success |
| VOLT swimwear | 51 | 51 (100%) | ✅ success |
| **Total** | **~5,100** | **~5,100 (99.9%)** | |

### Hobbies & Crafts
| Store | Products | Embedded | Status |
|---|---|---|---|
| תחביבן (צביעה, רקמה, יצירה) | 5,919 | 5,919 (100%) | ✅ success |
| **Total** | **5,919** | **5,919 (100%)** | |

### Health & Beauty
| Store | Products | Embedded | Status |
|---|---|---|---|
| AHAVA | 189 | 189 (100%) | ✅ success |
| CHRISTINA קוסמטיקה | 247 | 247 (100%) | ✅ success |
| Eye Glow | 193 | 193 (100%) | ✅ done |
| אורגניקזון organic zone | 251 | 251 (100%) | ✅ done |
| Daphne Skin | 56 | 56 (100%) | ✅ success |
| Redefine Hair | 38 | 38 (100%) | ✅ success |
| Happy Hempy | 221 | 221 (100%) | ✅ success |
| La maison du savon | 63 | 63 (100%) | ✅ success |
| **Total** | **~1,500** | **~1,500 (100%)** | |

### Food, Chocolate & Wine
| Store | Products | Embedded | Status |
|---|---|---|---|
| מקס ברנר | 34 | 34 (100%) | ✅ success |
| Leonidas | 47 | 47 (100%) | ✅ success |
| ג'וליקה שוקולד | 73 | 73 (100%) | ✅ success |
| דה קרינה שוקולד | 85 | 85 (100%) | ✅ success |
| פרלינים | 61 | 61 (100%) | ✅ done |
| דובידו | 73 | 1 (1%) | ✅ done ⚠️ |
| יקב טוליפ | 53 | 53 (100%) | ✅ done |
| יקב בזק | 48 | 48 (100%) | ✅ done |
| מזיגה חופשית | 39 | 1 (2%) | ✅ done ⚠️ |
| מבשלת שריגים | 26 | 26 (100%) | ✅ done |
| טעימות | 466 | 466 (100%) | ✅ success |
| קפה אוסישקין | 261 | 261 (100%) | ✅ success |
| **Total** | **~1,300** | **~1,190 (91%)** | |

### Restaurants & Experiences
> These stores don't have product catalogs — they offer gift cards for meals, spa treatments, tours, etc. No products to scrape.

| Store | Scrape Status | Notes |
|---|---|---|
| ~367 restaurant/experience stores | ⬜ no_sitemap | Expected — no product catalog |
| Jiggeria, Ceramora, ASK Q, Mixta... | ✅ done (a few) | Some have "products" (packages/vouchers) |

---

## Database Stats (as of 2026-04-02)

| Metric | Value |
|---|---|
| Total stores | 1,226 |
| Total products | 135,865 |
| Store-product links | 181,362 |
| Products with embeddings | 134,963 (99.3%) ✅ |
| Products with category | 91,595 (67%) |
| Products with null price | 3,898 |
| In-stock products | 115,465 (64%) |
| Geocoded stores | 426 / 1,226 |
| Physical retail stores without geocoding | 500 |

### Store Scrape Status
| Status | Count | Meaning |
|---|---|---|
| `no_sitemap` | 754 | No accessible sitemap — mostly restaurants/hotels/redirect-only stores |
| `done` | 208 | Sitemap scraped, products upserted (+8 recovered from retry) |
| `success` | 182 | Shopify `/products.json` scraped |
| `skipped` | 82 | Previously failed — retry in progress (was 59 `failed` + 31 `pending`) |

---

## Electronics Stores (Priority Focus)

| Store | Products | Embedded | Status | Notes |
|---|---|---|---|---|
| CrypTech | 7,846 | 7,823 (99.7%) | ✅ done | Computers, GPUs, peripherals, networking. Main electronics store in BuyMe. |
| Alltech | 975 | 975 (100%) | ✅ done | Scientific/measurement tools, digital gadgets, microscopes |
| ליאור מוצרי חשמל | 727 | 727 (100%) | ✅ done | Home appliances: refrigerators, dishwashers, BBQ grills |
| Intech | 593 | 593 (100%) | ✅ done | Tech accessories |

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
4. **pgvector cosine search** runs on 134,963 embedded products (99.3% of catalog)
5. Results merged: ILIKE word-matches first → high-similarity vector hits (>0.5) → remaining
6. Filters: `online_only`, `city`, `brand`, `max_price`, `min_match_score`
7. Pagination: `page` + `page_size` (default 20); returns `total_available` for all pages
8. Returns up to 200 candidates, sliced to requested page

### Search quality by query type
| Query type | Quality | Notes |
|---|---|---|
| Hebrew product name ("מקרר", "אוזניות") | 🟢 Excellent | Vector search now covers nearly all products |
| Hebrew + brand ("מדיח Miele", "Bosch מקרר") | 🟢 Excellent | Brand filter + word-overlap + vector |
| English brand + model ("Logitech MX Master") | 🟢 Excellent | Vector search finds semantically similar products |
| English category ("gaming headphones") | 🟢 Excellent | Vector search handles semantic meaning across 99% of catalog |
| Specific model number ("RTX 4090") | 🟢 Excellent | Both ILIKE and vector match |
| URL → product extraction | 🟡 Fair | Gemini extracts name from URL, then searches |
| Rare/niche products | 🟡 Fair | Now much better with 99% embedding coverage |

---

## Known Problems 🔴

### Critical

**1. 500 physical stores ungeocoded**
The Leaflet map and location filter don't work for these stores. The 426 already geocoded had standard street addresses Nominatim could resolve. The remaining 500 have informal Israeli addresses (mall names like "עופר גרנד קניון", kibbutz names, hotel/complex names) that Nominatim cannot geocode. **Solution: switch to Google Maps Geocoding API** which handles these formats.

**2. Stale product data**
Shopify stores scraped ~March 25, sitemap stores ~April 1. Prices and stock change daily. There is **no scheduled re-scraping** — the Celery scheduler skeleton exists in `scraper/scheduler.py` but tasks are not wired up. Data will get increasingly wrong over time.

**3. 82 stores still in retry queue**
The scraper retry is running but takes ~5-6 min/store. Some stores may still fail due to timeouts or encoding errors even with the parser fixes.

### Significant

**4. No product deduplication**
"Samsung T7 SSD 1TB" appears as separate `products` rows for each store. The `normalization/deduplication.py` module with embedding-based dedup exists but is **never called**. This means "find everywhere I can buy this" shows duplicates instead of one product with multiple store prices.

**5. Search is slow (~1.5–2 seconds)**
Gemini embedding API call alone takes ~1s. ILIKE + pgvector run in parallel but Gemini is the bottleneck.

**6. Brand field null on appliance products**
ליאור's JSON-LD schema doesn't include a `brand` field — so all 727 home appliance products have `brand=null`. Brand filter for "Miele" or "Bosch" won't catch ליאור products.

### Minor

**7. No category-based browsing**
No way to say "show me all electronics" or "all refrigerators." The UI is search-only. Category data exists (67% of products have `category_path`) but isn't exposed to users.

**8. 3,898 products with null price**
Show up in results with a blank price field — looks broken. Should either filter these out or show "price not available."

**9. AdminDashboard.tsx is a stub**
The component file exists but contains only `export {}`. No way to monitor scrape health or embedding progress in the UI.

**10. No error state for Gemini failures**
If Gemini embedding is down or rate-limited during a search, the API falls through to ILIKE-only silently. The user doesn't know results might be degraded.

**11. STORY / קבוצת story double-counted**
Two separate store entries for the same store group. Deduplication needed at store level too.

---

## Improvement Suggestions 💡

### High Priority (biggest impact)

| # | Improvement | Effort | Impact |
|---|---|---|---|
| 1 | **Wire Celery scheduler** for re-scraping | Medium | 🔥 Critical — keeps data fresh |
| 2 | **Switch geocoding to Google Maps API** for 500 remaining stores | Small | High — enables location filtering for most physical stores |
| 3 | **Wire deduplication pipeline** | Large | High — "buy X across multiple stores" becomes accurate |
| 4 | **Fix brand=null for ליאור products** | Small | Medium — enable brand search for home appliances |

### Medium Priority

| # | Improvement | Effort | Impact |
|---|---|---|---|
| 5 | **Availability filter** — hide out-of-stock | Small | Medium — UX improvement |
| 6 | **Cache search results in Redis** | Medium | Medium — cuts latency for common queries |
| 7 | **Category browsing UI** | Medium | Medium — "show me all electronics" |
| 8 | **Filter null-price products** from results | Small | Low — cleaner UX |
| 9 | **Min price filter** | Small | Medium — support ₪500–₪2000 range |

### Longer Term

| # | Improvement | Notes |
|---|---|---|
| 10 | **Implement AdminDashboard** | Scrape health, embedding progress, per-store stats |
| 11 | **Similar products explanation** | Use Gemini to explain why a result is similar (builds user trust) |
| 12 | **URL scraping improvements** | Better extraction from KSP/Zap URLs which users paste |
| 13 | **Mobile UI testing** | RTL + mobile has known edge cases in Hebrew UI |
| 14 | **Expand electronics coverage** | 754 `no_sitemap` stores — manual review may find more electronics/hardware stores |
| 15 | **Product image display** | URLs are scraped but not shown in `ResultCard` |
| 16 | **Search history / saved searches** | Requires auth but useful for repeat users |
| 17 | **Store-level deduplication** | STORY/קבוצת story are the same chain — merge them |

---

---

## Development Plan 🗺️

The system is now functionally complete for an MVP: 99% embedding coverage, hybrid search, pagination, brand filter, and 135k products across 390 scraped stores. The remaining work falls into four phases — data quality, search quality, UI polish, and production deployment.

---

### Phase 1 — Data Quality & Freshness
**Goal:** Keep the catalog accurate and complete. Without this, the product data rots as stores update prices and stock.

| # | Task | Effort | Why |
|---|---|---|---|
| 1.1 | **Wire Celery scheduler** — re-scrape Shopify stores weekly, sitemap stores bi-weekly | Medium | Prices and availability change daily. Currently the entire catalog is a snapshot from March–April 2026. |
| 1.2 | **Google Maps geocoding** for 500 remaining physical stores | Small | Nominatim confirmed unable to resolve Israeli mall/complex addresses. Google Maps API handles them. Unlocks location filter for 500 more stores. |
| 1.3 | **Fix brand=null for ליאור products** — parse brand from product name using regex or Gemini | Small | 727 home appliance products are invisible to brand filter ("Miele", "Bosch", "Samsung"). |
| 1.4 | **Filter/handle null-price products** — show "price not available" or exclude from results | Small | 3,898 products show blank price in ResultCard — looks broken to users. |
| 1.5 | **Wire deduplication pipeline** (`normalization/deduplication.py`) | Large | Currently "Samsung T7 1TB" has one row per store. Dedup creates a master product → multiple store prices. This is essential for the core "where can I buy this?" use case. |
| 1.6 | **Re-embed ~902 failed products** | Trivial | 300 failed in last run (network errors). One re-run of `python -m db.embed_products` catches them. |

---

### Phase 2 — Search Quality
**Goal:** Make the search smarter, faster, and more useful for edge cases.

| # | Task | Effort | Why |
|---|---|---|---|
| 2.1 | **Redis result cache** — cache embeddings and query results for 5 min | Medium | Gemini embedding API (~1s) is the main latency bottleneck. Common queries ("אוזניות", "GPU") hit the same embedding every time. |
| 2.2 | **Category browsing** — `GET /categories` endpoint + browse UI | Medium | 67% of products have `category_path`. Users currently can't say "show me all electronics." Reduces reliance on search for discovery. |
| 2.3 | **Min price filter** — add `min_price` alongside existing `max_price` | Small | Enables "show me products ₪500–₪2000" — a common shopping pattern. |
| 2.4 | **Availability filter** — hide out-of-stock by default | Small | 36% of products are out of stock. Showing them by default adds noise. |
| 2.5 | **Better URL extraction** — improve Gemini prompt for KSP/Zap/iHerb URLs | Small | Current extraction is "fair" for URLs. Better prompting or structured parsing would improve it. |
| 2.6 | **Graceful Gemini failure** — show warning when embedding fails | Small | Currently falls through to ILIKE silently. User should know results may be degraded. |

---

### Phase 3 — UI / UX Polish
**Goal:** Make the frontend production-quality. Currently functional but rough.

| # | Task | Effort | Why |
|---|---|---|---|
| 3.1 | **Product images** — show `image_url` in ResultCard | Small | Images scraped and stored but not displayed. Dramatically improves scan-ability of results. |
| 3.2 | **AdminDashboard** — scrape health, embedding progress, per-store stats | Medium | `AdminDashboard.tsx` is currently an empty stub. Needed for ongoing monitoring. |
| 3.3 | **Category filter in FilterBar** — dropdown populated from `category_path` values | Small | Complements Phase 2.2 category browsing. |
| 3.4 | **"Why this result?" tooltip** — use Gemini to explain similarity | Medium | Builds user trust for vector-matched results that look unexpected. |
| 3.5 | **Mobile RTL testing + fixes** | Small | Hebrew RTL on mobile has known layout edge cases in Tailwind. |
| 3.6 | **Empty state improvements** — suggest alternative queries on 0 results | Small | Current empty state just says "לא נמצאו תוצאות". Could suggest related categories or popular searches. |

---

### Phase 4 — Production Deployment
**Goal:** Deploy publicly, make it discoverable, handle real traffic.

| # | Task | Effort | Why |
|---|---|---|---|
| 4.1 | **Deploy frontend to AWS S3 + CloudFront** | Medium | See `ai-docs/aws-spa-deployment-guide.md`. Static SPA deployment. |
| 4.2 | **Deploy FastAPI to EC2 / ECS** | Medium | Containerize with Docker, deploy behind ALB. |
| 4.3 | **SSL + custom domain** | Small | Required for public launch. |
| 4.4 | **SEO / LLMO optimization** | Medium | See `ai-docs/seo-llmo-guide.md`. Makes the site discoverable via Google and AI assistants. |
| 4.5 | **Rate limiting + API auth** | Small | Prevent abuse of the `/search` endpoint. |
| 4.6 | **Monitoring + alerting** | Small | Basic uptime + error rate monitoring. Alert on scraper failures. |
| 4.7 | **User auth + saved searches** | Large | Nice-to-have for v2. Requires auth provider (Auth0 / Cognito). |

---

### Recommended Execution Order

```
Week 1:  1.6 → 1.2 → 1.3 → 1.4        (quick data quality wins, each <1 day)
Week 2:  1.1 (Celery scheduler)          (medium, most impactful for freshness)
Week 3:  2.1 (Redis cache) → 2.4 → 2.3  (search speed + filter improvements)
Week 4:  1.5 (deduplication)             (large, needs dedicated focus)
Week 5:  2.2 (category browsing)         (backend + frontend)
Week 6:  3.1 → 3.5 → 3.3 → 3.6         (UI polish sprint)
Week 7:  3.2 (AdminDashboard)            (monitoring/ops)
Week 8+: Phase 4 (deployment)
```

### Current Blockers
- **Deduplication (1.5)** — `normalization/deduplication.py` exists but is not wired into the ingestion pipeline. Needs a script that runs post-scrape, clusters near-duplicate products by embedding cosine similarity, picks canonical master, merges `store_products` rows.
- **Celery (1.1)** — `scraper/scheduler.py` skeleton exists. Needs task definitions for each scraper type and a Redis broker.
- **Google Maps geocoding (1.2)** — Requires a Google Maps API key added to `.env` as `GOOGLE_MAPS_API_KEY` and a small update to `db/geocode_stores.py` to call the Places/Geocoding API instead of Nominatim.

---

## How to Resume Work

```bash
cd /path/to/FindMe
source .venv/bin/activate

# Start API
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Start frontend
cd frontend && npm run dev

# Monitor scraper retry (still running as of 2026-04-02)
tail -f /tmp/scraper_retry.log | grep "Store\|Done\|inserted"

# Check DB stats
python -c "
import asyncio, asyncpg, os
from dotenv import load_dotenv; load_dotenv()
async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL','').replace('+asyncpg',''))
    r = await conn.fetchrow('SELECT COUNT(*) as products, COUNT(embedding_vector) as embedded FROM products')
    print(r)
    await conn.close()
asyncio.run(main())
"

# Re-embed any products that failed (300 failed in the last run)
python -m db.embed_products

# Geocode remaining stores with Google Maps API (Nominatim can't handle Israeli mall addresses)
# python -m db.geocode_stores  # only if switching to Google Maps API
```

---

## What Changed This Session (2026-04-02)

| Change | Details |
|---|---|
| **99% embedding coverage** | Upgraded Gemini to paid tier (1,500 RPM). Ran full embed pipeline: 132,887 products embedded in ~2-3 hours. Only 902 products remain unembedded (23 CrypTech + ~879 other). |
| **Pagination** | `page`/`page_size` in `SearchFilters`; backend collects 200 candidates, slices to page; frontend shows Previous/Next + "עמוד X מתוך Y" |
| **Brand filter** | Text input in `FilterBar.tsx`; case-insensitive substring match in search route |
| **Scraper retry** | Reset 59 failed + 31 pending → `skipped`; sitemap scraper running. Already recovered 8 stores (`done` count: 200→208) |
| **Geocoding attempted** | Nominatim found 0 new stores; confirmed remaining 500 require Google Maps API |
| **Sitemap scraper fixes** | `@graph` JSON-LD (Yoast SEO), all product sitemaps (not just first), `ParserRejectedMarkup` caught |
| **Frontend type fix** | `SearchResult` → `ProductResult` with nested `StoreInfo`; ResultCard + StoreMap updated |

---

## File Map

```
FindMe/
├── api/
│   ├── main.py              — FastAPI app, CORS, /health
│   ├── schemas.py           — Pydantic models (ProductResult, StoreInfo, SearchResponse, etc.)
│   ├── dependencies.py      — DB session, Gemini client, Settings
│   └── routes/
│       ├── search.py        — POST /search: hybrid ILIKE + pgvector search, pagination, brand filter
│       └── stores.py        — GET /stores: paginated store list
├── scraper/
│   ├── buyme_store_scraper.py      — Playwright scraper for buyme.co.il store list
│   ├── shopify_product_scraper.py  — Shopify /products.json scraper
│   ├── sitemap_scraper.py          — WordPress/WooCommerce sitemap + JSON-LD scraper
│   ├── woocommerce_product_scraper.py — WC REST API (mostly 401 on IL stores)
│   └── scheduler.py                — Celery task skeleton (not wired)
├── db/
│   ├── models.py            — SQLAlchemy ORM: Store, Product, StoreProduct, ScrapeRun
│   ├── embed_products.py    — Gemini embedding pipeline (paid tier, --store-id flag)
│   ├── geocode_stores.py    — Nominatim geocoding for store lat/lng
│   └── migrations/          — Alembic: 0001 init, 0002 unique constraint, 0003 vector 768-dim
├── normalization/
│   ├── name_normalizer.py   — Claude: canonical product names (HE+EN)
│   ├── category_classifier.py — Claude: unified taxonomy
│   ├── spec_extractor.py    — Claude: brand/model/color/size
│   └── deduplication.py     — Embedding-based dedup engine (NOT wired into pipeline)
└── frontend/src/
    ├── App.tsx              — Main layout, state, search flow, pagination
    ├── api.ts               — POST /search fetch wrapper
    ├── types.ts             — TypeScript: ProductResult, StoreInfo, SearchFilters, etc.
    └── components/
        ├── SearchBox.tsx    — Search input
        ├── FilterBar.tsx    — online_only, brand, max_price, city filters
        ├── ResultCard.tsx   — Product card: name, brand, price, availability, store
        ├── StoreMap.tsx     — Leaflet map (shows geocoded results)
        └── AdminDashboard.tsx — STUB, not implemented
```

## Agent Status — 2026-04-02

| Agent | Task | Status | Notes |
|-------|------|--------|-------|
| DB Agent | voucher_network migration | ✅ Done | Column added, index created, 1226 stores tagged buyme |
| API Agent | POST /api/chat | ✅ Done | Intent parser + response composer implemented |
| Frontend Agent | ChatInterface.tsx | ✅ Done | Chat tab added, GPS inline prompt, results rendering |
| Test Agent | tests/api/test_chat.py | ✅ Done | 6 tests passing |

## Phase 4 Integration Test Results — 2026-04-02

| # | Query | Intent | Results | Status |
|---|-------|--------|---------|--------|
| 1 | אוזניות של סוני בבת ים | product_search | 10 | ✅ |
| 2 | תמצא מסעדות באילת | store_search | 1 | ✅ |
| 3 | חנויות בגדים, מכנסיים לחתונה, תקציב 200 ש״ח + GPS(TLV) | product_search | 10 | ✅ |
| 4 | מה אפשר לקנות ב-BuyMe? | help | — | ✅ |
| 5 | תמצא לי אוזניות סוני | product_search | 10 | ✅ |

**Post-sprint fixes applied:**
- `gemini-2.0-flash` → `gemini-2.5-flash` (model deprecated)
- Intent parser JSON extraction: regex `{.*?}` + `max_tokens` 256→512 (handles partial fences)
- `search_text` now includes both `product_query` and `brand` to avoid Hebrew↔English brand filter mismatch
- City-filter fallback: if city filter yields 0 results, retry without city filter
