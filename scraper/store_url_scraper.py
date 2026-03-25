"""
scraper/store_url_scraper.py — Enrich stores.store_url from buyme.co.il pages.
===============================================================================

For every store where ``store_url IS NULL AND scrape_status = 'pending'``,
this script visits the store's BuyMe page (e.g. https://buyme.co.il/brands/2208)
using httpx (no Playwright), parses the HTML with BeautifulSoup, and extracts
the store's own external website URL.

Extraction strategy (tried in order, first match wins):
    1. Anchor tags whose ``href`` starts with ``http`` and points to a domain
       outside buyme.co.il — typical "visit website" links in the store info card.
    2. ``data-url`` / ``data-website`` attributes on any element.
    3. A ``<meta>`` canonical URL heuristic (last resort).

DB updates are done via asyncpg directly (faster than SQLAlchemy for bulk writes).

Usage:
    python -m scraper.store_url_scraper
    python -m scraper.store_url_scraper --limit 50
    python -m scraper.store_url_scraper --limit 200 --batch-size 25 --delay 1.0
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import asyncpg
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUYME_HOST = "buyme.co.il"

# HTTP settings — match the pattern in base.py / buyme_store_scraper.py
_REQUEST_TIMEOUT = 20.0  # seconds
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://buyme.co.il/",
}

# Default batch concurrency and inter-batch delay (seconds)
DEFAULT_BATCH_SIZE = 50
DEFAULT_DELAY = 0.5


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _asyncpg_dsn(database_url: str) -> str:
    """
    Convert a SQLAlchemy-style DATABASE_URL to a plain asyncpg DSN.

    SQLAlchemy uses ``postgresql+asyncpg://...`` as the scheme; asyncpg
    itself expects ``postgresql://...`` (or ``postgres://...``).

    Args:
        database_url: Value from the DATABASE_URL env var.

    Returns:
        A DSN string that asyncpg.connect() / create_pool() accepts.
    """
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_url)


async def fetch_pending_stores(
    conn: asyncpg.Connection,
    limit: Optional[int] = None,
) -> list[asyncpg.Record]:
    """
    Return all stores that still need their ``store_url`` populated.

    Args:
        conn:  Active asyncpg connection.
        limit: Maximum number of rows to return.  None → no limit.

    Returns:
        List of asyncpg.Record with fields: ``id``, ``name_he``, ``buyme_url``.
    """
    sql = """
        SELECT id, name_he, buyme_url
        FROM stores
        WHERE store_url IS NULL
          AND scrape_status = 'pending'
          AND buyme_url IS NOT NULL
        ORDER BY id
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    return await conn.fetch(sql)


async def update_store(
    conn: asyncpg.Connection,
    store_id: str,
    store_url: Optional[str],
    status: str,
    error: Optional[str] = None,
) -> None:
    """
    Persist the scraped website URL (or failure state) back to the DB.

    Args:
        conn:      Active asyncpg connection.
        store_id:  UUID of the store row (as string).
        store_url: The external website URL found, or None on failure.
        status:    ``'success'`` or ``'failed'``.
        error:     Human-readable error message (stored in scrape_error).
    """
    await conn.execute(
        """
        UPDATE stores
        SET store_url       = $1,
            scrape_status   = $2,
            scrape_error    = $3,
            last_scraped_at = $4
        WHERE id = $5::uuid
        """,
        store_url,
        status,
        error,
        datetime.now(timezone.utc),
        store_id,
    )


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _is_external(href: str) -> bool:
    """
    Return True if ``href`` points to a domain outside buyme.co.il.

    Args:
        href: Raw href string from an anchor tag.

    Returns:
        True for external HTTP/HTTPS URLs; False otherwise.
    """
    if not href or not href.startswith(("http://", "https://")):
        return False
    try:
        host = urlparse(href).hostname or ""
    except ValueError:
        return False
    # Reject BuyMe itself and common CDN / tracking domains
    blocked = {
        BUYME_HOST,
        "www." + BUYME_HOST,
        # common social/tracking links often embedded in every page
        "facebook.com",
        "www.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "twitter.com",
        "www.twitter.com",
        "tiktok.com",
        "www.tiktok.com",
        "youtube.com",
        "www.youtube.com",
        "linkedin.com",
        "www.linkedin.com",
        "apple.com",
        "apps.apple.com",
        "play.google.com",
        "wa.me",
        "api.whatsapp.com",
    }
    return host not in blocked and bool(host)


def extract_store_website(html: str) -> Optional[str]:
    """
    Parse a BuyMe store HTML page and return the store's own website URL.

    Strategy (tried in order; first successful match is returned):

    1. **Anchor links in the page body** — look for ``<a href="...">`` whose
       ``href`` is an external URL.  We score candidates and prefer links that
       appear in classed elements commonly used for store info (``website``,
       ``site``, ``link``, ``url``), then fall back to any external anchor.

    2. **data-url / data-website attributes** — some BuyMe store cards expose
       the URL via HTML5 data attributes on wrapper ``<div>`` or ``<a>`` tags.

    3. Returns ``None`` if no URL can be found.

    Args:
        html: Raw HTML string from the BuyMe store page.

    Returns:
        An external URL string, or None.
    """
    soup = BeautifulSoup(html, "html.parser")

    # ---- Strategy 1: anchor tags ----------------------------------------
    # Prefer anchors whose class name contains hints like "website", "site",
    # "link", "url", "web".  Collect both "preferred" and "fallback" lists.
    preferred: list[str] = []
    fallback: list[str] = []

    hint_pattern = re.compile(r"(website|site-?link|store.?url|web)", re.IGNORECASE)

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()
        if not _is_external(href):
            continue

        # Normalise href (strip trailing slash for dedup)
        href = href.rstrip("/")

        classes: str = " ".join(tag.get("class", []))
        parent_classes: str = " ".join(tag.parent.get("class", [])) if tag.parent else ""
        combined_classes = classes + " " + parent_classes

        if hint_pattern.search(combined_classes) or hint_pattern.search(
            tag.get("id", "")
        ):
            preferred.append(href)
        else:
            fallback.append(href)

    if preferred:
        return preferred[0]

    # ---- Strategy 2: data-url / data-website attributes -----------------
    for tag in soup.find_all(True):  # any element
        for attr in ("data-url", "data-website", "data-site", "data-link"):
            val: str = tag.get(attr, "").strip()
            if val and _is_external(val):
                return val.rstrip("/")

    # ---- Strategy 3: any external anchor as last resort -----------------
    if fallback:
        # Heuristic: favour shorter URLs (less likely to be deep-linked ads)
        fallback.sort(key=len)
        return fallback[0]

    return None


# ---------------------------------------------------------------------------
# Per-store fetch + parse
# ---------------------------------------------------------------------------


async def scrape_one_store(
    client: httpx.AsyncClient,
    store_id: str,
    name_he: str,
    buyme_url: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch a single BuyMe store page and extract the store website URL.

    Args:
        client:    Shared async HTTP client.
        store_id:  UUID string (for logging only).
        name_he:   Store name in Hebrew (for logging).
        buyme_url: BuyMe store page URL, e.g. https://buyme.co.il/brands/2208.

    Returns:
        A 2-tuple of ``(website_url, error_message)``.
        On success: ``(url, None)`` where url may still be None if not found.
        On HTTP/network error: ``(None, error_string)``.
    """
    try:
        response = await client.get(buyme_url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        msg = f"HTTP {exc.response.status_code} for {buyme_url}"
        logger.warning("  ✗ %s — %s", name_he, msg)
        return None, msg
    except httpx.RequestError as exc:
        msg = f"Request error for {buyme_url}: {exc}"
        logger.warning("  ✗ %s — %s", name_he, msg)
        return None, msg

    website_url = extract_store_website(response.text)
    return website_url, None


# ---------------------------------------------------------------------------
# Main batch runner
# ---------------------------------------------------------------------------


async def run(
    limit: Optional[int] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    delay: float = DEFAULT_DELAY,
) -> None:
    """
    Main coroutine — reads pending stores, scrapes them in batches, updates DB.

    Args:
        limit:      Maximum number of stores to process (None = all).
        batch_size: Number of concurrent requests per batch.
        delay:      Seconds to sleep between batches (be polite).
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in the environment / .env file.")

    dsn = _asyncpg_dsn(database_url)

    logger.info("Connecting to database …")
    conn: asyncpg.Connection = await asyncpg.connect(dsn)

    try:
        stores = await fetch_pending_stores(conn, limit=limit)
    except Exception as exc:
        logger.error("Failed to read stores from DB: %s", exc)
        await conn.close()
        raise

    total = len(stores)
    if total == 0:
        logger.info("No pending stores found — nothing to do.")
        await conn.close()
        return

    logger.info("Found %d pending store(s) to process.", total)

    found_count = 0
    failed_count = 0
    processed_count = 0

    async with httpx.AsyncClient(
        headers=_HEADERS,
        follow_redirects=True,
        timeout=_REQUEST_TIMEOUT,
    ) as client:

        # Slice into batches
        for batch_start in range(0, total, batch_size):
            batch = stores[batch_start : batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            logger.info(
                "--- Batch %d | stores %d–%d of %d ---",
                batch_num,
                batch_start + 1,
                min(batch_start + batch_size, total),
                total,
            )

            # Launch all requests in the batch concurrently
            tasks = [
                scrape_one_store(
                    client,
                    str(row["id"]),
                    row["name_he"],
                    row["buyme_url"],
                )
                for row in batch
            ]
            results: list[tuple[Optional[str], Optional[str]]] = await asyncio.gather(
                *tasks, return_exceptions=False
            )

            # Persist results
            batch_found = 0
            batch_failed = 0
            for row, (website_url, error) in zip(batch, results):
                if error:
                    status = "failed"
                    batch_failed += 1
                elif website_url:
                    status = "success"
                    batch_found += 1
                else:
                    # No error but also no URL — mark as failed (not found)
                    status = "failed"
                    error = "No external website URL found on BuyMe page"
                    batch_failed += 1

                await update_store(
                    conn,
                    store_id=str(row["id"]),
                    store_url=website_url,
                    status=status,
                    error=error,
                )

                logger.debug(
                    "  %s → %s [%s]",
                    row["name_he"],
                    website_url or "(none)",
                    status,
                )

            processed_count += len(batch)
            found_count += batch_found
            failed_count += batch_failed

            logger.info(
                "Batch %d complete — found: %d, failed/not-found: %d  "
                "(running total: %d/%d processed, %d URLs found)",
                batch_num,
                batch_found,
                batch_failed,
                processed_count,
                total,
                found_count,
            )

            # Polite delay between batches (skip after the last batch)
            if batch_start + batch_size < total:
                await asyncio.sleep(delay)

    await conn.close()

    # Final summary
    print("\n" + "=" * 60)
    print(f"Store URL scrape complete.")
    print(f"  Total processed : {processed_count}")
    print(f"  URLs found      : {found_count}  ({100 * found_count // max(processed_count, 1)}%)")
    print(f"  Failed/not found: {failed_count}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape buyme.co.il store pages and populate stores.store_url. "
            "Processes stores with store_url IS NULL AND scrape_status = 'pending'."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of stores to process (default: all pending).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Concurrent requests per batch (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        metavar="SECONDS",
        help=f"Delay between batches in seconds (default: {DEFAULT_DELAY}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    await run(
        limit=args.limit,
        batch_size=args.batch_size,
        delay=args.delay,
    )


if __name__ == "__main__":
    asyncio.run(_main())
