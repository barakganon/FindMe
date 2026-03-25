"""
scraper/woocommerce_product_scraper.py — WooCommerce catalog scraper with DB persistence.

For every online store in the ``stores`` table that exposes a WooCommerce
REST API v3 ``/wp-json/wc/v3/products`` endpoint, this script:

1. Detects WooCommerce via ``GET {base_url}/wp-json/wc/v3/products?per_page=1``.
   A 200 response containing a JSON array is treated as confirmation.
2. Paginates through ``?page=N&per_page=100`` until an empty array is returned.
3. Saves the raw JSON response payload to
   ``scraper/data/raw/woocommerce/{store_id}_{timestamp}.json`` for archival.
4. Upserts one ``products`` row per product (canonical_name = WooCommerce name,
   brand = first entry in the ``brands`` attribute if present).
5. Upserts one ``store_products`` row per product linking it to the store
   (product_url = WooCommerce ``permalink``, price, availability).
6. Updates ``stores.scrape_status`` → ``'success'`` and
   ``stores.last_scraped_at`` → UTC now on completion; ``'failed'`` on error.
7. Inserts a ``scrape_runs`` audit row for every attempt.

Usage::

    # Run against all eligible stores
    python -m scraper.woocommerce_product_scraper

    # Single store (for testing)
    python -m scraper.woocommerce_product_scraper --store-id <UUID>

    # Cap how many stores to process in one run
    python -m scraper.woocommerce_product_scraper --limit 5

Environment variable ``DATABASE_URL`` (or the default
``postgresql://localhost/buyme_search``) must point to a running PostgreSQL
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
logger = logging.getLogger("woocommerce_product_scraper")

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

_WC_PAGE_SIZE: int = 100
_POLITE_DELAY_SECONDS: float = 1.0

# Raw archive directory
_RAW_DIR: Path = (
    Path(__file__).parent / "data" / "raw" / "woocommerce"
)

# HTTP headers to present as a modern browser
_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

# ---------------------------------------------------------------------------
# Data classes (plain dicts typed for clarity)
# ---------------------------------------------------------------------------

# Type alias for a raw WooCommerce product dict from /wp-json/wc/v3/products
WooProductDict = dict[str, Any]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    """
    GET ``url`` and return the parsed JSON body.

    Args:
        client: A shared :class:`httpx.AsyncClient` instance.
        url:    The URL to fetch.

    Returns:
        Parsed JSON (usually a dict or list).

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        json.JSONDecodeError:  If the body is not valid JSON.
    """
    response = await client.get(url, headers=_HTTP_HEADERS)
    response.raise_for_status()
    return response.json()


def _strip_to_base_url(store_url: str) -> str:
    """
    Strip query parameters, fragments, and UTM params from a store URL,
    returning only scheme + host (e.g. ``https://example.co.il``).

    Args:
        store_url: Raw store URL, potentially containing UTM or other params.

    Returns:
        Clean base URL with scheme and netloc only.
    """
    parsed = urlparse(store_url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def is_woocommerce_store(client: httpx.AsyncClient, store_url: str) -> bool:
    """
    Check whether ``store_url`` exposes a WooCommerce REST API v3 endpoint.

    A store is considered WooCommerce if ``GET /wp-json/wc/v3/products?per_page=1``
    returns HTTP 200 with a JSON body that is a list (array).

    Stores returning 401/403 (auth required) or 404 are not treated as
    WooCommerce, since we require public read-only access to be useful.

    Args:
        client:    Shared HTTP client.
        store_url: Root URL of the store (UTM params are stripped automatically).

    Returns:
        ``True`` if the store exposes a public WooCommerce API; ``False`` otherwise.
    """
    base = _strip_to_base_url(store_url)
    url = f"{base}/wp-json/wc/v3/products?per_page=1"
    try:
        data = await fetch_json(client, url)
        result: bool = isinstance(data, list)
        logger.debug("is_woocommerce(%s) → %s", store_url, result)
        return result
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403, 404):
            logger.debug(
                "is_woocommerce(%s) → False [HTTP %d — not WooCommerce or auth required]",
                store_url,
                status,
            )
        else:
            logger.debug(
                "is_woocommerce(%s) → False [HTTP %d]",
                store_url,
                status,
            )
        return False
    except Exception as exc:
        logger.debug(
            "is_woocommerce(%s) → False [%s: %s]",
            store_url,
            type(exc).__name__,
            exc,
        )
        return False


async def fetch_all_woocommerce_products(
    client: httpx.AsyncClient,
    store_url: str,
) -> list[WooProductDict]:
    """
    Paginate through ``{store_url}/wp-json/wc/v3/products`` and return every product.

    Uses the ``?page=N&per_page=100`` query parameters. Stops when WooCommerce
    returns an empty list.

    Args:
        client:    Shared HTTP client.
        store_url: Root URL of the WooCommerce store (UTM params stripped internally).

    Returns:
        Flat list of raw WooCommerce product dicts.
    """
    all_products: list[WooProductDict] = []
    page = 1
    base = _strip_to_base_url(store_url)

    while True:
        url = f"{base}/wp-json/wc/v3/products?page={page}&per_page={_WC_PAGE_SIZE}"
        logger.debug("Fetching page %d → %s", page, url)

        try:
            data = await fetch_json(client, url)
        except Exception as exc:
            logger.error(
                "Failed to fetch page %d for %s: %s — stopping pagination",
                page,
                store_url,
                exc,
            )
            break

        products: list[WooProductDict] = data if isinstance(data, list) else []
        if not products:
            logger.debug(
                "Empty products on page %d — pagination complete (%d total)",
                page,
                len(all_products),
            )
            break

        all_products.extend(products)
        logger.debug(
            "Page %d: %d products (running total: %d)",
            page,
            len(products),
            len(all_products),
        )
        page += 1

    return all_products


# ---------------------------------------------------------------------------
# Raw-archive helper
# ---------------------------------------------------------------------------


def save_raw_archive(
    store_id: uuid.UUID,
    timestamp: str,
    products: list[WooProductDict],
) -> Path:
    """
    Save raw WooCommerce products JSON to the local archive.

    Args:
        store_id:  UUID of the store (used in the filename).
        timestamp: ISO-8601 compact timestamp string (e.g. ``20260324T183411``).
        products:  Raw product list from WooCommerce.

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
# Product-field extraction helpers
# ---------------------------------------------------------------------------


def _parse_price(price_str: Any) -> Optional[float]:
    """
    Coerce a WooCommerce price value (typically a string like ``"129.90"``) to float.

    Returns ``None`` if the value is absent or unparseable.
    """
    if price_str is None:
        return None
    try:
        val = float(price_str)
        # WooCommerce uses "0" or "" for missing prices
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _extract_brand(product: WooProductDict) -> Optional[str]:
    """
    Attempt to extract a brand name from a WooCommerce product dict.

    WooCommerce brand plugins typically expose brands either as a top-level
    ``brands`` list or as an attribute named ``brand`` / ``מותג`` (Hebrew).

    Args:
        product: Raw WooCommerce product dict.

    Returns:
        Brand name string, or ``None`` if not found.
    """
    # 1. Check top-level ``brands`` list (e.g. Perfect Brands for WooCommerce plugin)
    brands: list[dict[str, Any]] = product.get("brands", [])
    if brands and isinstance(brands, list):
        first_brand = brands[0]
        if isinstance(first_brand, dict):
            name = first_brand.get("name", "").strip()
            if name:
                return name

    # 2. Fall back to product attributes named "brand" or "מותג"
    attributes: list[dict[str, Any]] = product.get("attributes", [])
    for attr in attributes:
        if not isinstance(attr, dict):
            continue
        attr_name: str = (attr.get("name") or "").lower().strip()
        if attr_name in ("brand", "מותג", "manufacturer", "יצרן"):
            options: list[str] = attr.get("options", [])
            if options and isinstance(options, list):
                return str(options[0]).strip() or None

    return None


def extract_product_fields(
    product: WooProductDict,
) -> dict[str, Any]:
    """
    Extract the fields we care about from a raw WooCommerce product dict.

    Price preference: ``sale_price`` (if non-empty) → ``price`` → ``None``.
    Availability is derived from ``stock_status == "instock"``.
    The product URL comes directly from the WooCommerce ``permalink`` field.

    Args:
        product: Raw WooCommerce product dict from ``/wp-json/wc/v3/products``.

    Returns:
        Dict with keys: ``name``, ``brand``, ``category_path``,
        ``product_url``, ``price``, ``availability``.
    """
    name: str = (product.get("name") or "").strip()

    # Price: prefer sale_price when non-empty, fall back to regular price
    sale_price_raw: Any = product.get("sale_price")
    regular_price_raw: Any = product.get("price")
    price: Optional[float] = _parse_price(sale_price_raw) or _parse_price(regular_price_raw)

    # Category: use first category name if present
    categories: list[dict[str, Any]] = product.get("categories", [])
    category_path: Optional[str] = None
    if categories and isinstance(categories, list):
        first_cat = categories[0]
        if isinstance(first_cat, dict):
            cat_name = (first_cat.get("name") or "").strip()
            category_path = cat_name or None

    # Availability from stock_status
    stock_status: str = (product.get("stock_status") or "").strip()
    availability: bool = stock_status == "instock"

    # Product URL
    permalink: Optional[str] = product.get("permalink") or None

    # Brand
    brand: Optional[str] = _extract_brand(product)

    return {
        "name": name,
        "brand": brand,
        "category_path": category_path,
        "product_url": permalink,
        "price": price,
        "availability": availability,
    }


# ---------------------------------------------------------------------------
# DB upsert helpers (asyncpg)
# ---------------------------------------------------------------------------


async def upsert_product(
    conn: asyncpg.Connection,
    canonical_name: str,
    brand: Optional[str],
    category_path: Optional[str],
) -> uuid.UUID:
    """
    Insert or update a row in the ``products`` table.

    Matches on ``canonical_name`` (unique constraint ``uq_products_canonical_name``).
    If found, updates ``brand`` and ``category_path`` only when the incoming
    value is non-null (preserving AI-normalized data from a previous run).

    Args:
        conn:           asyncpg connection.
        canonical_name: WooCommerce product name used as the canonical name.
        brand:          Brand name extracted from WooCommerce data (may be None).
        category_path:  First WooCommerce category name (may be None).

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
    availability: bool,
    product_url: Optional[str],
    raw_name: Optional[str],
) -> None:
    """
    Insert or update a row in the ``store_products`` table.

    The unique constraint is ``uq_store_product_url`` on ``(product_id, store_id,
    product_url)``.  On conflict, ``price``, ``availability``, and ``raw_name``
    are updated.

    Args:
        conn:         asyncpg connection.
        product_id:   FK to ``products.id``.
        store_id:     FK to ``stores.id``.
        price:        Latest scraped price (ILS).
        availability: Whether the product is currently in stock.
        product_url:  Full product page URL on the store's site (permalink).
        raw_name:     Pre-normalization product name (for re-processing).
    """
    await conn.execute(
        """
        INSERT INTO store_products (id, product_id, store_id, price, currency,
                                    availability, product_url, raw_name,
                                    created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $2, $3, 'ILS', $4, $5, $6, now(), now())
        ON CONFLICT ON CONSTRAINT uq_store_product_url
        DO UPDATE SET
            price        = EXCLUDED.price,
            availability = EXCLUDED.availability,
            raw_name     = EXCLUDED.raw_name,
            updated_at   = now()
        """,
        product_id,
        store_id,
        price,
        availability,
        product_url,
        raw_name,
    )


async def mark_store_success(
    conn: asyncpg.Connection,
    store_id: uuid.UUID,
) -> None:
    """
    Set ``stores.scrape_status = 'success'`` and update ``last_scraped_at``.

    Args:
        conn:     asyncpg connection.
        store_id: UUID of the store row to update.
    """
    await conn.execute(
        """
        UPDATE stores
        SET scrape_status   = 'success',
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
        error_message[:2000],  # Guard against extremely long error strings
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
        status:             ``'success'``, ``'skipped'``, or ``'failed'``.
        items_scraped:      Total WooCommerce products found.
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
    Attempt a full WooCommerce catalog scrape for a single store.

    Steps:
        1. Detect WooCommerce via ``/wp-json/wc/v3/products?per_page=1``.
           Stores returning 401/403/404 are skipped gracefully.
        2. If not WooCommerce: log and skip (mark store as ``'skipped'``).
        3. Paginate and collect all products.
        4. Save raw archive.
        5. Upsert into ``products`` and ``store_products``.
        6. Update store status and insert audit ``scrape_runs`` row.

    Args:
        conn:       asyncpg connection.
        client:     Shared HTTP client.
        store_id:   UUID of the store.
        store_url:  Root URL of the store.
        store_name: Display name for log messages.
    """
    logger.info("[%s] Starting scrape — %s", store_name, store_url)

    # ---- 1. WooCommerce detection -------------------------------------------
    woocommerce = await is_woocommerce_store(client, store_url)
    logger.info(
        "[%s] is_woocommerce=%s",
        store_name,
        woocommerce,
    )

    if not woocommerce:
        logger.info("[%s] Not a WooCommerce store — skipping", store_name)
        await conn.execute(
            """
            UPDATE stores
            SET scrape_status = 'skipped',
                updated_at    = now()
            WHERE id = $1
            """,
            store_id,
        )
        await insert_scrape_run(
            conn=conn,
            store_id=store_id,
            status="skipped",
            items_scraped=0,
            items_new=0,
            items_updated=0,
            raw_snapshot_path=None,
            error_message="Not a WooCommerce store",
        )
        return

    # ---- 2. Paginate and collect products ------------------------------------
    try:
        raw_products = await fetch_all_woocommerce_products(client, store_url)
    except Exception as exc:
        error_msg = f"Pagination failed: {type(exc).__name__}: {exc}"
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

    logger.info(
        "[%s] products_found=%d",
        store_name,
        len(raw_products),
    )

    # ---- 3. Save raw archive -------------------------------------------------
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    archive_path: Optional[Path] = None
    try:
        archive_path = save_raw_archive(store_id, timestamp, raw_products)
    except Exception as exc:
        # Archive failure is non-fatal — log and continue
        logger.warning(
            "[%s] Could not save raw archive: %s",
            store_name,
            exc,
        )

    # ---- 4. Upsert into DB ---------------------------------------------------
    items_new = 0
    items_updated = 0

    async with conn.transaction():
        for product in raw_products:
            fields = extract_product_fields(product)
            if not fields["name"]:
                # Skip products with empty names
                continue

            # Count rows before to distinguish insert vs update
            existing = await conn.fetchval(
                "SELECT id FROM products WHERE canonical_name = $1",
                fields["name"],
            )

            product_id = await upsert_product(
                conn=conn,
                canonical_name=fields["name"],
                brand=fields["brand"],
                category_path=fields["category_path"],
            )

            if existing is None:
                items_new += 1
            else:
                items_updated += 1

            await upsert_store_product(
                conn=conn,
                product_id=product_id,
                store_id=store_id,
                price=fields["price"],
                availability=fields["availability"],
                product_url=fields["product_url"],
                raw_name=fields["name"],
            )

    logger.info(
        "[%s] products_inserted=%d products_updated=%d",
        store_name,
        items_new,
        items_updated,
    )

    # ---- 5. Update store status + audit row ----------------------------------
    await mark_store_success(conn, store_id)
    await insert_scrape_run(
        conn=conn,
        store_id=store_id,
        status="success",
        items_scraped=len(raw_products),
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
    Fetch eligible stores from the DB.

    Eligible stores have ``store_url IS NOT NULL``.  We attempt all stores
    with a URL (not just ``is_online = true``) because some stores may have
    ``is_online`` set incorrectly or not yet classified — the WooCommerce
    detector will filter them out quickly.

    Args:
        conn:     asyncpg connection.
        store_id: If provided, return only this store.
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
            ORDER BY last_scraped_at ASC NULLS FIRST
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
            ORDER BY last_scraped_at ASC NULLS FIRST
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
    Orchestrate the WooCommerce product scrape across all eligible stores.

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

    logger.info("Processing %d store(s).", len(stores))

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

            # Polite delay between stores
            if idx < len(stores):
                await asyncio.sleep(_POLITE_DELAY_SECONDS)

    await conn.close()
    logger.info("All stores processed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scraper.woocommerce_product_scraper",
        description=(
            "Scrape WooCommerce product catalogs for BuyMe partner stores "
            "and persist results to the FindMe database."
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
