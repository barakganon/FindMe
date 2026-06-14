"""api/agent/cost_guard.py — Daily + per-session LLM cost guard for v2 (W5/W9).

Tracks cumulative USD spend across all requests for the current UTC day in a
Redis counter with 24h TTL. When the daily total exceeds the configured daily
budget, `/api/chat/v2` short-circuits with HTTP 503 + Retry-After header set
to seconds-until-midnight-UTC.

Additionally (W9), tracks per-session spend in a Redis counter with 2h TTL
(matching session memory TTL). When the session total exceeds the per-session
budget, the route circuit-breaks to `/api/chat` with HTTP 503.

The W2 per-turn `cost_budget_usd` cap in `run_agent` is the FIRST line of
defense (protects against runaway loops within one turn). This daily guard
is the SECOND line; the per-session cap is the THIRD.

Graceful degradation: if Redis is unavailable, all guards ALLOW requests
through (fail-open) rather than blocking traffic on infrastructure failure.
The W2 per-turn cap still applies even when Redis counters are unreadable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Session TTL — must match session_memory.py SESSION_TTL_SECONDS
_SESSION_TTL_SECONDS = 7200  # 2 hours


def _today_key() -> str:
    """Redis key for today's UTC cumulative cost counter."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"findme:agent:daily_cost_usd:{today}"


def _session_key(session_id: str) -> str:
    """Redis key for per-session cumulative cost counter."""
    return f"findme:agent:session_cost_usd:{session_id}"


def cost_cap_key(session_id: Optional[str], client_host: Optional[str]) -> str:
    """Key the per-session cost cap should accumulate against.

    Logged-in / header-bearing clients use their stable ``session_id``. Anonymous
    clients that omit ``X-Session-ID`` would otherwise have NO per-session ceiling
    (only the daily + per-turn caps), so we fall back to a per-IP bucket. Requires
    uvicorn ``--proxy-headers`` so ``client_host`` is the real IP behind Render's
    proxy, not the shared proxy IP. Falls back to a single shared bucket only when
    the IP is also unknown — still better than no cap.
    """
    if session_id:
        return session_id
    return f"ip:{client_host or 'unknown'}"


def daily_budget_usd() -> float:
    """Configured daily budget. Override via DAILY_COST_BUDGET_USD env var.

    Reads directly from the environment so that tests can monkeypatch without
    invalidating the Settings lru_cache.
    """
    raw = os.environ.get("DAILY_COST_BUDGET_USD", "20.0")
    try:
        return float(raw)
    except ValueError:
        logger.warning("cost_guard: invalid DAILY_COST_BUDGET_USD=%r, falling back to 20.0", raw)
        return 20.0


def session_budget_usd() -> float:
    """Configured per-session budget. Override via PER_SESSION_COST_BUDGET_USD env var.

    Reads directly from the environment so that tests can monkeypatch without
    invalidating the Settings lru_cache. Default matches Settings.per_session_cost_budget_usd.
    """
    raw = os.environ.get("PER_SESSION_COST_BUDGET_USD", "0.50")
    try:
        return float(raw)
    except ValueError:
        logger.warning("cost_guard: invalid PER_SESSION_COST_BUDGET_USD=%r, falling back to 0.50", raw)
        return 0.50


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


# ---------------------------------------------------------------------------
# Per-session cost tracking (W9)
# ---------------------------------------------------------------------------


async def current_session_cost_usd(redis: Optional[Redis], session_id: str) -> float:
    """Read the session's cumulative cost from Redis. Returns 0.0 on any error."""
    if redis is None or not session_id:
        return 0.0
    try:
        raw = await redis.get(_session_key(session_id))
    except Exception as exc:  # noqa: BLE001 — fail-open on Redis errors
        logger.warning("cost_guard: session read failed (%s) — allowing request", exc)
        return 0.0
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


async def register_session_cost(redis: Optional[Redis], session_id: str, cost_usd: float) -> None:
    """Add `cost_usd` to the session's counter. Best-effort — silently ignores Redis errors."""
    if redis is None or not session_id or cost_usd <= 0:
        return
    key = _session_key(session_id)
    try:
        await redis.incrbyfloat(key, cost_usd)
        # Refresh TTL to keep the window sliding with activity.
        await redis.expire(key, _SESSION_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("cost_guard: session write failed (%s) — counter not updated", exc)


async def is_session_over_budget(
    redis: Optional[Redis], session_id: str, budget_usd: float
) -> bool:
    """True iff this session's cumulative cost has reached or exceeded `budget_usd`."""
    total = await current_session_cost_usd(redis, session_id)
    return total >= budget_usd
