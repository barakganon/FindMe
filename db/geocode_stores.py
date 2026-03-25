"""
db/geocode_stores.py — Geocode BuyMe stores using OpenStreetMap Nominatim.

Fetches stores where lat IS NULL and address OR city IS NOT NULL, then
calls the free Nominatim API to resolve coordinates and writes them back.

Nominatim usage policy:
  - Max 1 request/second  → we sleep 1.1 s between requests
  - Must identify the application in the User-Agent header

Usage:
    python -m db.geocode_stores [--limit N] [--log-level LEVEL]

Examples:
    python -m db.geocode_stores --limit 5 --log-level INFO
    python -m db.geocode_stores --limit 100
    python -m db.geocode_stores          # geocode ALL pending stores
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from typing import Optional
from urllib.parse import quote

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/buyme_search")
# asyncpg uses a plain postgresql:// URL (no driver suffix)
_DB_URL = DATABASE_URL.replace("+asyncpg", "")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    # Nominatim requires a descriptive User-Agent; parentheses with email addresses
    # are blocked by their Varnish layer — keep it a plain product/version token.
    "User-Agent": "FindMe-BuyMe-geocoder/1.0",
    "Accept-Language": "he,en",
}
RATE_LIMIT_SLEEP = 1.1  # seconds — Nominatim allows max 1 req/sec
LOG_PROGRESS_EVERY = 10

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Nominatim helper
# ---------------------------------------------------------------------------

def _build_query(address: Optional[str], city: Optional[str]) -> str:
    """Build the best search string for Nominatim from available fields."""
    if address and city:
        # address already often contains the city; use full address + country
        return f"{address}, Israel"
    if address:
        return f"{address}, Israel"
    if city:
        return f"{city}, Israel"
    return ""


async def geocode_one(
    client: httpx.AsyncClient,
    address: Optional[str],
    city: Optional[str],
) -> Optional[tuple[float, float]]:
    """
    Call Nominatim for a single store.

    Returns (lat, lng) float tuple or None when no result is found.
    Sleeps RATE_LIMIT_SLEEP seconds before returning to enforce rate limit.
    """
    query = _build_query(address, city)
    if not query:
        return None

    params = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "il",  # restrict to Israel — faster + more accurate
    }

    try:
        resp = await client.get(NOMINATIM_URL, params=params, timeout=15.0)
        resp.raise_for_status()
        results = resp.json()
        if results:
            hit = results[0]
            lat = float(hit["lat"])
            lon = float(hit["lon"])
            logger.debug("  '%s' → lat=%.5f lng=%.5f (via %s)", query, lat, lon, hit.get("display_name", ""))
            return lat, lon
        else:
            logger.debug("  No result for '%s'", query)
            return None
    except Exception as exc:
        logger.warning("  Nominatim error for '%s': %s", query, exc)
        return None
    finally:
        # Always sleep to respect rate limit, even on error
        await asyncio.sleep(RATE_LIMIT_SLEEP)


# ---------------------------------------------------------------------------
# Main geocoding routine
# ---------------------------------------------------------------------------

async def geocode_stores(limit: Optional[int] = None) -> None:
    """Fetch pending stores and write lat/lng back to the DB."""

    conn = await asyncpg.connect(_DB_URL)

    try:
        # Fetch stores that need geocoding
        query = """
            SELECT id, name_he, address, city
            FROM stores
            WHERE lat IS NULL
              AND (address IS NOT NULL OR city IS NOT NULL)
            ORDER BY created_at
        """
        if limit is not None:
            query += f" LIMIT {int(limit)}"

        rows = await conn.fetch(query)
        total = len(rows)
        logger.info("Stores to geocode: %d", total)

        if total == 0:
            logger.info("Nothing to do — all eligible stores already have coordinates.")
            return

        geocoded = 0
        failed = 0

        async with httpx.AsyncClient(headers=NOMINATIM_HEADERS) as client:
            for idx, row in enumerate(rows, start=1):
                store_id = row["id"]
                name = row["name_he"]
                address = row["address"]
                city = row["city"]

                result = await geocode_one(client, address, city)

                if result is not None:
                    lat, lng = result
                    await conn.execute(
                        "UPDATE stores SET lat = $1, lng = $2 WHERE id = $3",
                        lat,
                        lng,
                        store_id,
                    )
                    geocoded += 1
                    logger.debug("[%d/%d] OK  '%s'  lat=%.5f lng=%.5f", idx, total, name, lat, lng)
                else:
                    failed += 1
                    logger.debug("[%d/%d] MISS '%s' (addr=%r city=%r)", idx, total, name, address, city)

                if idx % LOG_PROGRESS_EVERY == 0:
                    logger.info(
                        "Progress: %d/%d processed — %d geocoded, %d no result",
                        idx,
                        total,
                        geocoded,
                        failed,
                    )

        logger.info(
            "Done. Total=%d | Geocoded=%d | No result=%d",
            total,
            geocoded,
            failed,
        )

    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Geocode BuyMe stores via OpenStreetMap Nominatim.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of stores to geocode (omit for all pending stores).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(geocode_stores(limit=args.limit))


if __name__ == "__main__":
    main()
