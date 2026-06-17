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

## Not yet done (carry-forward)
- **Re-run scrapers** (fixes staleness + 99% missing images + future price-change tracking).
- LLM category pass on the remaining 9,602 NULLs (needs `GEMINI_API_KEY`).
- LLM/regex brand extraction from product names.
- **Re-embed** any rows whose category changed, IF category feeds the embedding text
  (verify in `db/embed_products.py` before relying on category in semantic search).
