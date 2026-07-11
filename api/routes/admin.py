"""
api/routes/admin.py — System health endpoint for internal monitoring.
No authentication required (internal use only).
"""
from __future__ import annotations

import logging
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, get_redis
from api.agent.cost_guard import (
    current_day_cost_usd,
    daily_budget_usd,
    is_over_budget,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin"])

# Keep in sync with _VERSION in api/main.py
_APP_VERSION = "0.1.0"


@router.get("/admin/health")
async def health(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    # DB stats & latency
    start = datetime.now(timezone.utc)
    result = await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM products) AS products_total,
            (SELECT COUNT(*) FROM products WHERE embedding_vector IS NOT NULL) AS products_embedded,
            (SELECT COUNT(*) FROM stores) AS stores_total,
            (SELECT COUNT(*) FROM stores WHERE lat IS NOT NULL) AS stores_geocoded
    """))
    row = result.fetchone()
    db_latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    # Redis health & latency
    start = datetime.now(timezone.utc)
    try:
        await redis.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "unavailable"
    redis_latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000

    # Last 5 scrape runs
    runs_result = await db.execute(text("""
        SELECT store_id, status, items_scraped, started_at, finished_at
        FROM scrape_runs
        ORDER BY started_at DESC
        LIMIT 5
    """))
    runs = [
        {
            "store_id": str(r[0]) if r[0] else None,
            "status": r[1],
            "items_scraped": r[2],
            "started_at": r[3].isoformat() if r[3] else None,
            "finished_at": r[4].isoformat() if r[4] else None,
        }
        for r in runs_result.fetchall()
    ]

    products_total = row[0] or 0
    products_embedded = row[1] or 0
    coverage = round(products_embedded / products_total * 100, 1) if products_total > 0 else 0.0

    return {
        "database": {"status": "ok", "latency_ms": round(db_latency, 2)},
        "redis": {"status": redis_status, "latency_ms": round(redis_latency, 2)},
        "products_total": products_total,
        "products_embedded": products_embedded,
        "embedding_coverage_pct": coverage,
        "stores_total": row[2] or 0,
        "stores_geocoded": row[3] or 0,
        "recent_scrape_runs": runs,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/admin/health/detailed")
async def health_detailed(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    redis_ok = False
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "version": _APP_VERSION,
        "environment": os.getenv("ENV", "development"),
        "system": {
            "platform": platform.platform(),
            "python": sys.version,
        },
        "components": {
            "database": {"ok": db_ok},
            "redis": {"ok": redis_ok},
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/admin/cost-summary")
async def cost_summary(
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Return today's cost-guard state for operator visibility.

    Useful for answering "did we get close to / trip the daily budget today?".
    Degrades gracefully when Redis is unavailable — never raises, always 200.

    Note: per-session cost enumeration is intentionally omitted. Iterating over
    all session keys would require a Redis SCAN (O(N) over the keyspace) which
    is out of scope for a lightweight health endpoint.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget = daily_budget_usd()

    redis_available = True
    daily_cost: float = 0.0
    over_budget: bool = False

    try:
        daily_cost = await current_day_cost_usd(redis)
        over_budget = await is_over_budget(redis)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully like health endpoints
        logger.warning("cost_summary: Redis read failed (%s) — returning degraded response", exc)
        redis_available = False

    if redis is None:
        redis_available = False

    if budget > 0:
        pct_used = round(daily_cost / budget * 100, 2)
    else:
        pct_used = 0.0  # guard div-by-zero if budget is misconfigured as 0

    return {
        "date": today,
        "daily_cost_usd": daily_cost,
        "daily_budget_usd": budget,
        "daily_pct_used": pct_used,
        "daily_over_budget": over_budget,
        "redis_available": redis_available,
    }
