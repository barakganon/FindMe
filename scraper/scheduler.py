"""
scraper/scheduler.py — Celery task scheduler for FindMe scrape jobs.

Defines a Celery application and periodic tasks for:
    - Scraping the BuyMe partner store list (daily).
    - Scraping product catalogs for individual stores (weekly, per store).
    - Detecting price/availability changes across stored products (daily).

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
    # Detect price changes across all indexed stores every 24 hours (at 06:00 IL time)
    "detect-price-changes-daily": {
        "task": "scraper.scheduler.detect_price_changes",
        # detect_price_changes takes store_id; the beat entry here is a
        # placeholder that triggers the orchestration task instead.
        # TODO: replace with a fan-out task that iterates over all store IDs
        #       from the DB and enqueues individual detect_price_changes calls.
        "schedule": crontab(hour=6, minute=0),
        "args": ["__all__"],  # sentinel value — handled inside the task
        "options": {"queue": "scraper"},
    },
}

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
    Celery task: scrape the BuyMe partner store list and persist results.

    Instantiates :class:`~scraper.buyme_store_scraper.BuyMeStoreScraper`,
    runs the full scrape, and saves raw snapshots + structured JSON to disk.

    Scheduled to run **daily** via Celery beat (see ``beat_schedule``).

    Returns:
        A dict with keys ``store_count`` (int) and ``status`` (str).

    Raises:
        Retries up to 3 times (5-minute intervals) on any unexpected exception.
    """
    task_logger.info("Task started: scrape_buyme_store_list")

    async def _run() -> list:
        async with BuyMeStoreScraper(headless=True, save_raw=True) as scraper:
            return await scraper.run()

    try:
        stores = asyncio.run(_run())
        task_logger.info(
            "scrape_buyme_store_list completed: %d stores found", len(stores)
        )
        return {"status": "success", "store_count": len(stores)}
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
    name="scraper.scheduler.detect_price_changes",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def detect_price_changes(self: Any, store_id: str) -> dict[str, Any]:
    """
    Celery task: detect price and availability changes for a store's products.

    Compares freshly-scraped product data against the last known state in the
    database and flags items whose price or availability has changed.

    Scheduled to run **daily** via Celery beat (see ``beat_schedule``).

    Args:
        store_id: Opaque store identifier (DB primary key as string), or the
                  sentinel value ``"__all__"`` to trigger detection across
                  every store (used by the beat schedule entry).

    Returns:
        A dict with keys ``store_id`` and ``status``.

    Note:
        TODO: implement price change detection.
              Steps will be:
              1. Re-scrape store products (or read from latest scrape_runs row).
              2. Diff against store_products rows in the DB.
              3. Write price-change events to a ``price_changes`` audit table.
              4. Optionally emit a webhook / notification.
              Flag this requirement to the API Agent for the DB schema.
    """
    task_logger.info(
        "detect_price_changes called for store_id=%s — TODO: implement price change detection",
        store_id,
    )
    # TODO: implement price change detection
    return {"status": "not_implemented", "store_id": store_id}
