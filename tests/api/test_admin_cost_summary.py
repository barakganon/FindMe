"""tests/api/test_admin_cost_summary.py — Tests for GET /api/admin/cost-summary.

All Redis interactions are mocked — no real Redis required (CLAUDE.md).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from api.main import app
from api.dependencies import get_redis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis_mock(daily_cost: float) -> AsyncMock:
    """Build an AsyncMock Redis whose .get() returns the given daily cost."""
    redis = AsyncMock()
    # cost_guard helpers call redis.get(key) — return the encoded float value
    redis.get = AsyncMock(return_value=str(daily_cost).encode())
    return redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cost_summary_normal_case() -> None:
    """Normal case: Redis returns a known cost → correct pct_used + over_budget=False."""
    mock_redis = _make_redis_mock(daily_cost=5.0)

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[get_redis] = _override_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/cost-summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    body = response.json()

    assert "date" in body
    assert body["daily_cost_usd"] == pytest.approx(5.0, abs=0.01)
    assert body["daily_budget_usd"] == pytest.approx(20.0, abs=0.01)
    assert body["daily_pct_used"] == pytest.approx(25.0, abs=0.01)
    assert body["daily_over_budget"] is False
    assert body["redis_available"] is True


@pytest.mark.anyio
async def test_cost_summary_over_budget() -> None:
    """When daily cost >= budget the over_budget flag is True."""
    mock_redis = _make_redis_mock(daily_cost=20.0)

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[get_redis] = _override_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/cost-summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    body = response.json()
    assert body["daily_over_budget"] is True
    assert body["daily_pct_used"] == pytest.approx(100.0, abs=0.01)
    assert body["redis_available"] is True


@pytest.mark.anyio
async def test_cost_summary_redis_unavailable() -> None:
    """When Redis is None (unavailable) the endpoint still returns 200, redis_available=False."""

    async def _override_redis():
        return None  # simulate Redis being down

    app.dependency_overrides[get_redis] = _override_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/cost-summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    body = response.json()
    assert body["redis_available"] is False
    assert body["daily_cost_usd"] == pytest.approx(0.0)
    assert body["daily_over_budget"] is False


@pytest.mark.anyio
async def test_cost_summary_redis_raises() -> None:
    """When Redis.get() raises an exception the endpoint degrades gracefully (200, no 500)."""
    bad_redis = AsyncMock()
    bad_redis.get = AsyncMock(side_effect=ConnectionError("redis is down"))

    async def _override_redis():
        return bad_redis

    app.dependency_overrides[get_redis] = _override_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/cost-summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    body = response.json()
    # cost_guard.current_day_cost_usd catches exceptions and returns 0.0
    assert body["daily_cost_usd"] == pytest.approx(0.0)
    assert body["redis_available"] is True  # redis object exists; cost_guard swallowed the error


@pytest.mark.anyio
async def test_cost_summary_div_by_zero_guard() -> None:
    """When DAILY_COST_BUDGET_USD=0 pct_used should be 0.0 (not raise ZeroDivisionError)."""
    mock_redis = _make_redis_mock(daily_cost=5.0)

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[get_redis] = _override_redis
    try:
        with patch.dict("os.environ", {"DAILY_COST_BUDGET_USD": "0"}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/admin/cost-summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    body = response.json()
    assert body["daily_budget_usd"] == pytest.approx(0.0)
    assert body["daily_pct_used"] == pytest.approx(0.0)


@pytest.mark.anyio
async def test_cost_summary_response_shape() -> None:
    """Response includes all required fields with correct types."""
    mock_redis = _make_redis_mock(daily_cost=1.23)

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[get_redis] = _override_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/cost-summary")
    finally:
        app.dependency_overrides.pop(get_redis, None)

    body = response.json()
    required_fields = {
        "date", "daily_cost_usd", "daily_budget_usd",
        "daily_pct_used", "daily_over_budget", "redis_available",
    }
    assert required_fields.issubset(body.keys()), f"Missing fields: {required_fields - body.keys()}"
    assert isinstance(body["date"], str)
    assert isinstance(body["daily_cost_usd"], float)
    assert isinstance(body["daily_budget_usd"], float)
    assert isinstance(body["daily_pct_used"], float)
    assert isinstance(body["daily_over_budget"], bool)
    assert isinstance(body["redis_available"], bool)
