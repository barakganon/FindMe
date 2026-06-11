"""tests/api/test_rate_limit.py — Tests for per-route rate limiting (Story 5.9 Workstream C).

Verifies:
  1. Rate-limit decorators are registered on all 5 target routes.
  2. Under the limit, requests return the expected non-429 status.
  3. Over the limit, requests return 429.

Implementation note on testing 429 deterministically
-----------------------------------------------------
slowapi stores counters in a backend (default: in-memory). During a test
session the limiter is shared across all tests via the `app` singleton
(imported once). Triggering a 429 deterministically requires either:
  (a) Many rapid requests (fragile — depends on limit string, e.g. "20/minute")
  (b) Monkeypatching limiter.enabled = False then re-enabling with a low limit.
  (c) Temporarily overriding `_route_limits` with a very tight limit ("1/minute").

We use approach (c): override the route's registered Limit objects with a
"1/day" string, make 2 requests with the same fake IP, and assert the second
returns 429. We restore original limits in teardown.

Anonymous users are tested throughout — rate limiting is per-IP, not per-auth.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from api.main import app
from api.dependencies import get_db, get_ai_client, get_redis, limiter
from api.agent.loop import AgentResult
from api.schemas import ChatRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def override_deps():
    """Override DB/AI/Redis FastAPI deps; clean up after."""

    async def _db():
        """Async generator dependency override yielding a mock DB session."""
        session = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = []
        execute_result.scalars.return_value.all.return_value = []
        execute_result.scalar_one.return_value = 0
        session.execute = AsyncMock(return_value=execute_result)
        yield session

    def _ai():
        return MagicMock()

    async def _redis():
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.incrbyfloat = AsyncMock(return_value=0.01)
        return mock_redis

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_ai_client] = _ai
    app.dependency_overrides[get_redis] = _redis
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Part 1: Decorator registration
# ---------------------------------------------------------------------------


def test_chat_route_has_rate_limit():
    """POST /api/chat has a registered rate limit."""
    assert "api.routes.chat.chat" in limiter._route_limits
    assert len(limiter._route_limits["api.routes.chat.chat"]) >= 1


def test_chat_v2_route_has_rate_limit():
    """POST /api/chat/v2 has a registered rate limit."""
    assert "api.routes.chat_v2.chat_v2" in limiter._route_limits
    assert len(limiter._route_limits["api.routes.chat_v2.chat_v2"]) >= 1


def test_chat_v2_stream_route_has_rate_limit():
    """POST /api/chat/v2/stream has a registered rate limit."""
    assert "api.routes.chat_v2_stream.chat_v2_stream" in limiter._route_limits
    assert len(limiter._route_limits["api.routes.chat_v2_stream.chat_v2_stream"]) >= 1


def test_search_route_has_rate_limit():
    """POST /api/search has a registered rate limit."""
    assert "api.routes.search.search_products" in limiter._route_limits
    assert len(limiter._route_limits["api.routes.search.search_products"]) >= 1


def test_stores_search_route_has_rate_limit():
    """POST /api/stores/search has a registered rate limit."""
    assert "api.routes.stores.search_stores" in limiter._route_limits
    assert len(limiter._route_limits["api.routes.stores.search_stores"]) >= 1


def test_all_rate_limited_routes_have_wrapped_endpoint():
    """All rate-limited routes have the limiter wrapper as their FastAPI endpoint."""
    import inspect

    rate_limited_paths = {
        "/api/chat", "/api/chat/v2", "/api/chat/v2/stream",
        "/api/search", "/api/stores/search",
    }
    for route in app.routes:
        path = getattr(route, "path", None)
        if path in rate_limited_paths:
            endpoint = getattr(route, "endpoint", None)
            assert endpoint is not None, f"{path} has no endpoint"
            assert hasattr(endpoint, "__wrapped__"), (
                f"{path} endpoint is not wrapped by @limiter.limit() — "
                "rate limiting will not be enforced"
            )


# ---------------------------------------------------------------------------
# Part 2: Under-limit requests succeed (non-429)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chat_under_limit_succeeds(override_deps):
    """POST /api/chat returns non-429 for a single anonymous request."""
    with patch("api.routes.chat._parse_intent") as mock_parse, \
         patch("api.routes.chat._compose_response") as mock_compose, \
         patch("api.routes.chat._run_product_search") as mock_search:
        from api.schemas import ParsedIntent
        mock_parse.return_value = AsyncMock(return_value=ParsedIntent(
            intent="clarify", voucher_network="buyme"
        ))()
        mock_parse.return_value = ParsedIntent(intent="clarify", voucher_network="buyme")
        mock_compose.return_value = "שאלה?"
        mock_search.return_value = []

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "test", "history": [], "voucher_network": "buyme"},
            )
    # Rate limit doesn't fire on first request — any non-429 is acceptable
    assert resp.status_code != 429


@pytest.mark.anyio
async def test_search_under_limit_succeeds(override_deps):
    """POST /api/search returns non-429 for a single anonymous request (mocked search).

    We short-circuit the handler by mocking the search cache to return a hit,
    which prevents any DB or Gemini call.
    """
    from api.schemas import SearchResponse, QueryProduct
    cached_response = SearchResponse(
        results=[],
        query_product=QueryProduct(
            raw_query="test",
            extracted_name=None,
            brand=None,
            estimated_price=None,
            extraction_success=False,
        ),
        total=0,
        total_available=0,
        page=1,
        page_size=10,
        exact_matches=0,
        similar_matches=0,
        search_time_ms=1.0,
    )
    with patch("api.routes.search.get_search_cache", new=AsyncMock(return_value=cached_response.model_dump())):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/search",
                json={"query": "test", "filters": {}},
            )
    assert resp.status_code != 429


@pytest.mark.anyio
async def test_stores_search_under_limit_succeeds(override_deps):
    """POST /api/stores/search returns non-429 for a single anonymous request.

    The override_deps fixture provides a mock DB session. The route is expected
    to return 200 (empty results) since no DB error occurs.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/api/stores/search",
            json={},
        )
    assert resp.status_code != 429


# ---------------------------------------------------------------------------
# Part 3: Over-limit requests return 429
# ---------------------------------------------------------------------------


@pytest.fixture
def tight_limit_on_chat():
    """
    Temporarily replace the chat route's registered Limit objects with a
    "1/day" limit so that a second request from the same IP hits 429.

    Restores original limits on teardown.
    """
    from slowapi.wrappers import LimitGroup, Limit
    from slowapi.util import get_remote_address

    key = "api.routes.chat.chat"
    original = limiter._route_limits.get(key, [])

    # Build a 1/day limit (will fire on the 2nd request)
    new_limits = list(
        LimitGroup("1/day", get_remote_address, None, False, None, None, None, 1, True)
    )
    limiter._route_limits[key] = new_limits
    yield
    limiter._route_limits[key] = original


@pytest.mark.anyio
async def test_chat_returns_429_when_limit_exceeded(override_deps, tight_limit_on_chat):
    """
    With a 1/day limit on POST /api/chat, the second request from the same
    fake IP should return HTTP 429.
    """
    with patch("api.routes.chat._parse_intent") as mock_parse, \
         patch("api.routes.chat._compose_response") as mock_compose:
        from api.schemas import ParsedIntent
        mock_parse.return_value = ParsedIntent(intent="clarify", voucher_network="buyme")
        mock_compose.return_value = "שאלה?"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Forwarded-For": "10.0.0.1"},
        ) as client:
            body = {"message": "test", "history": [], "voucher_network": "buyme"}
            r1 = await client.post("/api/chat", json=body)
            r2 = await client.post("/api/chat", json=body)

    # First request OK (or any non-429)
    assert r1.status_code != 429, f"First request should not be rate-limited, got {r1.status_code}"
    # Second request should be rate-limited
    assert r2.status_code == 429, f"Second request should be rate-limited (429), got {r2.status_code}"
