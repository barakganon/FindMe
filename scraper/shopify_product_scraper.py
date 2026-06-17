"""
scraper/shopify_product_scraper.py — Shopify catalog scraper with DB persistence.

For every online store in the ``stores`` table that exposes a Shopify
``/products.json`` endpoint, this script:

1. Paginates through the endpoint (250 products per page) until exhausted.
2. Saves the raw JSON response payload to
   ``scraper/data/raw/shopify/{store_id}_{timestamp}.json`` for archival.
3. Upserts one ``products`` row per product (canonical_name = Shopify title,
   brand = Shopify vendor).
4. Upserts one ``store_products`` row per product linking it to the store
   (product_url = ``{store_url}/products/{handle}``, price, availability).
5. Updates ``stores.scrape_status`` → ``'success'`` and
   ``stores.last_scraped_at`` → UTC now on completion; ``'failed'`` on error.
6. Inserts a ``scrape_runs`` audit row for every attempt.

Usage::

    # Run against all eligible stores
    python -m scraper.shopify_product_scraper

    # Single store (for testing)
    python -m scraper.shopify_product_scraper --store-id <UUID>

    # Cap how many stores to process in one run
    python -m scraper.shopify_product_scraper --limit 5

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
from urllib.parse import urljoin, urlparse

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
logger = logging.getLogger("shopify_product_scraper")

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

_SHOPIFY_PAGE_LIMIT: int = 250
_POLITE_DELAY_SECONDS: float = 1.0

# Raw archive directory
_RAW_DIR: Path = (
    Path(__file__).parent / "data" / "raw" / "shopify"
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

# Type alias for a raw Shopify product dict from /products.json
ShopifyProductDict = dict[str, Any]


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


async def is_shopify_store(client: httpx.AsyncClient, store_url: str) -> bool:
    """
    Check whether ``store_url`` exposes a Shopify ``/products.json`` endpoint.

    A store is considered Shopify if the endpoint returns HTTP 200 with a JSON
    body that has a top-level ``products`` key.

    Args:
        client:    Shared HTTP client.
        store_url: Root URL of the store (no trailing slash).

    Returns:
        ``True`` if the store is Shopify; ``False`` otherwise.
    """
    url = urljoin(store_url.rstrip("/") + "/", "products.json")
    try:
        data = await fetch_json(client, url)
        result: bool = isinstance(data, dict) and "products" in data
        logger.debug("is_shopify(%s) → %s", store_url, result)
        return result
    except Exception as exc:
        logger.debug(
            "is_shopify(%s) → False [%s: %s]",
            store_url,
            type(exc).__name__,
            exc,
        )
        return False


async def fetch_all_shopify_products(
    client: httpx.AsyncClient,
    store_url: str,
) -> list[ShopifyProductDict]:
    """
    Paginate through ``{store_url}/products.json`` and return every product.

    Uses the ``?page=N&limit=250`` query parameters. Stops when Shopify
    returns an empty ``products`` list.

    Args:
        client:    Shared HTTP client.
        store_url: Root URL of the Shopify store (no trailing slash).

    Returns:
        Flat list of raw Shopify product dicts.
    """
    all_products: list[ShopifyProductDict] = []
    page = 1
    # Strip query params / fragments so UTM params don't corrupt the URL
    _parsed = urlparse(store_url)
    base = f"{_parsed.scheme}://{_parsed.netloc}"

    while True:
        url = f"{base}/products.json?page={page}&limit={_SHOPIFY_PAGE_LIMIT}"
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

        products: list[ShopifyProductDict] = data.get("products", [])
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
    products: list[ShopifyProductDict],
) -> Path:
    """
    Save raw Shopify products JSON to the local archive.

    Args:
        store_id:  UUID of the store (used in the filename).
        timestamp: ISO-8601 compact timestamp string (e.g. ``20260324T183411``).
        products:  Raw product list from Shopify.

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


# Prices at/above this are treated as a "price on request" sentinel, not a real
# price (e.g. ₪999,999 seen leaking from ENERGYM). See _bmad-output/data-audit-v1.md.
_PRICE_SENTINEL = 999999.0


def _parse_price(price_str: Any) -> Optional[float]:
    """
    Coerce a Shopify price value (typically a string like ``"129.90"``) to float.

    Returns ``None`` if the value is absent, unparseable, non-positive, or a
    "price on request" sentinel — so bogus prices never enter the catalog
    (otherwise every re-scrape re-introduces them; see data-audit-v1.md).
    """
    if price_str is None:
        return None
    try:
        value = float(price_str)
    except (ValueError, TypeError):
        return None
    if value <= 0 or value >= _PRICE_SENTINEL:
        return None
    return value


def _extract_availability(variant: dict[str, Any]) -> bool:
    """
    Determine availability from a Shopify variant dict.

    Prefers the ``available`` boolean field; falls back to
    ``inventory_quantity > 0`` when ``available`` is absent.
    """
    available = variant.get("available")
    if available is not None:
        return bool(available)
    qty = variant.get("inventory_quantity")
    if qty is not None:
        return int(qty) > 0
    # Default to available when no inventory data is present
    return True


def extract_product_fields(
    product: ShopifyProductDict,
    store_url: str,
) -> dict[str, Any]:
    """
    Extract the fields we care about from a raw Shopify product dict.

    We collapse multi-variant products to a single representative entry
    by using the first variant for price and availability.  The product URL
    is derived from the handle, and the raw vendor string is used as brand.

    Args:
        product:   Raw Shopify product dict from ``/products.json``.
        store_url: Root URL of the store (used to build ``product_url``).

    Returns:
        Dict with keys: ``title``, ``vendor``, ``product_type``, ``handle``,
        ``product_url``, ``price``, ``availability``, ``image_url``.
    """
    handle: str = product.get("handle", "")
    title: str = product.get("title", "").strip()
    vendor: str = (product.get("vendor") or "").strip()
    product_type: str = (product.get("product_type") or "").strip()

    # Build product page URL from handle
    product_url: Optional[str] = (
        f"{store_url.rstrip('/')}/products/{handle}" if handle else None
    )

    # Primary image
    images: list[dict] = product.get("images", [])
    image_url: Optional[str] = images[0].get("src") if images else None

    # Use first variant for price + availability
    variants: list[dict] = product.get("variants", [])
    first_variant: dict = variants[0] if variants else {}

    price = _parse_price(first_variant.get("price"))
    availability = _extract_availability(first_variant)

    return {
        "title": title,
        "vendor": vendor or None,
        "product_type": product_type or None,
        "handle": handle,
        "product_url": product_url,
        "price": price,
        "availability": availability,
        "image_url": image_url,
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

    Matches on ``canonical_name`` (case-insensitive).  If found, updates
    ``brand`` and ``category_path`` only when the incoming value is non-null
    (preserving AI-normalized data from a previous run).

    Args:
        conn:           asyncpg connection.
        canonical_name: Shopify product title used as the canonical name.
        brand:          Shopify vendor string (may be None).
        category_path:  Shopify product_type (may be None).

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
    image_url: Optional[str] = None,
) -> None:
    """
    Insert or update a row in the ``store_products`` table.

    The unique constraint is on ``(product_id, store_id, product_url)``.
    On conflict, ``price``, ``availability``, ``raw_name``, and ``image_url``
    are updated.

    Args:
        conn:         asyncpg connection.
        product_id:   FK to ``products.id``.
        store_id:     FK to ``stores.id``.
        price:        Latest scraped price (ILS).
        availability: Whether the variant is currently in stock.
        product_url:  Full product page URL on the store's site.
        raw_name:     Pre-normalization product title (for re-processing).
        image_url:    Primary product image URL (may be None).
    """
    await conn.execute(
        """
        INSERT INTO store_products (id, product_id, store_id, price, currency,
                                    availability, product_url, raw_name,
                                    image_url, image_url_updated_at,
                                    created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $2, $3, 'ILS', $4, $5, $6,
                CAST($7 AS text), CASE WHEN $7 IS NOT NULL THEN now() ELSE NULL END,
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
        availability,
        product_url,
        raw_name,
        image_url,
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
        status:             ``'success'`` or ``'failed'``.
        items_scraped:      Total Shopify products found.
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
    Attempt a full Shopify catalog scrape for a single store.

    Steps:
        1. Detect Shopify via ``/products.json``.
        2. If not Shopify: log and skip (mark store as ``'skipped'``).
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

    # ---- 1. Shopify detection ------------------------------------------------
    shopify = await is_shopify_store(client, store_url)
    logger.info(
        "[%s] is_shopify=%s",
        store_name,
        shopify,
    )

    if not shopify:
        logger.info("[%s] Not a Shopify store — skipping", store_name)
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
            error_message="Not a Shopify store",
        )
        return

    # ---- 2. Paginate and collect products ------------------------------------
    try:
        raw_products = await fetch_all_shopify_products(client, store_url)
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
            fields = extract_product_fields(product, store_url)
            if not fields["title"]:
                # Skip products with empty titles
                continue

            # Count rows before to distinguish insert vs update
            existing = await conn.fetchval(
                "SELECT id FROM products WHERE canonical_name = $1",
                fields["title"],
            )

            product_id = await upsert_product(
                conn=conn,
                canonical_name=fields["title"],
                brand=fields["vendor"],
                category_path=fields["product_type"],
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
                raw_name=fields["title"],
                image_url=fields["image_url"],
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
        status="done",
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
    ``is_online`` set incorrectly or not yet classified — the Shopify
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
    Orchestrate the Shopify product scrape across all eligible stores.

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
        timeout=httpx.Timeout(30.0, connect=10.0),
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
        prog="python -m scraper.shopify_product_scraper",
        description=(
            "Scrape Shopify product catalogs for BuyMe partner stores "
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
