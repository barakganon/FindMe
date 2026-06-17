# Data Remediation Log

Reversible catalog fixes from the 2026-06-16 audit (`../data-audit-v1.md`).
The raw `*.json` reversibility dumps are **gitignored** (one is ~4 MB) — they live
locally next to the DB they reverse. The scripts that produced them are in
`normalization/` and are deterministic/re-runnable.

## 2026-06-17 — Price cleanup (`normalization/price_cleanup.py`)
- Nulled **645** unambiguously-bogus `store_products.price` values:
  113 × `₪999,999` sentinel + 532 non-positive (≤ 0).
- Originals saved to `price-quarantine-20260617T040230Z.json` (54 KB).
- Verify: sentinel=0, non-positive=0 after run.
- Restore: `python -m normalization.price_cleanup --restore _bmad-output/remediation/price-quarantine-20260617T040230Z.json`
- Did NOT touch the ambiguous sub-₪10 cluster (needs a per-store installment rule).

## 2026-06-17 — Category backfill (`normalization/category_backfill.py`)
- Backfilled **34,791** missing `products.category_path` via keyword rules on
  `canonical_name` + coarse store `buyme_category` fallback.
- Null/empty category_path: **32.6% → 7.1%** (44,393 → 9,602).
- The remaining **9,602** (generic "other"/unknown store + no keyword) were left
  NULL on purpose — they are the precise worklist for a later LLM classification pass.
- Backfilled pairs saved to `category-backfill-20260617T040509Z.json` (3.9 MB).
- Restore: `python -m normalization.category_backfill --restore _bmad-output/remediation/category-backfill-20260617T040509Z.json`

## 2026-06-17 — Sub-₪10 price outliers (`normalization/price_cleanup.py --outliers`)
- Investigation finding: the sub-₪10 cluster is **mostly legitimate** (embroidery
  thread ₪3.5, candy ₪3, lace underwear ₪4.9) — **NOT** a widespread installment bug.
  A blanket fix would destroy good data.
- The real errors are **intra-product outliers**: a sub-₪10 price where the *same*
  canonical product is listed ≥20× higher elsewhere (e.g. a 1-carat diamond ring at
  ₪1.3 vs ₪199). Nulled **50** such rows; reversible (`price-outliers-*.json`).

## 2026-06-17 — Store city backfill (`normalization/city_backfill.py`)
- Backfilled **20** store cities from the trailing comma-segment of `address`
  (טירת כרמל, בני ברק, חיפה, …). Null-city stores **182 → 162**. Reversible.
- The remaining 162 have no address (online/addressless) → city legitimately null.

## Investigated, deliberately NOT auto-fixed
- **Brand (3,386 null):** nulls cluster in **multi-brand** electronics retailers
  (Alltech 968, ליאור 401) where the store name is NOT the product brand. Auto-assigning
  would inject wrong data — worse than null. Needs name-level extraction (LLM/regex), deferred.
- **Price freshness:** `last_price_change_at` null-for-all is **correct** (it's set only
  when a price *changes* between scrapes). The real signal is `updated_at`, and it shows
  the **entire catalog is ~2.5 months stale** (last scraped 2026-03-25→04-07; 1,229/1,236
  stores >30d). **Not a code bug — the scrapers simply haven't run.** Re-running them is the
  fix (also populates images + price-change history going forward). Operational, needs
  Celery/Playwright runtime.

## 2026-06-17 — Full Shopify re-scrape (`scraper.shopify_product_scraper`)
- Ran the full product scrape (1,201 stores; 215 Shopify catalogs refreshed, 986
  non-Shopify skipped — those need the sitemap/Playwright scrapers).
- **+42,207 new products, 157,774 updated.** Catalog: 135,988 → **178,201 products**;
  199,981 store_products updated today. Pipeline confirmed healthy after ~2.5mo idle.
- **The scrape re-introduced bogus prices** (112 sentinels + 3,599 ≤0) and ~18k new
  uncategorized products — expected, since upsert ingests whatever the store returns.
  Re-ran the cleanup scripts (idempotent): prices clean again (0/0); category re-backfilled
  (null 32.6% → **5.5%**).
- **Durable fix:** `_parse_price` in `scraper/shopify_product_scraper.py` now rejects
  `≤0` and the `≥999,999` sentinel at ingest, so future scrapes won't re-introduce them
  (+4 tests, `tests/test_parse_price.py`). The negative/sentinel cleanup should no longer
  be needed post-scrape; the category re-backfill still should run after each scrape.

## ⛔ New blocker after the scrape
- **43,238 products (24.3%) now have no embedding** (the 42k newly-scraped ones). They
  won't surface in semantic search until embedded. Embedding needs `GEMINI_API_KEY`
  (`python -m db.embed_products`). **Handoff item.**

## 2026-06-17 — Non-Shopify scrape attempt: DEAD END with current tooling
Tried to refresh the **986 non-Shopify `skipped` stores**. Stopped after diagnosis — it
was producing ~0 products while making thousands of requests at partner sites:
- **Sitemap + JSON-LD** (`scraper.sitemap_scraper`): ran ~17 stores. Every one returned
  `pages_with_json_ld=0` — even CHEZ VIVIE (2,000 pages fetched → 0 products) and
  IT MOMZ (589 → 0). The scraper's own HTTP 200 responses contain no JSON-LD Product
  schema. At ~1 store/min this would have taken **~16 hours for ~0 products**. Killed.
- **WooCommerce Store API** (`/wp-json/wc/store/products`): `403` (bot-protected, e.g.
  Cloudflare) or `404` (not exposed) on the stores tested.
- **Direct page fetch**: `403` bot-challenge.

**Conclusion:** these stores are bot-protected and/or expose no machine-readable product
data — they cannot be reliably product-scraped with the current sitemap/Woo/JSON-LD
strategies. **Recommendation:** treat them as *store-only* listings (no product catalog)
for now; a per-store custom scraper or a paid scraping/anti-bot service would be required
to extract their products. Do NOT blindly run the Playwright `per_store_scraper` across
all 986 — it is far heavier and headless browsers are typically blocked by the same
anti-bot protection. (Code hardening from this session — the price ingest-guards in both
scrapers — still stands and is valuable for the Shopify path.)

## Not yet done (carry-forward)
- **Re-run scrapers** (fixes staleness + 99% missing images + future price-change tracking).
- LLM category pass on the remaining 9,602 NULLs (needs `GEMINI_API_KEY`).
- LLM/regex brand extraction from product names.
- **Re-embed** any rows whose category changed, IF category feeds the embedding text
  (verify in `db/embed_products.py` before relying on category in semantic search).
