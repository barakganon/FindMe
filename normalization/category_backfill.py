"""
normalization/category_backfill.py — rule-based backfill of missing category_path.

~32% of products have no category_path (see _bmad-output/data-audit-v1.md), almost
all because certain store scrapers never set it. This fills the gap deterministically
(no LLM, no cost) using two signals, in priority order:

  1. Hebrew/English keyword rules on `canonical_name` (most specific → a real leaf), then
  2. the product's store `buyme_category` as a coarse fallback.

It only writes rows that are currently NULL/empty — never overwrites a scraped category.
Lower-precision than an LLM pass; intended as the free first layer (an LLM pass can later
refine whatever this leaves at the coarse fallback). Reversible: backfilled (id, value)
pairs are written to a timestamped JSON under _bmad-output/remediation/; `--restore`
sets those rows back to NULL.

Usage:
    python -m normalization.category_backfill --dry-run
    python -m normalization.category_backfill --apply
    python -m normalization.category_backfill --restore <backfill.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.dependencies import _normalize_async_db_url, get_settings

_DIR = os.path.join(os.path.dirname(__file__), "..", "_bmad-output", "remediation")

# Keyword → category_path. Checked in order; first hit wins. Substring match on a
# lowercased canonical_name. Hebrew has no case but lower() is harmless.
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("צמיד", "שרשרת", "טבעת", "עגיל", "תליון", "חישוק", "necklace", "bracelet", "ring", "earring"), "אופנה > תכשיטים"),
    (("נעל", "סניקרס", "מגף", "כפכף", "סנדל", "sneaker", "boot", "sandal", "shoe"), "אופנה > הנעלה"),
    (("חולצה", "מכנס", "שמלה", "ג'ינס", "חצאית", "מעיל", "סווטשירט", "גופיי", "תחתון", "ביגוד", "בגד", "shirt", "pants", "dress", "jacket"), "אופנה > ביגוד"),
    (("תיק", "ארנק", "קלאץ", "bag", "wallet", "backpack"), "אופנה > תיקים"),
    (("איפור", "קרם", "בושם", "שמפו", "סרום", "מסכת פנים", "ליפסטיק", "מייקאפ", "makeup", "perfume", "serum"), "יופי וטיפוח"),
    (("כרית", "מגבת", "סיר", "צלחת", "כוס", "מצעים", "שמיכה", "וילון", "towel", "pillow", "bedding"), "בית ומטבח"),
    (("בובה", "פאזל", "משחק", "צעצוע", "toy", "puzzle", "lego", "לגו"), "צעצועים ומשחקים"),
    (("תינוק", "בגדי גוף", "מארז בגדי", "baby", "newborn", "nb "), "תינוקות וילדים"),
    (("שוקולד", "ממתק", "קפה", "יין", "מארז מתוק", "chocolate", "wine", "coffee"), "מזון ומשקאות"),
    (("מחשב", "אוזניות", "מטען", "כבל", "מקלדת", "עכבר", "usb", "computer", "headphone", "charger"), "אלקטרוניקה"),
]

# Store-level buyme_category → coarse fallback category_path. Deliberately has NO
# entry for "other"/unknown: products with no keyword hit and a generic store
# category are left NULL so a later LLM pass can target exactly the rows that
# still have no real signal (rather than masking them with a useless label).
_STORE_FALLBACK = {
    "restaurant": "מסעדות ובתי קפה",
    "spa": "ספא ויופי",
    "leisure": "פנאי ובילוי",
    "retail": "קמעונאות כללית",
}


def _engine():
    return create_async_engine(_normalize_async_db_url(get_settings().database_url))


def _classify(name: str | None, store_cat: str | None) -> str | None:
    n = (name or "").lower()
    for keywords, path in _KEYWORD_RULES:
        if any(k in n for k in keywords):
            return path
    if store_cat:
        return _STORE_FALLBACK.get(store_cat.lower())  # None for "other"/unknown
    return None


async def _collect(conn):
    rows = await conn.execute(text("""
        SELECT p.id, p.canonical_name,
               (SELECT s.buyme_category FROM store_products sp
                  JOIN stores s ON s.id = sp.store_id
                 WHERE sp.product_id = p.id LIMIT 1) AS store_cat
        FROM products p
        WHERE p.category_path IS NULL OR p.category_path = ''
    """))
    out = []
    for r in rows:
        cat = _classify(r.canonical_name, r.store_cat)
        if cat:
            out.append({"id": str(r.id), "category_path": cat})
    return out


async def dry_run() -> None:
    eng = _engine()
    async with eng.connect() as conn:
        assigns = await _collect(conn)
    await eng.dispose()
    dist = Counter(a["category_path"] for a in assigns)
    print(f"[dry-run] would backfill {len(assigns):,} products. Distribution:")
    for cat, n in dist.most_common():
        print(f"  {n:>7,}  {cat}")


async def apply() -> None:
    eng = _engine()
    async with eng.begin() as conn:
        assigns = await _collect(conn)
        if not assigns:
            print("Nothing to backfill.")
            await eng.dispose()
            return
        os.makedirs(_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bfile = os.path.join(_DIR, f"category-backfill-{stamp}.json")
        with open(bfile, "w", encoding="utf-8") as fh:
            json.dump({"created_utc": stamp, "source": "rule_backfill_v1", "rows": assigns},
                      fh, ensure_ascii=False, indent=2)
        # Group by category to do one UPDATE per distinct value.
        by_cat: dict[str, list[str]] = {}
        for a in assigns:
            by_cat.setdefault(a["category_path"], []).append(a["id"])
        for cat, ids in by_cat.items():
            await conn.execute(
                text("UPDATE products SET category_path = :c WHERE id = ANY(:ids)"),
                {"c": cat, "ids": ids},
            )
    await eng.dispose()
    print(f"Backfilled {len(assigns):,} categories → recorded in {os.path.relpath(bfile)}.")
    print("Restore with: python -m normalization.category_backfill --restore " + os.path.relpath(bfile))


async def restore(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    ids = [r["id"] for r in data["rows"]]
    eng = _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE products SET category_path = NULL WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
    await eng.dispose()
    print(f"Reset {len(ids):,} category_path values to NULL from {path}.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Rule-based category_path backfill.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--restore", metavar="BACKFILL_JSON")
    args = ap.parse_args()
    if args.dry_run:
        asyncio.run(dry_run())
    elif args.apply:
        asyncio.run(apply())
    else:
        asyncio.run(restore(args.restore))


if __name__ == "__main__":
    main()
