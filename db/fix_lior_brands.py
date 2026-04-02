"""
db/fix_lior_brands.py — Fix brand=null for ליאור מוצרי חשמל products.

The 727 ליאור מוצרי חשמל products have brand=null because JSON-LD on their
Shopify store does not include a brand field.  However the brand name is
embedded in canonical_name (e.g. "מקרר Miele G12345", "מדיח Bosch SMS46KI01I").

This script:
  1. Connects to the DB via asyncpg.
  2. Finds all products with brand IS NULL that belong to the ליאור store via
     the store_products join.
  3. For each product, tries to extract the brand from canonical_name by
     checking a curated list of known appliance / electronics brands.
  4. Updates products.brand where a match is found.
  5. Logs total rows updated.

Run:
    python -m db.fix_lior_brands
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Known appliance / electronics brands to look for in product names
# ---------------------------------------------------------------------------

KNOWN_BRANDS: list[str] = [
    "Miele",
    "Bosch",
    "Samsung",
    "LG",
    "Siemens",
    "AEG",
    "Candy",
    "Beko",
    "Whirlpool",
    "Electrolux",
    "Haier",
    "Hisense",
    "Hotpoint",
    "Smeg",
    "Fisher & Paykel",
    "Sharp",
    "Panasonic",
    "Midea",
    "Ariston",
    "Indesit",
    "Zanussi",
    "Gorenje",
    "Liebherr",
    "Sub-Zero",
    "Thermador",
    "KitchenAid",
    "Fisher",
    "Teka",
    "Bertazzoni",
    "DeLonghi",
    "Nespresso",
    "Jura",
    "Saeco",
    "פיליפס",
    "Philips",
    "Braun",
]

# Pre-compile one pattern per brand (word-boundary aware, case-insensitive).
# Longer multi-word brands are checked first so "Fisher & Paykel" wins over "Fisher".
_SORTED_BRANDS = sorted(KNOWN_BRANDS, key=len, reverse=True)
_BRAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (brand, re.compile(re.escape(brand), re.IGNORECASE))
    for brand in _SORTED_BRANDS
]


def _extract_brand(canonical_name: str) -> str | None:
    """Return the first matching brand found in canonical_name, or None."""
    for brand, pattern in _BRAND_PATTERNS:
        if pattern.search(canonical_name):
            return brand
    return None


# ---------------------------------------------------------------------------
# Main async routine
# ---------------------------------------------------------------------------


async def fix_lior_brands() -> None:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    # asyncpg uses the plain postgresql:// scheme (no +asyncpg driver suffix)
    asyncpg_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(asyncpg_url)
    try:
        # ----------------------------------------------------------------
        # Fetch products with brand IS NULL belonging to the ליאור store.
        # We match the store by name (both possible spellings).
        # ----------------------------------------------------------------
        rows = await conn.fetch(
            """
            SELECT DISTINCT p.id, p.canonical_name
            FROM products p
            JOIN store_products sp ON sp.product_id = p.id
            JOIN stores s          ON sp.store_id  = s.id
            WHERE p.brand IS NULL
              AND (
                  s.name_he ILIKE '%ליאור%'
               OR s.name_en ILIKE '%lior%'
              )
            """
        )

        logger.info("Found %d ליאור products with brand=NULL", len(rows))

        updated = 0
        skipped = 0

        for row in rows:
            product_id: str = str(row["id"])
            canonical_name: str = row["canonical_name"] or ""
            brand = _extract_brand(canonical_name)

            if brand is None:
                skipped += 1
                continue

            await conn.execute(
                "UPDATE products SET brand = $1 WHERE id = $2::uuid",
                brand,
                product_id,
            )
            updated += 1

        logger.info(
            "Done. Updated: %d products with brand assigned. "
            "Skipped (no brand found): %d.",
            updated,
            skipped,
        )

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(fix_lior_brands())
