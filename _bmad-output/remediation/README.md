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

## Not yet done (carry-forward)
- Sub-₪10 installment-bug investigation (per-store rule).
- LLM category pass on the remaining 9,602 NULLs (needs `GEMINI_API_KEY`).
- Image backfill (99% missing) + fix `last_price_change_at` freshness tracking.
- **Re-embed** any rows whose category changed, IF category feeds the embedding text
  (verify in `db/embed_products.py` before relying on category in semantic search).
