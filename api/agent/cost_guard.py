"""api/agent/cost_guard.py — Daily LLM cost guard for the v2 agentic chat (W5).

Tracks cumulative USD spend across all requests for the current UTC day in a
Redis counter with 24h TTL. When the daily total exceeds `DAILY_COST_BUDGET_USD`
(env var, default $20.00), `/api/chat/v2` short-circuits with HTTP 503 +
Retry-After header set to seconds-until-midnight-UTC.

The W2 per-turn `cost_budget_usd` cap in `run_agent` is the FIRST line of
defense (protects against runaway loops within one turn). This daily guard
is the SECOND line: protects against a sustained traffic spike running up a
large bill before anyone notices.

Graceful degradation: if Redis is unavailable, the guard ALLOWS requests
through (fail-open) rather than blocking traffic on infrastructure failure.
The W2 per-turn cap still applies even when the daily counter is unreadable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def _today_key() -> str:
    """Redis key for today's UTC cumulative cost counter."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"findme:agent:daily_cost_usd:{today}"


def daily_budget_usd() -> float:
    """Configured daily budget. Override via DAILY_COST_BUDGET_USD env var."""
    raw = os.environ.get("DAILY_COST_BUDGET_USD", "20.0")
    try:
        return float(raw)
    except ValueError:
        logger.warning("cost_guard: invalid DAILY_COST_BUDGET_USD=%r, falling back to 20.0", raw)
        return 20.0


def seconds_until_midnight_utc() -> int:
    """How many seconds until 00:00 UTC tomorrow — used for Retry-After."""
    now = datetime.now(timezone.utc)
    tomorrow_midnight = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        .replace(day=now.day) if now.hour == 0 and now.minute == 0
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    # add a day in seconds — simpler than dateutil arithmetic
    next_midnight_ts = ((now.timestamp() // 86400) + 1) * 86400
    return max(0, int(next_midnight_ts - now.timestamp()))


async def current_day_cost_usd(redis: Optional[Redis]) -> float:
    """Read today's cumulative cost from Redis. Returns 0.0 on Redis error."""
    if redis is None:
        return 0.0
    try:
        raw = await redis.get(_today_key())
    except Exception as exc:  # noqa: BLE001 — fail-open on Redis errors
        logger.warning("cost_guard: read failed (%s) — allowing request", exc)
        return 0.0
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


async def register_cost(redis: Optional[Redis], cost_usd: float) -> None:
    """Add `cost_usd` to today's counter. Best-effort — silently ignores Redis errors."""
    if redis is None or cost_usd <= 0:
        return
    key = _today_key()
    try:
        await redis.incrbyfloat(key, cost_usd)
        # Refresh TTL so the key reliably expires after the day rolls over.
        # Use 25h to give a 1h grace window for late-arriving writes from
        # in-flight requests that started near midnight.
        await redis.expire(key, 25 * 60 * 60)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("cost_guard: write failed (%s) — counter not updated", exc)


async def is_over_budget(redis: Optional[Redis]) -> bool:
    """True iff today's cumulative cost has reached or exceeded the budget."""
    total = await current_day_cost_usd(redis)
    return total >= daily_budget_usd()
