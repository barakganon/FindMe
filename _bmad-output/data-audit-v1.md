# FindMe — Data Audit v1 (run 2026-06-16)

> First real catalog audit, run read-only against the local Postgres
> (`buyme_search`). Supersedes the placeholder figures in CLAUDE.md. Numbers are
> exact counts as of the run date. This is the P0 "data truthfulness" artifact the
> v2 sprint plan called for but that was never produced during Epic 5.

## Scale

| Table | Count |
|-------|------:|
| products | 135,988 |
| store_products (price/availability rows) | 181,517 |
| stores | 1,236 |
| embedded products | 134,963 (99.2%) |

## P0 — Price truthfulness ❌ FAILS the "<0.5% suspect" gate

`store_products.price` quality:

| Issue | Count | % of rows | Verdict |
|-------|------:|----------:|---------|
| NULL price | 3,898 | 2.15% | missing |
| ≤ 0 (negative/zero) | 532 | 0.29% | **bogus — parse error** |
| `₪999,999` sentinel | 113 | 0.06% | **bogus — "no price" sentinel** |
| other ≥ ₪100k | 5 | <0.01% | suspect (verify) |
| 0 < price < ₪10 | 1,644 | 0.91% | **suspect — installment/parse** |
| min positive | ₪0.01 | — | bogus |
| max | ₪999,999 | — | bogus |
| avg (positive) | ₪1,285.62 | — | plausible |

**Suspect total ≈ 2,294 rows (~1.3%)** → fails the <0.5% target.

### Root causes (concentration tells the story)
- **`₪999,999`: 113 of 116 are in ENERGYM (spa).** Classic scraper sentinel for
  "price on request" leaking into the price column. **Fix: null these out.**
- **Negative/zero prices** cluster in FOX Home (80), TAKEANAP (62), שלומית אופיר (60),
  Lilush box (40), CrypTech (14) — per-scraper parse bugs. **Fix: null + flag for re-scrape.**
- **< ₪10**: תחביבן/leisure (512) and SWEETWEET/restaurant (117) dominate. Some are
  genuinely cheap (stickers, single menu items); some are likely the **installment
  bug** (monthly payment scraped as full price). Needs per-store rule, not a blanket fix.

## P1 — Category accuracy ❌ 32.6% missing

- **44,393 products (32.6%) have NULL/empty `category_path`.**
- It is **systematic per store/scraper**, not random — entire catalogs are uncategorized:
  CrypTech 7,846/7,846 (100%), Femina 1,769/1,769 (100%), STEVE MADDEN 2,891/2,914 (99%),
  טבע נאות 1,492/1,492 (100%), נעלי נימרוד 1,245/1,246 (~100%), SWEETWEET 1,175/1,176.
- The 67% that are categorized span **3,260 distinct `category_path` values** — a rich
  taxonomy exists to map into.
- Products carry `canonical_name` + `brand`, and the store carries a coarse
  `buyme_category` (retail/spa/restaurant/…) → **enrichable** without re-scraping.

## P1 — Brand attribution

- 3,386 products (2.5%) NULL/empty brand. Within target-ish; low priority vs category.

## P1 — Store geo

- 182 stores (14.7%) NULL `city` → hurts location search for those stores.

## P2 — Image hygiene ❌ 99% missing

- 179,774 / 181,517 store_products (99.0%) have no `image_url`. Known (only Femina's
  ~1,743 done). Big UX gap for the results tray, but not correctness-critical.

## ❌ Price-freshness tracking is broken

- `last_price_change_at` is NULL for **all 181,517 rows**; `price_changes` is unused.
- Cannot measure staleness. The scheduler's `detect_price_changes` task either never
  runs or never writes. **Investigate before trusting any "price dropped" feature.**

## Ship-gate verdict

The v2 ship-gate ("all P0 pass") **does not pass**: price truthfulness is ~1.3% suspect
(target <0.5%). Remediation is tractable and mostly mechanical.

## Recommended remediation (phased)

**Phase 1 — safe, deterministic price cleanup (no LLM, reversible):**
1. NULL out the `₪999,999` sentinels (≈113) and ≤0 prices (≈532); record originals in
   `price_changes` or a quarantine column so it's reversible. Flag those store_products
   for re-scrape.
2. Investigate the < ₪10 clusters per store; apply a per-store rule only where the
   installment pattern is confirmed (don't blanket-delete legit cheap items).

**Phase 2 — category enrichment (choose an approach):**
- (a) **Free/rule-based:** backfill `category_path` from the store's `buyme_category`
  as a coarse fallback + keyword rules on `canonical_name`. Zero cost, lower precision.
- (b) **LLM classification:** classify each of the 44k null-category products from
  `canonical_name`+`brand` into the existing 3,260-value taxonomy via Gemini flash.
  Higher precision; needs `GEMINI_API_KEY` + a one-time batch cost (est. low single-digit
  USD at flash pricing — verify) + re-embed of changed rows.

**Phase 3 — images + freshness:** re-run scrapers to populate `image_url`; fix
`detect_price_changes` so `last_price_change_at` populates going forward.

## How this maps to the backlog
This is **Epic 3 (Data Quality Phase 2)**: 3-1 installment/price fix, 3-2 thin/empty
categories, 3-3 store enrichment. The audit gives the order: **prices → categories →
images/freshness.**

---

## ✅ Remediation applied (2026-06-17)

Reversible; see `remediation/README.md` for restore commands.

| Fix | Result | Tool |
|-----|--------|------|
| **Bogus prices** | 645 nulled (113 × ₪999,999 sentinel + 532 ≤0). Sentinel & non-positive now **0**. | `normalization/price_cleanup.py` |
| **Missing categories** | 34,791 backfilled (keyword + store fallback). Null category **32.6% → 7.1%**. | `normalization/category_backfill.py` |

**Still open:** sub-₪10 installment investigation; LLM category pass on the remaining
9,602 NULLs (needs `GEMINI_API_KEY`); image backfill; freshness-tracking fix; re-embed
if category feeds embedding text.
