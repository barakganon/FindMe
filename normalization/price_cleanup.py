"""
normalization/price_cleanup.py — reversible cleanup of bogus store_product prices.

Targets two unambiguous classes of bad price (see _bmad-output/data-audit-v1.md):
  * the ₪999,999 "price on request" sentinel (mostly ENERGYM), and
  * non-positive prices (≤ 0) from scraper parse errors.

It does NOT touch the ambiguous sub-₪10 cluster (some are legit cheap items; some
are the installment bug) — that needs a per-store rule, handled separately.

Reversible: before nulling anything, every affected row's (id, original price) is
written to a timestamped JSON quarantine file under _bmad-output/remediation/.
`--restore <file>` re-applies those originals.

Usage:
    python -m normalization.price_cleanup --dry-run     # report only, no writes
    python -m normalization.price_cleanup --apply       # quarantine + null
    python -m normalization.price_cleanup --restore <quarantine.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.dependencies import _normalize_async_db_url, get_settings

_QUARANTINE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "_bmad-output", "remediation"
)

# Bogus-price predicate: the ₪999,999 sentinel OR non-positive prices.
_TARGET_WHERE = "price IS NOT NULL AND (price = 999999 OR price <= 0)"

# Outlier predicate: a sub-₪10 price where the SAME canonical product has another
# listing >= 20x higher (e.g. a 1-carat diamond ring at ₪1.3 vs ₪199 elsewhere).
# Legit cheap items (embroidery thread, candy) have no high-priced sibling, so they
# are excluded — this only catches intra-product price errors, not cheap goods.
_OUTLIER_MULTIPLE = 20
_OUTLIER_SELECT = f"""
  WITH prod AS (
    SELECT product_id, MAX(price) AS maxp
    FROM store_products WHERE price > 0 GROUP BY product_id
  )
  SELECT sp.id, sp.price FROM store_products sp
  JOIN prod ON prod.product_id = sp.product_id
  WHERE sp.price > 0 AND sp.price < 10 AND prod.maxp >= sp.price * {_OUTLIER_MULTIPLE}
"""


def _engine():
    return create_async_engine(_normalize_async_db_url(get_settings().database_url))


async def _select_targets(conn, outliers: bool = False):
    sql = _OUTLIER_SELECT if outliers else (
        f"SELECT id, price FROM store_products WHERE {_TARGET_WHERE} ORDER BY price"
    )
    rows = await conn.execute(text(sql))
    return [{"id": str(r.id), "price": float(r.price)} for r in rows]


async def dry_run(outliers: bool = False) -> None:
    eng = _engine()
    async with eng.connect() as conn:
        targets = await _select_targets(conn, outliers)
    await eng.dispose()
    if outliers:
        print(f"[dry-run] would quarantine + null {len(targets)} sub-₪10 intra-product "
              f"outliers (same product listed >= {_OUTLIER_MULTIPLE}x higher). No writes made.")
    else:
        sentinel = sum(1 for t in targets if t["price"] == 999999)
        nonpos = sum(1 for t in targets if t["price"] <= 0)
        print(f"[dry-run] would quarantine + null {len(targets)} rows "
              f"({sentinel} × ₪999,999 sentinel, {nonpos} non-positive). No writes made.")


async def apply(outliers: bool = False) -> None:
    eng = _engine()
    async with eng.begin() as conn:
        targets = await _select_targets(conn, outliers)
        if not targets:
            print("Nothing to clean — 0 matching rows found.")
            await eng.dispose()
            return
        os.makedirs(_QUARANTINE_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prefix = "price-outliers" if outliers else "price-quarantine"
        qfile = os.path.join(_QUARANTINE_DIR, f"{prefix}-{stamp}.json")
        with open(qfile, "w", encoding="utf-8") as fh:
            json.dump({"created_utc": stamp, "predicate": _TARGET_WHERE, "rows": targets},
                      fh, ensure_ascii=False, indent=2)
        ids = [t["id"] for t in targets]
        await conn.execute(
            text("UPDATE store_products SET price = NULL WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
    await eng.dispose()
    print(f"Quarantined {len(targets)} originals → {os.path.relpath(qfile)} and set their price = NULL.")
    print("Restore with: python -m normalization.price_cleanup --restore " + os.path.relpath(qfile))


async def restore(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data["rows"]
    eng = _engine()
    async with eng.begin() as conn:
        for row in rows:
            await conn.execute(
                text("UPDATE store_products SET price = :p WHERE id = :id"),
                {"p": row["price"], "id": row["id"]},
            )
    await eng.dispose()
    print(f"Restored {len(rows)} original prices from {path}.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Reversible bogus-price cleanup.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--restore", metavar="QUARANTINE_JSON")
    ap.add_argument("--outliers", action="store_true",
                    help="target sub-₪10 intra-product price outliers instead of sentinels/non-positive")
    args = ap.parse_args()
    if args.dry_run:
        asyncio.run(dry_run(args.outliers))
    elif args.apply:
        asyncio.run(apply(args.outliers))
    else:
        asyncio.run(restore(args.restore))


if __name__ == "__main__":
    main()
