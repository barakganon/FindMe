# Story 3.1 — Permanent Installment-Price Fix

> Drafted 2026-07-11 (autonomous, pre-launch). Data-quality phase 2, gated by Epic 6
> analytics per the epic-6 plan ("order it by what the 6.5 analytics actually
> surface, not by guess") — this doc specs the fix so it's ready to prioritize, not
> a directive to start immediately.

## Background — what's already done (reversible cleanup, not a permanent fix)

Three commits so far, in order:

1. **`c078834` feat(data): reversible price cleanup + rule-based category backfill
   (Epic 3)** — added `normalization/price_cleanup.py`. Nulled 645 bogus prices
   (113 × ₪999,999 "price on request" sentinel + 532 non-positive) via
   `--dry-run`/`--apply`/`--restore`, quarantining originals to JSON so the change
   is reversible. Explicitly did **not** touch the ambiguous sub-₪10 cluster,
   noting "some are legit cheap items; some are the installment bug — needs a
   per-store rule, handled separately" (see `price_cleanup.py:8-9`).
2. **`be6766e` fix(scraper): reject ≤0 and ₪999999 sentinel prices at ingest** —
   after a full Shopify re-scrape re-introduced the same bogus prices, made
   `_parse_price` in `scraper/shopify_product_scraper.py` return `None` for
   non-positive and the ₪999999 sentinel at ingest time, so re-scrapes stop
   reintroducing them. This is the durable fix for the sentinel/non-positive
   classes — **already permanent**, not this story's job to redo.
3. **`5822a43` fix(scraper): sentinel/non-positive price rejection in sitemap
   scraper too** — mirrored the same ingest-time guard into
   `scraper/sitemap_scraper.py::_extract_price_from_offers` for the JSON-LD path.

**What remains unsolved:** the sub-₪10 "intra-product outlier" cluster.
`price_cleanup.py` added a *second*, separate predicate for this
(`--outliers` flag, `_OUTLIER_SELECT` in `price_cleanup.py:46-54`): a sub-₪10
listing where the same canonical `product_id` has another store listing
`>= 20x` higher (e.g. a diamond ring at ₪1.3 vs ₪199 elsewhere) — the signature
of an installment-plan price (e.g. "12 payments of ₪X") being scraped as the
full price. This predicate is **reversible cleanup only** (nulls + quarantine
JSON), run manually via `--apply --outliers`. There is no ingest-time guard for
it yet — unlike the sentinel/non-positive fix, a re-scrape will reintroduce these.

## Why this is genuinely harder than the sentinel fix

The sentinel/non-positive fix was a pure value check (`price <= 0 or price ==
999999`) — no cross-referencing needed, safe to apply at parse time per-item.
The installment-price outlier is **relational**: you can't tell a price is wrong
by looking at it alone, only by comparing it to other listings of the *same*
product. That comparison requires either:
- deferring the check to post-ingest (current approach — run `price_cleanup.py
  --outliers` periodically), or
- doing the cross-reference at scrape time, which means the scraper needs to know
  about sibling listings across stores for the same product — a bigger change to
  the scraper's write path (it currently writes one `store_products` row at a
  time, not product-aware).

There's also a genuine ambiguity `price_cleanup.py` already flags: legitimately
cheap items (embroidery thread, candy) look identical in isolation to a
mis-scraped installment price. The `>= 20x` sibling-price heuristic is a
reasonable proxy but not proof — a store could legitimately sell the exact same
item 20x cheaper via a clearance/bundle deal.

## Scope (in)

- Decide the permanent home for the outlier check: most likely a **post-ingest
  Celery periodic task** (not APScheduler/cron, per CLAUDE.md) that runs the
  existing `_OUTLIER_SELECT` logic after each scrape batch completes, rather than
  requiring a human to remember to run `--apply --outliers` manually.
- Reuse `normalization/price_cleanup.py`'s existing outlier predicate and
  quarantine/restore mechanism as-is — don't rewrite the SQL, wire it into the
  scrape pipeline's completion hook.
- Add a regression test asserting a newly-scraped sub-₪10 sibling-outlier row
  gets nulled without manual intervention (mirrors the `test_parse_price.py`
  pattern from `be6766e`/`5822a43`).
- Re-verify the `20x` multiple threshold against real data once 6.5 analytics
  give a sense of scrape volume/frequency in prod — the threshold was chosen
  from Epic 3's initial audit, not from live traffic patterns.

## Scope (out)

- Any change to `_parse_price` itself — the per-item sentinel/non-positive checks
  are already permanent and correct; don't touch them.
- Solving the ambiguous case with certainty (legit clearance price vs installment
  bug) — the 20x heuristic is a pragmatic proxy, not a target for this story to
  perfect. Flag remaining false positives/negatives for a future manual review
  pass instead of over-engineering the heuristic now.
- Product-aware scraper rewrite (making the scraper compare across stores at
  write time) — bigger change, not justified unless the periodic-task approach
  proves too laggy in practice.

## Dependencies

- Soft dependency: Epic 6.5 first-week analytics (`2-2-first-week-analytics.md`)
  should confirm this is actually worth prioritizing over `3-2`/`3-3` before
  starting — per the epic-6 plan's explicit sequencing instruction.
- No hard blocker — `normalization/price_cleanup.py --apply --outliers` can be
  run manually today if an urgent case surfaces before this story is scheduled.

## Acceptance criteria

1. Sub-₪10 intra-product outliers are nulled automatically after each scrape run,
   without a human running `price_cleanup.py --outliers` by hand.
2. The fix reuses the existing quarantine/restore mechanism — no data loss, still
   reversible.
3. A test exists proving a freshly-ingested outlier gets caught (not just the
   historical cleanup pass).
4. The `20x` threshold is either reaffirmed or adjusted with a one-line rationale
   tied to real prod data, not left as an unexamined magic number.
