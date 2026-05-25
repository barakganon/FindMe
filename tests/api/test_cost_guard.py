"""tests/api/test_cost_guard.py — W5 cost guard unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.agent.cost_guard import (
    current_day_cost_usd,
    daily_budget_usd,
    is_over_budget,
    register_cost,
    seconds_until_midnight_utc,
)


def test_default_budget_when_env_unset(monkeypatch):
    monkeypatch.delenv("DAILY_COST_BUDGET_USD", raising=False)
    assert daily_budget_usd() == 20.0


def test_budget_from_env(monkeypatch):
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "5.5")
    assert daily_budget_usd() == 5.5


def test_budget_falls_back_on_invalid(monkeypatch):
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "not a number")
    assert daily_budget_usd() == 20.0


def test_seconds_until_midnight_positive():
    n = seconds_until_midnight_utc()
    assert 0 <= n <= 86400


@pytest.mark.anyio
async def test_current_cost_zero_when_redis_none():
    assert await current_day_cost_usd(None) == 0.0


@pytest.mark.anyio
async def test_current_cost_zero_when_key_missing():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    assert await current_day_cost_usd(redis) == 0.0


@pytest.mark.anyio
async def test_current_cost_reads_redis_value():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="3.14")
    assert await current_day_cost_usd(redis) == 3.14


@pytest.mark.anyio
async def test_current_cost_fail_open_on_redis_error():
    """Redis failure must NOT block traffic — return 0 to keep `is_over_budget` False."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    assert await current_day_cost_usd(redis) == 0.0


@pytest.mark.anyio
async def test_register_cost_increments_and_sets_ttl():
    redis = AsyncMock()
    redis.incrbyfloat = AsyncMock()
    redis.expire = AsyncMock()
    await register_cost(redis, 0.05)
    redis.incrbyfloat.assert_called_once()
    args = redis.incrbyfloat.call_args
    assert args.args[0].startswith("findme:agent:daily_cost_usd:")
    assert args.args[1] == 0.05
    redis.expire.assert_called_once()
    # TTL is 25h
    assert redis.expire.call_args.args[1] == 25 * 60 * 60


@pytest.mark.anyio
async def test_register_cost_noop_for_zero():
    redis = AsyncMock()
    redis.incrbyfloat = AsyncMock()
    await register_cost(redis, 0.0)
    redis.incrbyfloat.assert_not_called()


@pytest.mark.anyio
async def test_register_cost_silent_on_redis_error():
    redis = AsyncMock()
    redis.incrbyfloat = AsyncMock(side_effect=ConnectionError("redis down"))
    # Should NOT raise
    await register_cost(redis, 0.05)


@pytest.mark.anyio
async def test_is_over_budget_false_under_limit(monkeypatch):
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "10.0")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="5.0")
    assert await is_over_budget(redis) is False


@pytest.mark.anyio
async def test_is_over_budget_true_at_limit(monkeypatch):
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "10.0")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="10.0")
    assert await is_over_budget(redis) is True


@pytest.mark.anyio
async def test_is_over_budget_true_above_limit(monkeypatch):
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "10.0")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="15.5")
    assert await is_over_budget(redis) is True


@pytest.mark.anyio
async def test_is_over_budget_fail_open_on_redis_down(monkeypatch):
    """Critical: Redis-down must NOT trip the over-budget circuit breaker."""
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "10.0")
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError())
    assert await is_over_budget(redis) is False
