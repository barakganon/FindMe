"""scripts/backfill_brands.py — Extract brand from canonical_name for products with NULL/empty brand.

Strategy: regex match the top-20 Israeli consumer brands against
`products.canonical_name`. If a match is found AND the product currently has
`brand IS NULL` or `brand = ''`, update it to the canonical brand string.

The regex set is hand-curated. Matching is case-insensitive and supports
both Hebrew and English forms (e.g. "Sony" and "סוני" both map to "Sony").

Idempotent — re-running only updates rows that still have null/empty brand.
Safe to schedule.

Usage:
    .venv/bin/python -m scripts.backfill_brands                # write changes
    .venv/bin/python -m scripts.backfill_brands --dry-run      # print only
    .venv/bin/python -m scripts.backfill_brands --limit 1000   # cap for testing
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# Canonical brand → list of substring patterns that imply this brand.
# Patterns are case-insensitive. Order matters: first match wins.
_BRAND_PATTERNS: dict[str, list[str]] = {
    "Sony": ["sony", "סוני"],
    "Apple": ["apple", "אפל", "iphone", "ipad", "macbook"],
    "Samsung": ["samsung", "סמסונג", "galaxy"],
    "Nike": ["nike", "נייקי"],
    "Adidas": ["adidas", "אדידס"],
    "LG": [r"\blg\b", "אל ג'י"],
    "Bosch": ["bosch", "בוש"],
    "Philips": ["philips", "פיליפס"],
    "Braun": ["braun", "בראון"],
    "Whirlpool": ["whirlpool", "וירפול"],
    "Electrolux": ["electrolux", "אלקטרולוקס"],
    "GE": [r"\bge appliances\b", r"\bge\s+(?:dishwasher|fridge|oven|washer)"],
    "Asus": ["asus", "אסוס"],
    "Lenovo": ["lenovo", "לנובו"],
    "HP": [r"\bhp\b", r"hewlett[\s-]?packard"],
    "Dell": [r"\bdell\b"],
    "Xiaomi": ["xiaomi", "שיאומי", "redmi", "mi band"],
    "Garmin": ["garmin", "גרמין"],
    "Logitech": ["logitech", "לוג'יטק"],
    "JBL": [r"\bjbl\b"],
    "Bose": [r"\bbose\b", "בוז"],
    "Edifier": ["edifier", "אדיפייר"],
    "Lior": ["ליאור"],  # the 727-product gap from QA findings
    "Castro": ["castro", "קסטרו"],
    "Fox": [r"\bfox\b", r"\bfox\s+home\b"],
    "Renuar": ["renuar", "רנואר"],
}


def _compile_patterns() -> list[tuple[str, re.Pattern]]:
    """Compile each brand's union pattern. Returns list of (brand, pattern)."""
    compiled = []
    for brand, patterns in _BRAND_PATTERNS.items():
        # Combine all patterns for this brand with OR
        combined = "|".join(f"(?:{p})" for p in patterns)
        compiled.append((brand, re.compile(combined, re.IGNORECASE)))
    return compiled


_COMPILED = _compile_patterns()


def detect_brand(canonical_name: str | None) -> str | None:
    """Return the canonical brand string for a product name, or None."""
    if not canonical_name:
        return None
    for brand, pattern in _COMPILED:
        if pattern.search(canonical_name):
            return brand
    return None


async def main(dry_run: bool, limit: int | None) -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://barakganon@localhost/buyme_search")
    engine = create_async_engine(db_url)

    print(f"→ Connecting to: {db_url.split('@')[-1]}")
    print(f"  Mode: {'DRY-RUN (no writes)' if dry_run else 'WRITE'}")

    async with engine.connect() as conn:
        # Fetch products with NULL or empty brand
        q = """
            SELECT id, canonical_name
            FROM products
            WHERE (brand IS NULL OR brand = '')
              AND canonical_name IS NOT NULL
        """
        if limit:
            q += f" LIMIT {int(limit)}"
        result = await conn.execute(text(q))
        rows = result.fetchall()

    print(f"  Candidates with NULL/empty brand: {len(rows):,}")

    # Detect brand per row
    updates: list[tuple[str, str]] = []  # (id, brand)
    brand_counts: Counter = Counter()
    for row in rows:
        brand = detect_brand(row[1])
        if brand:
            updates.append((str(row[0]), brand))
            brand_counts[brand] += 1

    print(f"  Detected brand for: {len(updates):,} products")
    print("  Brand distribution:")
    for brand, n in brand_counts.most_common(20):
        print(f"    {brand:<15} {n:>6}")

    if dry_run:
        print("\nDry-run complete — no changes written.")
        await engine.dispose()
        return

    # Batch UPDATE
    print(f"\n→ Writing {len(updates):,} brand updates...")
    async with engine.begin() as conn:
        for i in range(0, len(updates), 500):
            batch = updates[i:i + 500]
            # Build VALUES clause for batched UPDATE via temp table pattern
            for product_id, brand in batch:
                await conn.execute(
                    text("UPDATE products SET brand = :brand WHERE id = CAST(:id AS uuid)"),
                    {"brand": brand, "id": product_id},
                )
            print(f"  ... committed through row {i + len(batch):,}")

    print(f"✓ Done. {len(updates):,} products updated.")
    await engine.dispose()


def cli() -> int:
    parser = argparse.ArgumentParser(description="Backfill products.brand from canonical_name")
    parser.add_argument("--dry-run", action="store_true", help="Print proposed changes without writing")
    parser.add_argument("--limit", type=int, default=None, help="Cap candidates for testing")
    args = parser.parse_args()

    try:
        asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(cli())
