"""
db/geocode_stores.py — Geocode BuyMe stores using Google Maps (primary) or Nominatim (fallback).

Fetches stores where lat IS NULL and address OR city IS NOT NULL, then
calls the Google Maps Geocoding API (if GOOGLE_MAPS_API_KEY is set) or
falls back to the free Nominatim API to resolve coordinates and writes them back.

Google Maps usage:
  - Requires GOOGLE_MAPS_API_KEY environment variable
  - Handles Israeli mall names, complex addresses, and mixed Hebrew/English text
  - No rate-limit concerns at the scale of ~500 stores

Nominatim usage policy:
  - Max 1 request/second  → we sleep 1.1 s between requests
  - Must identify the application in the User-Agent header
  - Cannot handle Israeli mall/complex addresses reliably

Usage:
    python -m db.geocode_stores [--limit N] [--log-level LEVEL]
    python -m db.geocode_stores --force           # re-geocode stores that already have lat/lng
    python -m db.geocode_stores --store-id UUID   # geocode a single specific store

Examples:
    python -m db.geocode_stores --limit 5 --log-level INFO
    python -m db.geocode_stores --limit 100
    python -m db.geocode_stores          # geocode ALL pending stores
    python -m db.geocode_stores --force  # re-geocode all stores (improve accuracy)
    python -m db.geocode_stores --store-id 550e8400-e29b-41d4-a716-446655440000
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

GOOGLE_MAPS_API_KEY: Optional[str] = os.getenv("GOOGLE_MAPS_API_KEY")

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
# Google Maps Geocoding helper
# ---------------------------------------------------------------------------

async def geocode_google(
    client: httpx.AsyncClient,
    address: Optional[str],
    city: Optional[str],
) -> Optional[tuple[float, float]]:
    """Geocode using Google Maps API. Returns (lat, lng) or None.

    Args:
        client: Shared httpx.AsyncClient instance.
        address: Store address string (Hebrew/English/mixed), or None.
        city: City name, or None.

    Returns:
        (lat, lng) float tuple on success, None on failure or missing API key.
    """
    if not GOOGLE_MAPS_API_KEY:
        return None

    query = _build_query(address, city)
    if not query:
        return None

    try:
        resp = await client.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "address": query + ", ישראל",
                "key": GOOGLE_MAPS_API_KEY,
                "language": "he",
                "region": "il",
            },
            timeout=10.0,
        )
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            lat = float(loc["lat"])
            lng = float(loc["lng"])
            logger.debug(
                "  Google Maps: '%s' → lat=%.5f lng=%.5f", query, lat, lng
            )
            return lat, lng
        else:
            status = data.get("status", "UNKNOWN")
            logger.debug("  Google Maps: no result for '%s' (status=%s)", query, status)
    except Exception as exc:
        logger.warning("  Google Maps error for '%s': %s", query, exc)

    return None


# ---------------------------------------------------------------------------
# Nominatim helper
# ---------------------------------------------------------------------------

def _build_query(address: Optional[str], city: Optional[str]) -> str:
    """Build the best search string from available fields."""
    if address and city:
        # address already often contains the city; use full address + country
        return f"{address}, Israel"
    if address:
        return f"{address}, Israel"
    if city:
        return f"{city}, Israel"
    return ""


async def geocode_nominatim(
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
            logger.debug(
                "  Nominatim: '%s' → lat=%.5f lng=%.5f (via %s)",
                query, lat, lon, hit.get("display_name", ""),
            )
            return lat, lon
        else:
            logger.debug("  Nominatim: no result for '%s'", query)
            return None
    except Exception as exc:
        logger.warning("  Nominatim error for '%s': %s", query, exc)
        return None
    finally:
        # Always sleep to respect rate limit, even on error
        await asyncio.sleep(RATE_LIMIT_SLEEP)


# ---------------------------------------------------------------------------
# Combined geocoding with fallback
# ---------------------------------------------------------------------------

async def geocode_one(
    google_client: httpx.AsyncClient,
    nominatim_client: httpx.AsyncClient,
    address: Optional[str],
    city: Optional[str],
) -> tuple[Optional[tuple[float, float]], str]:
    """Geocode a single store, trying Google Maps first then Nominatim.

    Args:
        google_client: httpx client for Google Maps (no special headers needed).
        nominatim_client: httpx client with Nominatim User-Agent headers.
        address: Store address, or None.
        city: City name, or None.

    Returns:
        Tuple of ((lat, lng) or None, method_used).
        method_used is "google", "nominatim", or "none".
    """
    # Try Google Maps first if API key is available
    if GOOGLE_MAPS_API_KEY:
        result = await geocode_google(google_client, address, city)
        if result is not None:
            return result, "google"
        logger.debug("  Google Maps failed, falling back to Nominatim")

    # Fall back to Nominatim
    result = await geocode_nominatim(nominatim_client, address, city)
    if result is not None:
        return result, "nominatim"

    return None, "none"


# ---------------------------------------------------------------------------
# Main geocoding routine
# ---------------------------------------------------------------------------

async def geocode_stores(
    limit: Optional[int] = None,
    force: bool = False,
    store_id: Optional[str] = None,
) -> None:
    """Fetch pending stores and write lat/lng back to the DB.

    Args:
        limit: Maximum number of stores to process. None = all.
        force: If True, re-geocode stores that already have lat/lng set.
        store_id: If set, geocode only this specific store UUID.
    """
    conn = await asyncpg.connect(_DB_URL)

    try:
        # Build the fetch query based on flags
        if store_id:
            # Single-store mode
            rows = await conn.fetch(
                "SELECT id, name_he, address, city FROM stores WHERE id = $1::uuid",
                store_id,
            )
        elif force:
            # Re-geocode ALL stores (with or without existing coordinates)
            query = """
                SELECT id, name_he, address, city
                FROM stores
                WHERE (address IS NOT NULL OR city IS NOT NULL)
                ORDER BY created_at
            """
            if limit is not None:
                query += f" LIMIT {int(limit)}"
            rows = await conn.fetch(query)
        else:
            # Default: only stores that don't have coordinates yet
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
        logger.info(
            "Stores to geocode: %d%s%s",
            total,
            " (force mode — re-geocoding all)" if force else "",
            f" (single store: {store_id})" if store_id else "",
        )

        if total == 0:
            logger.info("Nothing to do — no eligible stores found.")
            return

        geocoded = 0
        failed = 0
        via_google = 0
        via_nominatim = 0

        if GOOGLE_MAPS_API_KEY:
            logger.info("Google Maps API key found — using Google Maps as primary geocoder.")
        else:
            logger.info(
                "GOOGLE_MAPS_API_KEY not set — using Nominatim only. "
                "Add GOOGLE_MAPS_API_KEY to .env for better Israeli address support."
            )

        async with httpx.AsyncClient(timeout=15.0) as google_client:
            async with httpx.AsyncClient(headers=NOMINATIM_HEADERS) as nominatim_client:
                for idx, row in enumerate(rows, start=1):
                    sid = row["id"]
                    name = row["name_he"]
                    address = row["address"]
                    city = row["city"]

                    result, method = await geocode_one(
                        google_client, nominatim_client, address, city
                    )

                    if result is not None:
                        lat, lng = result
                        await conn.execute(
                            "UPDATE stores SET lat = $1, lng = $2 WHERE id = $3",
                            lat,
                            lng,
                            sid,
                        )
                        geocoded += 1
                        if method == "google":
                            via_google += 1
                        elif method == "nominatim":
                            via_nominatim += 1
                        logger.debug(
                            "[%d/%d] OK  '%s'  lat=%.5f lng=%.5f  (via %s)",
                            idx, total, name, lat, lng, method,
                        )
                    else:
                        failed += 1
                        logger.debug(
                            "[%d/%d] MISS '%s' (addr=%r city=%r)",
                            idx, total, name, address, city,
                        )

                    if idx % LOG_PROGRESS_EVERY == 0:
                        logger.info(
                            "Progress: %d/%d processed — %d geocoded (%d Google, %d Nominatim), %d failed",
                            idx, total, geocoded, via_google, via_nominatim, failed,
                        )

        logger.info(
            "Done. Geocoded %d/%d stores (%d via Google, %d via Nominatim, %d failed)",
            geocoded, total, via_google, via_nominatim, failed,
        )
        print(
            f"Geocoded {geocoded}/{total} stores "
            f"({via_google} via Google, {via_nominatim} via Nominatim, {failed} failed)"
        )

    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Geocode BuyMe stores using Google Maps (primary) or Nominatim (fallback).\n\n"
            "Set GOOGLE_MAPS_API_KEY in .env for best results with Israeli addresses."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of stores to geocode (omit for all pending stores).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help=(
            "Re-geocode stores that already have lat/lng set. "
            "Useful for improving accuracy after switching to Google Maps."
        ),
    )
    parser.add_argument(
        "--store-id",
        type=str,
        default=None,
        metavar="UUID",
        help="Geocode a single specific store by its UUID. Ignores --limit.",
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
    asyncio.run(
        geocode_stores(
            limit=args.limit,
            force=args.force,
            store_id=args.store_id,
        )
    )


if __name__ == "__main__":
    main()
