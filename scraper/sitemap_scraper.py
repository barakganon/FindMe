"""
scraper/sitemap_scraper.py — WordPress/WooCommerce sitemap scraper with DB persistence.

For every store in the ``stores`` table with ``scrape_status='skipped'``, this script:

1. Strips UTM params and resolves the base URL (``scheme://netloc`` only).
2. Detects a sitemap by probing common paths in order:
   ``/sitemap.xml`` → ``/sitemap_index.xml`` → ``/page-sitemap.xml``
3. Parses the sitemap XML to find a child sitemap whose ``<loc>`` contains
   ``product`` (e.g. ``product-sitemap.xml``, ``sitemap-products.xml``).
4. Collects up to 500 product ``<loc>`` URLs from the product sitemap.
5. For each product URL, fetches the HTML page and extracts JSON-LD structured
   data (``@type: Product``) to get name, brand, price, availability.
6. Upserts into ``products`` and ``store_products`` (same patterns as
   ``shopify_product_scraper.py``).
7. Saves raw product data to
   ``scraper/data/raw/sitemap/{store_id}_{timestamp}.json`` for archival.
8. Updates ``stores.scrape_status`` to ``'done'`` / ``'failed'`` /
   ``'no_sitemap'`` and inserts a ``scrape_runs`` audit row.

Usage::

    # Run against all skipped stores
    python -m scraper.sitemap_scraper

    # Single store (for testing)
    python -m scraper.sitemap_scraper --store-id <UUID>

    # Cap how many stores to process in one run
    python -m scraper.sitemap_scraper --limit 5

    # Change log verbosity
    python -m scraper.sitemap_scraper --log-level DEBUG

Environment variable ``DATABASE_URL`` must point to a running PostgreSQL
instance with the FindMe schema already migrated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import asyncpg
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("sitemap_scraper")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

load_dotenv()

_DEFAULT_DB_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://localhost/buyme_search"
)
# asyncpg wants the ``postgresql://`` or ``postgres://`` scheme (not asyncpg://)
# Strip the +asyncpg suffix that SQLAlchemy uses if present.
_DB_URL: str = _DEFAULT_DB_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
    "postgres+asyncpg://", "postgres://"
)

# Maximum product URLs to process per store (avoids overwhelming large stores)
_MAX_PRODUCT_URLS: int = 2000

# Maximum concurrent product-page fetches within a single store
_PRODUCT_CONCURRENCY: int = 5

# Polite delay (seconds) between individual product page fetches within a store
_POLITE_DELAY_SECONDS: float = 0.5

# Sitemap probe paths, tried in order
_SITEMAP_PATHS: list[str] = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/page-sitemap.xml",
]

# Substrings that indicate a child sitemap is a product sitemap
_PRODUCT_SITEMAP_HINTS: list[str] = [
    "product",
]

# Raw archive directory
_RAW_DIR: Path = Path(__file__).parent / "data" / "raw" / "sitemap"

# HTTP headers to present as a modern browser
_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ProductData = dict[str, Any]

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def strip_utm_params(url: str) -> str:
    """
    Return only ``scheme://netloc`` from ``url``, discarding path, query, and
    fragment.  This ensures UTM tracking parameters do not corrupt sitemap
    probe URLs.

    Args:
        url: Any URL string (may contain query parameters, fragments, etc.)

    Returns:
        Bare ``scheme://netloc`` string, e.g. ``https://example.co.il``.
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
) -> Optional[str]:
    """
    GET ``url`` and return the response body text on HTTP 200, else ``None``.

    Non-200 responses and network errors are silently swallowed and ``None``
    is returned so callers can decide how to handle missing pages.

    Args:
        client: A shared :class:`httpx.AsyncClient` instance.
        url:    URL to fetch.

    Returns:
        Response body text, or ``None`` on any error or non-200 status.
    """
    try:
        response = await client.get(url, headers=_HTTP_HEADERS)
        if response.status_code == 200:
            return response.text
        logger.debug("fetch_html(%s) → HTTP %d", url, response.status_code)
        return None
    except Exception as exc:
        logger.debug("fetch_html(%s) → %s: %s", url, type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Sitemap detection
# ---------------------------------------------------------------------------


async def find_sitemap_url(
    client: httpx.AsyncClient,
    base_url: str,
) -> Optional[str]:
    """
    Probe common sitemap paths against ``base_url`` and return the first one
    that responds with HTTP 200 and contains XML content.

    Tries ``/sitemap.xml``, ``/sitemap_index.xml``, and
    ``/page-sitemap.xml`` in that order.

    Args:
        client:   Shared HTTP client.
        base_url: ``scheme://netloc`` of the store (no trailing slash).

    Returns:
        Full URL of the first working sitemap, or ``None`` if none found.
    """
    for path in _SITEMAP_PATHS:
        url = base_url.rstrip("/") + path
        logger.debug("Probing sitemap: %s", url)
        text = await fetch_html(client, url)
        if text and ("<urlset" in text or "<sitemapindex" in text or "<sitemap" in text):
            logger.debug("Found sitemap at %s", url)
            return url
    return None


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------


def _parse_sitemap_locs(xml_text: str) -> list[str]:
    """
    Extract all ``<loc>`` text values from a sitemap or sitemap-index XML string.

    Args:
        xml_text: Raw XML text of the sitemap.

    Returns:
        List of URL strings found in ``<loc>`` tags.
    """
    soup = BeautifulSoup(xml_text, "xml")
    return [tag.get_text(strip=True) for tag in soup.find_all("loc")]


def _is_sitemap_index(xml_text: str) -> bool:
    """
    Return ``True`` if the XML is a sitemap index (contains ``<sitemapindex>``).

    A sitemap index lists child sitemaps rather than page URLs directly.

    Args:
        xml_text: Raw XML text.

    Returns:
        ``True`` if this is a sitemap index document.
    """
    return "<sitemapindex" in xml_text


def find_all_product_sitemap_urls(xml_text: str) -> list[str]:
    """
    From a sitemap-index XML, find ALL child sitemaps whose ``<loc>`` URL
    suggests they contain product pages (e.g. product-sitemap.xml,
    product-sitemap2.xml, ...).

    Args:
        xml_text: Raw XML text of the sitemap index.

    Returns:
        List of product child sitemap URLs (may be empty).
    """
    locs = _parse_sitemap_locs(xml_text)
    found = []
    for loc in locs:
        lower = loc.lower()
        if any(hint in lower for hint in _PRODUCT_SITEMAP_HINTS):
            logger.debug("Found product sitemap: %s", loc)
            found.append(loc)
    return found


async def fetch_product_urls(
    client: httpx.AsyncClient,
    sitemap_url: str,
) -> list[str]:
    """
    Resolve ``sitemap_url`` to a flat list of product page URLs.

    If ``sitemap_url`` is a sitemap index, this function drills into ALL
    product child sitemaps to collect URLs.  If it is already a URL list
    sitemap, URLs are extracted directly.  Returns at most
    ``_MAX_PRODUCT_URLS`` entries.

    Args:
        client:      Shared HTTP client.
        sitemap_url: URL of the initial sitemap (may be an index or a URL list).

    Returns:
        List of product page URL strings (capped at ``_MAX_PRODUCT_URLS``).
    """
    text = await fetch_html(client, sitemap_url)
    if not text:
        logger.debug("Empty response for sitemap: %s", sitemap_url)
        return []

    if _is_sitemap_index(text):
        # Collect ALL product sitemaps (product-sitemap.xml, product-sitemap2.xml, ...)
        product_sitemap_urls = find_all_product_sitemap_urls(text)
        if not product_sitemap_urls:
            logger.debug("No product sitemap found in index: %s", sitemap_url)
            return []
        all_urls: list[str] = []
        for ps_url in product_sitemap_urls:
            if len(all_urls) >= _MAX_PRODUCT_URLS:
                break
            product_text = await fetch_html(client, ps_url)
            if product_text:
                all_urls.extend(_parse_sitemap_locs(product_text))
        urls = all_urls
    else:
        urls = _parse_sitemap_locs(text)

    logger.debug("Found %d URLs in sitemap (before cap)", len(urls))
    return urls[:_MAX_PRODUCT_URLS]


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


def _type_is_product(type_val: Any) -> bool:
    """Return True if a JSON-LD @type value refers to a Product."""
    if isinstance(type_val, str):
        return type_val.lower() == "product"
    if isinstance(type_val, list):
        return any(isinstance(t, str) and t.lower() == "product" for t in type_val)
    return False


def extract_json_ld(html: str) -> Optional[dict[str, Any]]:
    """
    Parse HTML and return the first JSON-LD block whose ``@type`` is
    ``Product`` (case-insensitive).

    Handles:
    - Single-object and list-of-objects JSON-LD payloads
    - ``@graph`` arrays (Yoast SEO / WooCommerce pattern)
    - ``@type`` as a string or list of strings

    Args:
        html: Raw HTML text of a product page.

    Returns:
        Dict of the JSON-LD Product object, or ``None`` if not found.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            # Flatten: handle top-level list or single object
            items: list[Any] = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Direct @type: Product
                if _type_is_product(item.get("@type", "")):
                    return item
                # @graph pattern (Yoast SEO wraps everything in @graph)
                for graph_item in item.get("@graph", []):
                    if isinstance(graph_item, dict) and _type_is_product(graph_item.get("@type", "")):
                        return graph_item
        except Exception:
            continue
    return None


def _extract_price_from_offers(offers: Any) -> Optional[float]:
    """
    Coerce the ``price`` field from a JSON-LD ``offers`` value to float.

    The ``offers`` field may be a single object or a list; both are handled.

    Args:
        offers: The raw ``offers`` value from a JSON-LD Product dict.

    Returns:
        Price as a float, or ``None`` if not found / unparseable.
    """
    if offers is None:
        return None
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None
    price_raw = offers.get("price")
    if price_raw is None:
        return None
    try:
        value = float(str(price_raw).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    # Reject non-positive + the ₪999,999 "price on request" sentinel at ingest so
    # re-scrapes don't keep re-introducing bogus prices (see data-audit-v1.md).
    if value <= 0 or value >= 999999.0:
        return None
    return value


def _extract_currency_from_offers(offers: Any) -> str:
    """
    Extract the ``priceCurrency`` from a JSON-LD ``offers`` value.

    Args:
        offers: The raw ``offers`` value from a JSON-LD Product dict.

    Returns:
        Currency code string, defaulting to ``"ILS"`` if not found.
    """
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        return offers.get("priceCurrency", "ILS") or "ILS"
    return "ILS"


def _extract_availability_from_offers(offers: Any) -> bool:
    """
    Determine in-stock availability from a JSON-LD ``offers`` value.

    Returns ``True`` if the ``availability`` URL/string contains ``InStock``,
    and defaults to ``True`` when the field is absent.

    Args:
        offers: The raw ``offers`` value from a JSON-LD Product dict.

    Returns:
        ``True`` if the product appears to be in stock.
    """
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        avail = offers.get("availability", "")
        if avail:
            return "InStock" in avail
    # Default to available when no data
    return True


def parse_product_from_json_ld(
    json_ld: dict[str, Any],
    page_url: str,
) -> ProductData:
    """
    Extract normalised product fields from a JSON-LD Product dict.

    Fields extracted:
    - ``canonical_name``: ``name``
    - ``brand``: ``brand.name`` or ``brand`` string
    - ``price``: ``offers.price`` (float or None)
    - ``currency``: ``offers.priceCurrency`` (default ``"ILS"``)
    - ``availability``: ``offers.availability`` contains ``"InStock"``
    - ``product_url``: ``url`` or ``page_url`` fallback
    - ``category_path``: ``category`` if present
    - ``image_url``: ``image`` (string or list)

    Args:
        json_ld:  JSON-LD Product dict extracted from the page HTML.
        page_url: The URL of the page (used as ``product_url`` fallback).

    Returns:
        Dict with normalised product fields.
    """
    # Brand: may be a dict with 'name' or a plain string
    brand_raw: Any = json_ld.get("brand")
    if isinstance(brand_raw, dict):
        brand: Optional[str] = brand_raw.get("name") or None
    elif isinstance(brand_raw, str):
        brand = brand_raw.strip() or None
    else:
        brand = None

    # Image: may be a string, a list of strings, or an ImageObject
    image_raw: Any = json_ld.get("image")
    image_url: Optional[str] = None
    if isinstance(image_raw, str):
        image_url = image_raw
    elif isinstance(image_raw, list) and image_raw:
        first = image_raw[0]
        image_url = first if isinstance(first, str) else first.get("url")
    elif isinstance(image_raw, dict):
        image_url = image_raw.get("url")

    offers = json_ld.get("offers")

    return {
        "canonical_name": (json_ld.get("name") or "").strip(),
        "brand": brand,
        "price": _extract_price_from_offers(offers),
        "currency": _extract_currency_from_offers(offers),
        "availability": _extract_availability_from_offers(offers),
        "product_url": (json_ld.get("url") or page_url).strip(),
        "category_path": (json_ld.get("category") or None),
        "image_url": image_url,
    }


# ---------------------------------------------------------------------------
# Raw-archive helper
# ---------------------------------------------------------------------------


def save_raw_archive(
    store_id: uuid.UUID,
    timestamp: str,
    products: list[ProductData],
) -> Path:
    """
    Save raw product data JSON to the local archive.

    Args:
        store_id:  UUID of the store (used in the filename).
        timestamp: ISO-8601 compact timestamp string (e.g. ``20260324T183411``).
        products:  List of parsed product dicts.

    Returns:
        Absolute :class:`~pathlib.Path` to the saved file.
    """
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    filename = _RAW_DIR / f"{store_id}_{timestamp}.json"
    filename.write_text(
        json.dumps(products, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("Raw archive saved → %s", filename)
    return filename


# ---------------------------------------------------------------------------
# DB upsert helpers (asyncpg — mirrors shopify_product_scraper.py)
# ---------------------------------------------------------------------------


async def upsert_product(
    conn: asyncpg.Connection,
    canonical_name: str,
    brand: Optional[str],
    category_path: Optional[str],
) -> uuid.UUID:
    """
    Insert or update a row in the ``products`` table.

    Matches on ``canonical_name``.  On conflict, updates ``brand`` and
    ``category_path`` only when the incoming value is non-null, preserving any
    AI-normalised data from a previous run.

    Args:
        conn:           asyncpg connection.
        canonical_name: Product name used as the canonical identifier.
        brand:          Brand string (may be None).
        category_path:  Category string (may be None).

    Returns:
        UUID of the inserted or existing product row.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO products (id, canonical_name, brand, category_path, first_seen_at,
                              created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $2, $3, now(), now(), now())
        ON CONFLICT (canonical_name)
        DO UPDATE SET
            brand          = COALESCE(EXCLUDED.brand, products.brand),
            category_path  = COALESCE(EXCLUDED.category_path, products.category_path),
            updated_at     = now()
        RETURNING id
        """,
        canonical_name,
        brand,
        category_path,
    )
    product_id: uuid.UUID = row["id"]
    return product_id


async def upsert_store_product(
    conn: asyncpg.Connection,
    product_id: uuid.UUID,
    store_id: uuid.UUID,
    price: Optional[float],
    currency: str,
    availability: bool,
    product_url: Optional[str],
    raw_name: Optional[str],
    image_url: Optional[str] = None,
) -> None:
    """
    Insert or update a row in the ``store_products`` table.

    The unique constraint is on ``(product_id, store_id, product_url)``.
    On conflict, ``price``, ``availability``, ``raw_name``, and ``image_url`` are updated.

    Args:
        conn:         asyncpg connection.
        product_id:   FK to ``products.id``.
        store_id:     FK to ``stores.id``.
        price:        Latest scraped price.
        currency:     Currency code (e.g. ``"ILS"``).
        availability: Whether the product is currently in stock.
        product_url:  Full product page URL on the store's site.
        raw_name:     Pre-normalisation product name (for re-processing).
        image_url:    Primary product image URL (may be None).
    """
    await conn.execute(
        """
        INSERT INTO store_products (id, product_id, store_id, price, currency,
                                    availability, product_url, raw_name,
                                    image_url, image_url_updated_at,
                                    created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                $8, CASE WHEN $8 IS NOT NULL THEN now() ELSE NULL END,
                now(), now())
        ON CONFLICT ON CONSTRAINT uq_store_product_url
        DO UPDATE SET
            price                = EXCLUDED.price,
            availability         = EXCLUDED.availability,
            raw_name             = EXCLUDED.raw_name,
            image_url            = COALESCE(EXCLUDED.image_url, store_products.image_url),
            image_url_updated_at = CASE
                WHEN EXCLUDED.image_url IS NOT NULL THEN now()
                ELSE store_products.image_url_updated_at
            END,
            updated_at           = now()
        """,
        product_id,
        store_id,
        price,
        currency,
        availability,
        product_url,
        raw_name,
        image_url,
    )


async def mark_store_done(
    conn: asyncpg.Connection,
    store_id: uuid.UUID,
) -> None:
    """
    Set ``stores.scrape_status = 'done'`` and update ``last_scraped_at``.

    Args:
        conn:     asyncpg connection.
        store_id: UUID of the store row to update.
    """
    await conn.execute(
        """
        UPDATE stores
        SET scrape_status   = 'done',
            last_scraped_at = now(),
            scrape_error    = NULL,
            updated_at      = now()
        WHERE id = $1
        """,
        store_id,
    )


async def mark_store_failed(
    conn: asyncpg.Connection,
    store_id: uuid.UUID,
    error_message: str,
) -> None:
    """
    Set ``stores.scrape_status = 'failed'`` and record the error message.

    Args:
        conn:          asyncpg connection.
        store_id:      UUID of the store row to update.
        error_message: Human-readable error description.
    """
    await conn.execute(
        """
        UPDATE stores
        SET scrape_status = 'failed',
            scrape_error  = $2,
            updated_at    = now()
        WHERE id = $1
        """,
        store_id,
        error_message[:2000],
    )


async def mark_store_no_sitemap(
    conn: asyncpg.Connection,
    store_id: uuid.UUID,
) -> None:
    """
    Set ``stores.scrape_status = 'no_sitemap'`` when no sitemap was found.

    Args:
        conn:     asyncpg connection.
        store_id: UUID of the store row to update.
    """
    await conn.execute(
        """
        UPDATE stores
        SET scrape_status = 'no_sitemap',
            scrape_error  = 'No accessible sitemap found',
            updated_at    = now()
        WHERE id = $1
        """,
        store_id,
    )


async def insert_scrape_run(
    conn: asyncpg.Connection,
    store_id: uuid.UUID,
    status: str,
    items_scraped: int,
    items_new: int,
    items_updated: int,
    raw_snapshot_path: Optional[str],
    error_message: Optional[str],
) -> None:
    """
    Insert a completed ``scrape_runs`` audit row.

    Args:
        conn:               asyncpg connection.
        store_id:           FK to ``stores.id``.
        status:             ``'success'``, ``'failed'``, ``'no_sitemap'``, etc.
        items_scraped:      Total product URLs processed.
        items_new:          Products newly inserted this run.
        items_updated:      Products updated this run.
        raw_snapshot_path:  Path to the raw JSON archive file (or None).
        error_message:      Error description on failure (or None).
    """
    await conn.execute(
        """
        INSERT INTO scrape_runs (id, store_id, run_type, status,
                                 started_at, finished_at,
                                 items_scraped, items_new, items_updated,
                                 raw_snapshot_path, error_message,
                                 created_at, updated_at)
        VALUES (gen_random_uuid(), $1, 'store_products', $2,
                now(), now(),
                $3, $4, $5,
                $6, $7,
                now(), now())
        """,
        store_id,
        status,
        items_scraped,
        items_new,
        items_updated,
        raw_snapshot_path,
        error_message,
    )


# ---------------------------------------------------------------------------
# Per-product fetch + parse (with concurrency)
# ---------------------------------------------------------------------------


async def _fetch_and_parse_product(
    client: httpx.AsyncClient,
    url: str,
) -> Optional[tuple[str, dict[str, Any]]]:
    """
    Fetch a product page and extract JSON-LD product data.

    Returns ``None`` if the page could not be fetched or contained no
    ``Product`` JSON-LD block.

    Args:
        client: Shared HTTP client.
        url:    Product page URL.

    Returns:
        Tuple of ``(page_url, json_ld_dict)`` or ``None``.
    """
    html = await fetch_html(client, url)
    if not html:
        return None
    try:
        json_ld = extract_json_ld(html)
    except Exception as exc:
        logger.debug("JSON-LD parse error for %s: %s", url, exc)
        return None
    if json_ld is None:
        logger.debug("No JSON-LD Product found at %s", url)
        return None
    return (url, json_ld)


async def fetch_products_concurrently(
    client: httpx.AsyncClient,
    urls: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    """
    Fetch and parse up to ``_PRODUCT_CONCURRENCY`` product pages at a time.

    A ``_POLITE_DELAY_SECONDS`` sleep is inserted between each batch to avoid
    overwhelming the target server.

    Args:
        client: Shared HTTP client.
        urls:   List of product page URLs to fetch.

    Returns:
        List of ``(page_url, json_ld_dict)`` tuples for pages that returned a
        JSON-LD Product block.
    """
    results: list[tuple[str, dict[str, Any]]] = []
    # Process in batches of _PRODUCT_CONCURRENCY
    for batch_start in range(0, len(urls), _PRODUCT_CONCURRENCY):
        batch = urls[batch_start : batch_start + _PRODUCT_CONCURRENCY]
        batch_results = await asyncio.gather(
            *[_fetch_and_parse_product(client, url) for url in batch],
            return_exceptions=False,
        )
        for item in batch_results:
            if item is not None:
                results.append(item)
        # Polite delay between batches (not after the very last one)
        if batch_start + _PRODUCT_CONCURRENCY < len(urls):
            await asyncio.sleep(_POLITE_DELAY_SECONDS)
    return results


# ---------------------------------------------------------------------------
# Per-store scrape logic
# ---------------------------------------------------------------------------


async def scrape_store(
    conn: asyncpg.Connection,
    client: httpx.AsyncClient,
    store_id: uuid.UUID,
    store_url: str,
    store_name: str,
) -> None:
    """
    Attempt a full sitemap-based product scrape for a single store.

    Steps:
        1. Strip UTM params from ``store_url`` to get ``base_url``.
        2. Probe common sitemap paths; if none respond, mark ``no_sitemap``.
        3. Parse the sitemap to collect product page URLs (up to 500).
        4. Fetch each product page and extract JSON-LD ``Product`` data.
        5. Save raw archive.
        6. Upsert into ``products`` and ``store_products``.
        7. Update store status and insert audit ``scrape_runs`` row.

    Args:
        conn:       asyncpg connection.
        client:     Shared HTTP client.
        store_id:   UUID of the store.
        store_url:  Raw URL from the ``stores`` table (may contain UTM params).
        store_name: Display name for log messages.
    """
    logger.info("[%s] Starting sitemap scrape — %s", store_name, store_url)

    # ---- 1. Resolve base URL -------------------------------------------------
    base_url = strip_utm_params(store_url)
    logger.debug("[%s] base_url=%s", store_name, base_url)

    # ---- 2. Detect sitemap ---------------------------------------------------
    sitemap_url = await find_sitemap_url(client, base_url)
    if not sitemap_url:
        logger.info("[%s] No sitemap found — marking no_sitemap", store_name)
        await mark_store_no_sitemap(conn, store_id)
        await insert_scrape_run(
            conn=conn,
            store_id=store_id,
            status="no_sitemap",
            items_scraped=0,
            items_new=0,
            items_updated=0,
            raw_snapshot_path=None,
            error_message="No accessible sitemap found",
        )
        return

    logger.info("[%s] Sitemap found: %s", store_name, sitemap_url)

    # ---- 3. Collect product URLs from sitemap --------------------------------
    try:
        product_urls = await fetch_product_urls(client, sitemap_url)
    except Exception as exc:
        error_msg = f"Sitemap fetch/parse failed: {type(exc).__name__}: {exc}"
        logger.error("[%s] %s", store_name, error_msg)
        await mark_store_failed(conn, store_id, error_msg)
        await insert_scrape_run(
            conn=conn,
            store_id=store_id,
            status="failed",
            items_scraped=0,
            items_new=0,
            items_updated=0,
            raw_snapshot_path=None,
            error_message=error_msg,
        )
        return

    logger.info("[%s] product_urls_found=%d", store_name, len(product_urls))

    if not product_urls:
        logger.info("[%s] No product URLs found in sitemap", store_name)
        await mark_store_no_sitemap(conn, store_id)
        await insert_scrape_run(
            conn=conn,
            store_id=store_id,
            status="no_sitemap",
            items_scraped=0,
            items_new=0,
            items_updated=0,
            raw_snapshot_path=None,
            error_message="Sitemap found but contained no product URLs",
        )
        return

    # ---- 4. Fetch product pages and extract JSON-LD -------------------------
    try:
        raw_results = await fetch_products_concurrently(client, product_urls)
    except Exception as exc:
        error_msg = f"Product page fetch failed: {type(exc).__name__}: {exc}"
        logger.error("[%s] %s", store_name, error_msg)
        await mark_store_failed(conn, store_id, error_msg)
        await insert_scrape_run(
            conn=conn,
            store_id=store_id,
            status="failed",
            items_scraped=len(product_urls),
            items_new=0,
            items_updated=0,
            raw_snapshot_path=None,
            error_message=error_msg,
        )
        return

    logger.info(
        "[%s] pages_with_json_ld=%d / %d fetched",
        store_name,
        len(raw_results),
        len(product_urls),
    )

    # Parse each JSON-LD result into normalised product dicts
    parsed_products: list[ProductData] = []
    for page_url, json_ld in raw_results:
        product_data = parse_product_from_json_ld(json_ld, page_url)
        if product_data["canonical_name"]:
            parsed_products.append(product_data)
        else:
            logger.debug("Skipping product with empty name at %s", page_url)

    logger.info(
        "[%s] products_with_name=%d",
        store_name,
        len(parsed_products),
    )

    # ---- 5. Save raw archive -------------------------------------------------
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    archive_path: Optional[Path] = None
    if parsed_products:
        try:
            archive_path = save_raw_archive(store_id, timestamp, parsed_products)
        except Exception as exc:
            # Archive failure is non-fatal — log and continue
            logger.warning("[%s] Could not save raw archive: %s", store_name, exc)

    # ---- 6. Upsert into DB ---------------------------------------------------
    items_new = 0
    items_updated = 0

    if parsed_products:
        async with conn.transaction():
            for product_data in parsed_products:
                canonical_name: str = product_data["canonical_name"]

                # Determine insert vs update for counter
                existing = await conn.fetchval(
                    "SELECT id FROM products WHERE canonical_name = $1",
                    canonical_name,
                )

                product_id = await upsert_product(
                    conn=conn,
                    canonical_name=canonical_name,
                    brand=product_data.get("brand"),
                    category_path=product_data.get("category_path"),
                )

                if existing is None:
                    items_new += 1
                else:
                    items_updated += 1

                await upsert_store_product(
                    conn=conn,
                    product_id=product_id,
                    store_id=store_id,
                    price=product_data.get("price"),
                    currency=product_data.get("currency", "ILS"),
                    availability=product_data.get("availability", True),
                    product_url=product_data.get("product_url"),
                    raw_name=canonical_name,
                    image_url=product_data.get("image_url"),
                )

    logger.info(
        "[%s] products_inserted=%d products_updated=%d",
        store_name,
        items_new,
        items_updated,
    )

    # ---- 7. Update store status + audit row ----------------------------------
    await mark_store_done(conn, store_id)
    await insert_scrape_run(
        conn=conn,
        store_id=store_id,
        status="success",
        items_scraped=len(product_urls),
        items_new=items_new,
        items_updated=items_updated,
        raw_snapshot_path=str(archive_path) if archive_path else None,
        error_message=None,
    )

    logger.info("[%s] Done.", store_name)


# ---------------------------------------------------------------------------
# Store-fetching query
# ---------------------------------------------------------------------------


async def fetch_stores(
    conn: asyncpg.Connection,
    store_id: Optional[uuid.UUID] = None,
    limit: Optional[int] = None,
) -> list[asyncpg.Record]:
    """
    Fetch stores with ``scrape_status = 'skipped'`` from the DB.

    Only stores with a non-null ``store_url`` are returned.  Filtering to
    ``'skipped'`` avoids re-scraping stores already processed by the Shopify
    scraper or marked as failed.

    Args:
        conn:     asyncpg connection.
        store_id: If provided, return only this store (regardless of status).
        limit:    Maximum number of stores to return.

    Returns:
        List of asyncpg Record objects with columns
        ``id``, ``name_he``, ``store_url``.
    """
    if store_id is not None:
        rows = await conn.fetch(
            """
            SELECT id, name_he, store_url
            FROM stores
            WHERE id = $1
              AND store_url IS NOT NULL
            """,
            store_id,
        )
        return rows

    if limit is not None:
        rows = await conn.fetch(
            """
            SELECT id, name_he, store_url
            FROM stores
            WHERE store_url IS NOT NULL
              AND scrape_status = 'skipped'
            ORDER BY id
            LIMIT $1
            """,
            limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, name_he, store_url
            FROM stores
            WHERE store_url IS NOT NULL
              AND scrape_status = 'skipped'
            ORDER BY id
            """
        )
    return rows


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main(
    store_id_arg: Optional[str] = None,
    limit_arg: Optional[int] = None,
) -> None:
    """
    Orchestrate the sitemap product scrape across all eligible stores.

    Args:
        store_id_arg: Optional store UUID string (from ``--store-id`` CLI arg).
        limit_arg:    Optional max stores to process (from ``--limit`` CLI arg).
    """
    # Parse store_id if provided
    target_store_id: Optional[uuid.UUID] = None
    if store_id_arg:
        try:
            target_store_id = uuid.UUID(store_id_arg)
        except ValueError:
            logger.error("Invalid UUID for --store-id: %r", store_id_arg)
            sys.exit(1)

    logger.info(
        "Connecting to DB: %s",
        _DB_URL.split("@")[-1] if "@" in _DB_URL else _DB_URL,
    )

    try:
        conn: asyncpg.Connection = await asyncpg.connect(_DB_URL)
    except Exception as exc:
        logger.error("Could not connect to database: %s", exc)
        sys.exit(1)

    try:
        stores = await fetch_stores(
            conn,
            store_id=target_store_id,
            limit=limit_arg,
        )
    except Exception as exc:
        logger.error("Failed to fetch stores from DB: %s", exc)
        await conn.close()
        sys.exit(1)

    if not stores:
        logger.warning(
            "No eligible stores found%s.",
            f" for store_id={target_store_id}" if target_store_id else "",
        )
        await conn.close()
        return

    logger.info(
        "Processing %d store(s) with scrape_status='skipped'.",
        len(stores),
    )

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0, connect=10.0),
    ) as client:
        for idx, store_row in enumerate(stores, start=1):
            store_id: uuid.UUID = store_row["id"]
            store_name: str = store_row["name_he"] or str(store_id)
            store_url: str = store_row["store_url"]

            logger.info(
                "--- Store %d/%d: %s ---",
                idx,
                len(stores),
                store_name,
            )

            try:
                await scrape_store(
                    conn=conn,
                    client=client,
                    store_id=store_id,
                    store_url=store_url,
                    store_name=store_name,
                )
            except Exception as exc:
                # Catch-all: one store failure must not abort the whole run
                error_msg = f"Unexpected error: {type(exc).__name__}: {exc}"
                logger.exception("[%s] %s", store_name, error_msg)
                try:
                    await mark_store_failed(conn, store_id, error_msg)
                    await insert_scrape_run(
                        conn=conn,
                        store_id=store_id,
                        status="failed",
                        items_scraped=0,
                        items_new=0,
                        items_updated=0,
                        raw_snapshot_path=None,
                        error_message=error_msg,
                    )
                except Exception as db_exc:
                    logger.error(
                        "[%s] Could not write failure to DB: %s",
                        store_name,
                        db_exc,
                    )

            # Polite delay between stores (not after the very last one)
            if idx < len(stores):
                await asyncio.sleep(_POLITE_DELAY_SECONDS)

    await conn.close()
    logger.info("All stores processed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.sitemap_scraper",
        description=(
            "Scrape WordPress/WooCommerce product catalogs via sitemaps for "
            "BuyMe partner stores and persist results to the FindMe database."
        ),
    )
    parser.add_argument(
        "--store-id",
        metavar="UUID",
        default=None,
        help="Target a single store by its UUID (useful for testing).",
    )
    parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        default=None,
        help="Maximum number of stores to process in this run.",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser


if __name__ == "__main__":
    _parser = _build_arg_parser()
    _args = _parser.parse_args()

    # Apply log-level override
    logging.getLogger().setLevel(getattr(logging, _args.log_level))

    asyncio.run(
        main(
            store_id_arg=_args.store_id,
            limit_arg=_args.limit,
        )
    )
