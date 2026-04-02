"""
scraper/scheduler.py — Celery task scheduler for FindMe scrape jobs.

Defines a Celery application and periodic tasks for:
    - Scraping the BuyMe partner store list (daily).
    - Scraping product catalogs for individual stores (weekly, per store).
    - Detecting price/availability changes across stored products (daily).
    - Embedding new products without vectors (daily).

All tasks use ``asyncio.run()`` to bridge Celery's synchronous task
execution model with the async scrapers defined elsewhere in this package.

Configuration is read entirely from environment variables:
    CELERY_BROKER_URL  — Redis broker URL (default: redis://localhost:6379/0)
    REDIS_URL          — Redis result backend URL (default: same as broker)

Usage (start worker)::

    celery -A scraper.scheduler worker --loglevel=info

Usage (start beat scheduler)::

    celery -A scraper.scheduler beat --loglevel=info

Usage (combined, for development only)::

    celery -A scraper.scheduler worker --beat --loglevel=info
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger

from scraper.buyme_store_scraper import BuyMeStoreScraper
from scraper.shopify_detector import ShopifyDetector
from scraper.per_store_scraper import PerStoreScraper

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

#: Redis broker URL, read from environment with a sensible default.
_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

#: Redis result backend URL.  Falls back to REDIS_URL, then the broker URL.
_BACKEND_URL: str = os.environ.get("REDIS_URL", _BROKER_URL)


celery_app = Celery(
    "findme_scraper",
    broker=_BROKER_URL,
    backend=_BACKEND_URL,
)
"""
Celery application instance for FindMe scrape jobs.

Configured from ``CELERY_BROKER_URL`` / ``REDIS_URL`` environment variables.
Import this object when you need to submit tasks programmatically::

    from scraper.scheduler import celery_app
    celery_app.send_task("scraper.scheduler.scrape_store_products",
                         args=["store-42", "https://example.co.il"])
"""

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone — Israel Standard Time
    timezone="Asia/Jerusalem",
    enable_utc=True,
    # Retry policy for soft failures
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result expiry — keep task results for 24 hours
    result_expires=86_400,
)

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # Refresh the BuyMe store list every 24 hours (at 02:00 IL time)
    "scrape-buyme-store-list-daily": {
        "task": "scraper.scheduler.scrape_buyme_store_list",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "scraper"},
    },
    # Re-scrape all Shopify stores weekly on Sunday at 03:00 IL time
    "scrape-shopify-stores-weekly": {
        "task": "scraper.scheduler.scrape_shopify_stores",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sunday
        "options": {"queue": "scraper"},
    },
    # Re-scrape all sitemap/WooCommerce stores bi-weekly (1st and 15th at 04:00 IL)
    "scrape-sitemap-stores-biweekly": {
        "task": "scraper.scheduler.scrape_sitemap_stores",
        "schedule": crontab(hour=4, minute=0, day_of_month="1,15"),
        "options": {"queue": "scraper"},
    },
    # Embed any new products without vectors every day at 05:00 IL time
    "embed-new-products-daily": {
        "task": "scraper.scheduler.embed_new_products",
        "schedule": crontab(hour=5, minute=0),
        "options": {"queue": "scraper"},
    },
    # Run product deduplication weekly on Monday at 06:00 IL time (after embedding)
    "run-deduplication-weekly": {
        "task": "scraper.scheduler.run_deduplication",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),  # Monday
        "options": {"queue": "scraper"},
    },
}
celery_app.conf.timezone = "Asia/Jerusalem"

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="scraper.scheduler.scrape_buyme_store_list",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes between retries
)
def scrape_buyme_store_list(self: Any) -> dict[str, Any]:
    """
    Celery task: scrape the BuyMe partner store list and upsert results into DB.

    Instantiates :class:`~scraper.buyme_store_scraper.BuyMeStoreScraper`,
    runs the full scrape, and upserts each store into the ``stores`` table.
    New stores are enqueued for product scraping via
    :func:`scrape_store_products`.

    Scheduled to run **daily** via Celery beat (see ``beat_schedule``).

    Returns:
        A dict with keys ``total``, ``new``, ``updated``, and ``status``.

    Raises:
        Retries up to 3 times (5-minute intervals) on any unexpected exception.
    """
    task_logger.info("Task started: scrape_buyme_store_list")

    import asyncpg
    from dotenv import load_dotenv
    load_dotenv()

    async def _run() -> dict[str, Any]:
        async with BuyMeStoreScraper(headless=True, save_raw=True) as scraper:
            stores = await scraper.run()

        db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        conn = await asyncpg.connect(db_url)
        try:
            new_count = 0
            updated_count = 0

            for store in stores:
                result = await conn.fetchrow(
                    """
                    INSERT INTO stores (
                        id, name_he, name_en, buyme_url, buyme_category,
                        is_online, voucher_network, scrape_status,
                        created_at, updated_at
                    )
                    VALUES (
                        gen_random_uuid(), $1, $2, $3, $4,
                        $5, 'buyme', 'pending',
                        now(), now()
                    )
                    ON CONFLICT (buyme_url) DO UPDATE SET
                        name_he        = EXCLUDED.name_he,
                        buyme_category = EXCLUDED.buyme_category,
                        is_online      = EXCLUDED.is_online,
                        updated_at     = now()
                    RETURNING id, (xmax = 0) AS inserted
                    """,
                    store.get("name_he", ""),
                    store.get("name_en"),
                    store.get("buyme_url", ""),
                    store.get("buyme_category", ""),
                    store.get("is_online", False),
                )

                if result:
                    if result["inserted"]:
                        new_count += 1
                        # Enqueue product scrape for newly-discovered stores
                        store_url = store.get("store_url")
                        if store_url:
                            scrape_store_products.delay(
                                str(result["id"]), store_url
                            )
                    else:
                        updated_count += 1

            # Write audit row (store_id = NULL indicates a store-list-level run)
            await conn.execute(
                """
                INSERT INTO scrape_runs (
                    id, store_id, run_type, status,
                    started_at, finished_at,
                    items_scraped, items_new, items_updated,
                    created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), NULL, 'store_list', 'success',
                    now(), now(),
                    $1, $2, $3,
                    now(), now()
                )
                """,
                len(stores),
                new_count,
                updated_count,
            )

            task_logger.info(
                "scrape_buyme_store_list completed: total=%d new=%d updated=%d",
                len(stores),
                new_count,
                updated_count,
            )
            return {"status": "success", "total": len(stores), "new": new_count, "updated": updated_count}
        finally:
            await conn.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        task_logger.error(
            "scrape_buyme_store_list failed: %s — retrying", exc, exc_info=True
        )
        raise self.retry(exc=exc)


@celery_app.task(
    name="scraper.scheduler.scrape_store_products",
    bind=True,
    max_retries=3,
    default_retry_delay=600,  # 10 minutes between retries
)
def scrape_store_products(self: Any, store_id: str, store_url: str) -> dict[str, Any]:
    """
    Celery task: scrape the full product catalog for a single partner store.

    Strategy (mirrors the CLAUDE.md Shopify fast-path design):
        1. Instantiate :class:`~scraper.shopify_detector.ShopifyDetector`
           and call :meth:`~scraper.shopify_detector.ShopifyDetector.detect_shopify`.
        2. If the store is Shopify: use
           :class:`~scraper.shopify_detector.ShopifyDetector` to harvest the
           full catalog via ``/products.json`` pagination.
        3. Otherwise: fall back to
           :class:`~scraper.per_store_scraper.PerStoreScraper` which tries
           sitemaps + Playwright page rendering.
        4. Log the product count; persist is handled downstream
           (DB upsert is not performed here — see TODO below).

    Intended to be enqueued **weekly per store** by an orchestration task
    that iterates the ``stores`` DB table.

    Args:
        store_id:  Opaque store identifier (DB primary key as string).
        store_url: Root URL of the store to scrape (e.g. ``https://ksp.co.il``).

    Returns:
        A dict with keys ``store_id``, ``store_url``, ``product_count``,
        ``shopify``, and ``status``.

    Raises:
        Retries up to 3 times (10-minute intervals) on unexpected exceptions.

    Note:
        TODO: After scraping, upsert products into the ``store_products`` DB
        table via the API Agent's DB session (do not reach into ``db/`` directly
        from here — flag requirement to orchestrator).
    """
    task_logger.info(
        "Task started: scrape_store_products store_id=%s url=%s", store_id, store_url
    )

    async def _run() -> tuple[list[dict], bool]:
        """Run Shopify detection then scrape; returns (items, is_shopify)."""
        # Step 1 — Shopify fast-path check
        async with ShopifyDetector(store_url=store_url) as detector:
            is_shopify = await detector.detect_shopify()

        if is_shopify:
            task_logger.info(
                "store_id=%s is Shopify — using ShopifyDetector", store_id
            )
            async with ShopifyDetector(store_url=store_url) as detector:
                items = await detector.scrape()
            return items, True

        # Step 2 — Generic per-store fallback
        task_logger.info(
            "store_id=%s is NOT Shopify — using PerStoreScraper", store_id
        )
        async with PerStoreScraper(store_url=store_url, save_raw=True) as scraper:
            items = await scraper.scrape()
        return items, False

    try:
        items, is_shopify = asyncio.run(_run())
        task_logger.info(
            "scrape_store_products completed: store_id=%s products=%d shopify=%s",
            store_id,
            len(items),
            is_shopify,
        )
        # TODO: pass items to DB upsert task — do not touch db/ directly here
        return {
            "status": "success",
            "store_id": store_id,
            "store_url": store_url,
            "product_count": len(items),
            "shopify": is_shopify,
        }
    except Exception as exc:
        task_logger.error(
            "scrape_store_products failed for store_id=%s: %s",
            store_id,
            exc,
            exc_info=True,
        )
        raise self.retry(exc=exc)


@celery_app.task(
    name="scraper.scheduler.scrape_shopify_stores",
    bind=True,
    max_retries=3,
    default_retry_delay=600,
)
def scrape_shopify_stores(self: Any) -> dict[str, Any]:
    """
    Celery task: weekly re-scrape of all Shopify stores with price-change detection.

    Queries all stores with ``scrape_status = 'success'`` (Shopify stores),
    re-fetches their full product catalog via ``/products.json``, upserts
    products and store_products rows, and writes ``price_changes`` rows for
    any price or availability diffs detected.

    Enqueues :func:`embed_new_products` after completion to catch any newly
    inserted products that lack embedding vectors.

    Scheduled to run **weekly on Sunday** via Celery beat (see ``beat_schedule``).

    Returns:
        A dict with keys ``stores_scraped``, ``total_products``, and ``status``.
    """
    task_logger.info("Task started: scrape_shopify_stores")

    import asyncpg
    import httpx
    from dotenv import load_dotenv
    from scraper.shopify_product_scraper import (
        fetch_all_shopify_products,
        extract_product_fields,
        upsert_product,
        upsert_store_product,
        mark_store_success,
        mark_store_failed,
        insert_scrape_run,
        save_raw_archive,
    )
    import uuid
    from datetime import datetime, timezone

    load_dotenv()

    async def _run() -> dict[str, Any]:
        db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        conn = await asyncpg.connect(db_url)
        total_products = 0
        stores_scraped = 0

        try:
            stores = await conn.fetch(
                """
                SELECT id, name_he, store_url
                FROM stores
                WHERE scrape_status = 'success'
                  AND store_url IS NOT NULL
                """
            )
            task_logger.info("scrape_shopify_stores: found %d eligible stores", len(stores))

            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
            ) as client:
                for store in stores:
                    store_id: uuid.UUID = store["id"]
                    store_url: str = store["store_url"]
                    store_name: str = store["name_he"] or str(store_id)

                    try:
                        raw_products = await fetch_all_shopify_products(client, store_url)
                        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

                        try:
                            archive_path = save_raw_archive(store_id, timestamp, raw_products)
                        except Exception:
                            archive_path = None

                        items_new = 0
                        items_updated = 0

                        async with conn.transaction():
                            for product in raw_products:
                                fields = extract_product_fields(product, store_url)
                                if not fields["title"]:
                                    continue

                                # Check for existing store_product to detect price change
                                existing_sp = await conn.fetchrow(
                                    """
                                    SELECT sp.id, sp.price, sp.availability
                                    FROM store_products sp
                                    JOIN products p ON sp.product_id = p.id
                                    WHERE p.canonical_name = $1
                                      AND sp.store_id = $2
                                    """,
                                    fields["title"],
                                    store_id,
                                )

                                existing_prod = await conn.fetchval(
                                    "SELECT id FROM products WHERE canonical_name = $1",
                                    fields["title"],
                                )

                                product_id = await upsert_product(
                                    conn=conn,
                                    canonical_name=fields["title"],
                                    brand=fields["vendor"],
                                    category_path=fields["product_type"],
                                )

                                if existing_prod is None:
                                    items_new += 1
                                else:
                                    items_updated += 1

                                # Detect and record price change before upsert
                                if existing_sp:
                                    old_price = float(existing_sp["price"]) if existing_sp["price"] is not None else None
                                    new_price = fields["price"]
                                    old_avail = existing_sp["availability"]
                                    new_avail = fields["availability"]

                                    price_changed = (old_price != new_price)
                                    avail_changed = (old_avail != new_avail)

                                    if price_changed or avail_changed:
                                        try:
                                            await conn.execute(
                                                """
                                                INSERT INTO price_changes (
                                                    id, store_product_id,
                                                    old_price, new_price,
                                                    old_availability, new_availability,
                                                    detected_at
                                                )
                                                VALUES (
                                                    gen_random_uuid(), $1,
                                                    $2, $3,
                                                    $4, $5,
                                                    now()
                                                )
                                                """,
                                                existing_sp["id"],
                                                old_price,
                                                new_price,
                                                old_avail,
                                                new_avail,
                                            )
                                            await conn.execute(
                                                """
                                                UPDATE store_products
                                                SET price               = $1,
                                                    availability        = $2,
                                                    last_price_change_at = now(),
                                                    updated_at          = now()
                                                WHERE id = $3
                                                """,
                                                new_price,
                                                new_avail,
                                                existing_sp["id"],
                                            )
                                        except Exception as pc_exc:
                                            # price_changes table may not exist yet (migration pending)
                                            task_logger.warning(
                                                "Could not write price_change for store=%s: %s",
                                                store_name,
                                                pc_exc,
                                            )

                                await upsert_store_product(
                                    conn=conn,
                                    product_id=product_id,
                                    store_id=store_id,
                                    price=fields["price"],
                                    availability=fields["availability"],
                                    product_url=fields["product_url"],
                                    raw_name=fields["title"],
                                )

                        total_products += len(raw_products)
                        stores_scraped += 1
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
                        task_logger.info(
                            "[%s] Done: %d products (new=%d updated=%d)",
                            store_name,
                            len(raw_products),
                            items_new,
                            items_updated,
                        )

                    except Exception as store_exc:
                        error_msg = f"{type(store_exc).__name__}: {store_exc}"
                        task_logger.error(
                            "[%s] scrape failed: %s", store_name, error_msg, exc_info=True
                        )
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
                        except Exception:
                            pass

            # Enqueue embedding for any newly-added products
            embed_new_products.delay()

            return {
                "status": "success",
                "stores_scraped": stores_scraped,
                "total_products": total_products,
            }
        finally:
            await conn.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        task_logger.error("scrape_shopify_stores failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="scraper.scheduler.scrape_sitemap_stores",
    bind=True,
    max_retries=3,
    default_retry_delay=600,
)
def scrape_sitemap_stores(self: Any) -> dict[str, Any]:
    """
    Celery task: bi-weekly re-scrape of all sitemap/WooCommerce stores.

    Queries all stores with ``scrape_status = 'done'`` (sitemap-scraped stores),
    re-fetches their product catalog via sitemap XML parsing and JSON-LD
    extraction, and upserts products and store_products rows.

    Enqueues :func:`embed_new_products` after completion to catch any newly
    inserted products that lack embedding vectors.

    Scheduled to run **bi-weekly** (1st and 15th of each month) via Celery beat.

    Returns:
        A dict with keys ``stores_scraped``, ``total_products``, and ``status``.
    """
    task_logger.info("Task started: scrape_sitemap_stores")

    import asyncpg
    import httpx
    from dotenv import load_dotenv
    from scraper.shopify_product_scraper import (
        upsert_product,
        upsert_store_product,
        mark_store_success,
        mark_store_failed,
        insert_scrape_run,
    )
    from scraper.sitemap_scraper import (
        scrape_store as sitemap_scrape_store,
    )

    load_dotenv()

    async def _run() -> dict[str, Any]:
        db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        conn = await asyncpg.connect(db_url)
        total_products = 0
        stores_scraped = 0

        try:
            stores = await conn.fetch(
                """
                SELECT id, name_he, store_url
                FROM stores
                WHERE scrape_status = 'done'
                  AND store_url IS NOT NULL
                """
            )
            task_logger.info("scrape_sitemap_stores: found %d eligible stores", len(stores))

            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(60.0, connect=10.0),
            ) as client:
                for store in stores:
                    import uuid
                    store_id: uuid.UUID = store["id"]
                    store_url: str = store["store_url"]
                    store_name: str = store["name_he"] or str(store_id)

                    try:
                        await sitemap_scrape_store(
                            conn=conn,
                            client=client,
                            store_id=store_id,
                            store_url=store_url,
                            store_name=store_name,
                        )
                        # Count products scraped in this run by querying the latest scrape_run
                        run_row = await conn.fetchrow(
                            """
                            SELECT items_scraped FROM scrape_runs
                            WHERE store_id = $1
                            ORDER BY finished_at DESC NULLS LAST
                            LIMIT 1
                            """,
                            store_id,
                        )
                        if run_row:
                            total_products += run_row["items_scraped"] or 0
                        stores_scraped += 1
                        task_logger.info("[%s] Done.", store_name)

                    except Exception as store_exc:
                        error_msg = f"{type(store_exc).__name__}: {store_exc}"
                        task_logger.error(
                            "[%s] scrape failed: %s", store_name, error_msg, exc_info=True
                        )
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
                        except Exception:
                            pass

            # Enqueue embedding for any newly-added products
            embed_new_products.delay()

            return {
                "status": "success",
                "stores_scraped": stores_scraped,
                "total_products": total_products,
            }
        finally:
            await conn.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        task_logger.error("scrape_sitemap_stores failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="scraper.scheduler.embed_new_products",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def embed_new_products(self: Any) -> dict[str, Any]:
    """
    Celery task: embed any products that don't have embedding vectors yet.

    Queries up to 5,000 products with ``embedding_vector IS NULL``, batches
    them through the Gemini ``batchEmbedContents`` API (batch size controlled
    by ``EMBED_BATCH_SIZE`` env var, default 100), and writes the vectors back
    to the ``products`` table.

    Scheduled to run **daily** via Celery beat (see ``beat_schedule``).
    Also enqueued on-demand by :func:`scrape_shopify_stores` and
    :func:`scrape_sitemap_stores` after each store scrape.

    Returns:
        A dict with keys ``embedded``, ``total_found``, and ``status``.
    """
    task_logger.info("Task started: embed_new_products")

    import asyncpg
    from dotenv import load_dotenv
    from db.embed_products import _batch_embed, _vec_literal

    load_dotenv()

    async def _run() -> dict[str, Any]:
        db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "")

        if not gemini_key:
            task_logger.error("embed_new_products: GEMINI_API_KEY not set — skipping")
            return {"status": "skipped", "reason": "GEMINI_API_KEY not set", "embedded": 0, "total_found": 0}

        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT id, canonical_name, brand
                FROM products
                WHERE embedding_vector IS NULL
                ORDER BY id
                LIMIT 5000
                """
            )

            if not rows:
                task_logger.info("embed_new_products: all products already embedded")
                return {"status": "success", "embedded": 0, "total_found": 0}

            batch_size = int(os.getenv("EMBED_BATCH_SIZE", "100"))
            embedded_count = 0
            failed_count = 0
            total = len(rows)
            task_logger.info("embed_new_products: %d products need embedding", total)

            for i in range(0, total, batch_size):
                batch = rows[i: i + batch_size]
                texts = [
                    f"{r['brand']} {r['canonical_name']}".strip() if r["brand"]
                    else r["canonical_name"]
                    for r in batch
                ]

                try:
                    vecs = await _batch_embed(texts, gemini_key)
                    if vecs is None:
                        failed_count += len(batch)
                        task_logger.warning(
                            "embed_new_products: batch %d-%d returned None — skipping",
                            i,
                            i + len(batch),
                        )
                        continue

                    updates = [
                        (_vec_literal(vecs[j]), str(batch[j]["id"]))
                        for j in range(len(batch))
                    ]
                    await conn.executemany(
                        "UPDATE products SET embedding_vector = $1::vector WHERE id = $2::uuid",
                        updates,
                    )
                    embedded_count += len(batch)
                    task_logger.info(
                        "embed_new_products: embedded %d / %d", embedded_count, total
                    )
                except Exception as batch_exc:
                    failed_count += len(batch)
                    task_logger.warning(
                        "embed_new_products: batch %d-%d failed: %s — skipping",
                        i,
                        i + len(batch),
                        batch_exc,
                    )

            task_logger.info(
                "embed_new_products done: embedded=%d failed=%d", embedded_count, failed_count
            )
            return {
                "status": "success",
                "embedded": embedded_count,
                "total_found": total,
                "failed": failed_count,
            }
        finally:
            await conn.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        task_logger.error("embed_new_products failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="scraper.scheduler.detect_price_changes",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def detect_price_changes(self: Any) -> dict[str, Any]:
    """
    Celery task: report on price changes detected in the last 24 hours.

    Queries the ``price_changes`` table (populated by :func:`scrape_shopify_stores`
    during its weekly runs) and returns a summary of how many price/availability
    events occurred recently.

    Scheduled to run **daily** at 06:00 IL time via Celery beat.

    Returns:
        A dict with keys ``price_changes_last_24h`` and ``status``.
    """
    task_logger.info("Task started: detect_price_changes")

    import asyncpg
    from dotenv import load_dotenv
    load_dotenv()

    async def _run() -> dict[str, Any]:
        db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS count
                FROM price_changes
                WHERE detected_at > now() - INTERVAL '24 hours'
                """
            )
            count = row["count"] if row else 0
            task_logger.info("detect_price_changes: %d changes in last 24h", count)
            return {"status": "success", "price_changes_last_24h": count}
        except Exception as exc:
            # price_changes table may not exist yet (migration 0005 pending)
            task_logger.warning("detect_price_changes query failed: %s", exc)
            return {"status": "skipped", "reason": str(exc), "price_changes_last_24h": 0}
        finally:
            await conn.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        task_logger.error("detect_price_changes failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="scraper.scheduler.run_deduplication",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def run_deduplication(self: Any) -> dict:
    """
    Celery task: run product deduplication after embedding.

    Uses stored pgvector embeddings to find near-duplicate products
    (cosine similarity >= 0.95) and merges their store_products rows into
    the canonical product record.

    Requires migration 0008 (is_duplicate + canonical_product_id columns).
    Scheduled to run **weekly on Monday** at 06:00 IL time via Celery beat.

    Returns:
        A dict with keys ``groups_found``, ``products_merged``, and ``status``.
    """
    task_logger.info("Task started: run_deduplication")

    from normalization.deduplication import deduplicate_products

    try:
        return asyncio.run(deduplicate_products())
    except Exception as exc:
        task_logger.error("run_deduplication failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)
