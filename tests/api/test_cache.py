"""
tests/api/test_cache.py — Tests for Redis caching of search results and parsed intents.

Uses a simple in-memory FakeRedis to avoid a live Redis dependency.
Tests verify that:
  - Cache miss causes the backing function (Gemini) to be called.
  - Cache hit skips the backing function entirely.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.cache import (
    get_intent_cache,
    get_search_cache,
    set_intent_cache,
    set_search_cache,
    _intent_key,
    _search_key,
)
from api.dependencies import get_db, get_redis, get_settings, Settings, get_settings, Settings
from api.main import app
from api.schemas import ParsedIntent


# ---------------------------------------------------------------------------
# In-memory fake Redis
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async-compatible Redis fake backed by a plain dict."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self._ttls[key] = ttl

    async def ping(self) -> bool:
        return True

    def clear(self):
        self._store.clear()
        self._ttls.clear()

    def last_ttl(self, key: str) -> int | None:
        """Return the TTL used the last time setex was called for this key."""
        return self._ttls.get(key)


# ---------------------------------------------------------------------------
# Helper: mock DB session that is compatible with chat and search routes
# ---------------------------------------------------------------------------


def _make_mock_db():
    mock_session = AsyncMock()
    mappings_mock = MagicMock()
    mappings_mock.all.return_value = []
    execute_result = MagicMock()
    execute_result.mappings.return_value = mappings_mock
    execute_result.all.return_value = []
    execute_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    execute_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=execute_result)
    return mock_session


async def _mock_db_gen():
    yield _make_mock_db()


# ---------------------------------------------------------------------------
# Unit-level tests for cache.py functions (no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_cache_miss() -> None:
    """get_search_cache on empty FakeRedis returns None (cache miss)."""
    redis = FakeRedis()
    result = await get_search_cache(redis, "אוזניות", {"max_price": 300})
    assert result is None


@pytest.mark.anyio
async def test_search_cache_hit() -> None:
    """After set_search_cache, get_search_cache returns the stored value."""
    redis = FakeRedis()
    query = "אוזניות סוני"
    filters = {"max_price": 500, "city": None}
    payload = {"results": [{"name": "Sony WH1000"}], "total": 1}

    # Initially a miss
    miss = await get_search_cache(redis, query, filters)
    assert miss is None

    # Store it
    await set_search_cache(redis, query, filters, payload, ttl=60)

    # Now a hit
    hit = await get_search_cache(redis, query, filters)
    assert hit is not None
    assert hit["total"] == 1
    assert hit["results"][0]["name"] == "Sony WH1000"


@pytest.mark.anyio
async def test_intent_cache_miss() -> None:
    """get_intent_cache on empty FakeRedis returns None (cache miss)."""
    redis = FakeRedis()
    result = await get_intent_cache(redis, "מסעדות בתל אביב")
    assert result is None


@pytest.mark.anyio
async def test_intent_cache_hit() -> None:
    """After set_intent_cache, get_intent_cache returns the stored ParsedIntent dict."""
    redis = FakeRedis()
    message = "מסעדות בתל אביב"
    parsed = ParsedIntent(
        intent="store_search",
        store_type="restaurant",
        city="תל אביב",
        voucher_network="buyme",
    )
    parsed_dict = parsed.model_dump()

    # Initially a miss
    miss = await get_intent_cache(redis, message)
    assert miss is None

    # Store the parsed intent
    await set_intent_cache(redis, message, parsed_dict, ttl=120)

    # Now a hit
    hit = await get_intent_cache(redis, message)
    assert hit is not None
    assert hit["intent"] == "store_search"
    assert hit["city"] == "תל אביב"
    assert hit["store_type"] == "restaurant"


# ---------------------------------------------------------------------------
# Integration-level: verify Gemini is NOT called on intent cache hit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_intent_cache_prevents_llm_call() -> None:
    """
    When the intent cache is primed, _parse_intent should return the cached
    ParsedIntent without calling the LLM at all.
    """
    from api.routes.chat import _parse_intent

    redis = FakeRedis()
    message = "אוזניות סוני"

    # Pre-populate the cache
    cached_parsed = ParsedIntent(
        intent="product_search",
        product_query="אוזניות סוני",
        brand="Sony",
        voucher_network="buyme",
    )
    await set_intent_cache(redis, message, cached_parsed.model_dump())

    # Create a mock AI client that should NOT be called
    mock_ai = AsyncMock()
    mock_ai.chat.completions.create = AsyncMock(side_effect=AssertionError("LLM should not be called on cache hit"))

    result = await _parse_intent(
        message=message,
        history=[],
        session_context=None,
        client=mock_ai,
        redis=redis,
    )

    # LLM was never called (would have raised AssertionError if it was)
    assert result.intent == "product_search"
    assert result.product_query == "אוזניות סוני"
    assert result.brand == "Sony"


# ---------------------------------------------------------------------------
# Integration-level: verify Gemini IS called on cache miss
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_intent_cache_miss_calls_llm() -> None:
    """
    When the intent cache is empty, _parse_intent must call the LLM and then
    store the result in the cache.
    """
    from api.routes.chat import _parse_intent

    redis = FakeRedis()
    message = "אוזניות בוז"

    # Verify cache is empty first
    assert await get_intent_cache(redis, message) is None

    # Build mock AI that returns valid JSON for product_search
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "intent": "product_search",
        "product_query": "אוזניות בוז",
        "brand": "Bose",
        "max_price": None,
        "city": None,
        "location_hint": None,
        "needs_user_location": False,
        "store_type": None,
        "voucher_network": "buyme",
    })
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_ai = AsyncMock()
    mock_ai.chat.completions.create = AsyncMock(return_value=mock_completion)

    result = await _parse_intent(
        message=message,
        history=[],
        session_context=None,
        client=mock_ai,
        redis=redis,
    )

    # LLM was called
    assert mock_ai.chat.completions.create.call_count == 1

    # Result is correct
    assert result.intent == "product_search"
    assert result.brand == "Bose"

    # Cache now has the result
    cached = await get_intent_cache(redis, message)
    assert cached is not None
    assert cached["intent"] == "product_search"


# ---------------------------------------------------------------------------
# TTL-from-Settings tests (Workstream B — env-driven cache TTLs)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_search_cache_uses_settings_ttl() -> None:
    """set_search_cache with no explicit ttl uses Settings.search_cache_ttl."""
    redis = FakeRedis()
    query = "כרטיס מתנה"
    filters: dict = {}
    payload = {"results": [], "total": 0}

    mock_settings = Settings(search_cache_ttl=555, intent_cache_ttl=111)
    with patch("api.cache.get_settings", return_value=mock_settings):
        await set_search_cache(redis, query, filters, payload)

    key = _search_key(query, filters)
    assert redis.last_ttl(key) == 555


@pytest.mark.anyio
async def test_set_search_cache_explicit_ttl_overrides_settings() -> None:
    """An explicit ttl kwarg takes precedence over the Settings value."""
    redis = FakeRedis()
    query = "כרטיס מתנה"
    filters: dict = {}
    payload = {"results": [], "total": 0}

    mock_settings = Settings(search_cache_ttl=555, intent_cache_ttl=111)
    with patch("api.cache.get_settings", return_value=mock_settings):
        await set_search_cache(redis, query, filters, payload, ttl=42)

    key = _search_key(query, filters)
    assert redis.last_ttl(key) == 42


@pytest.mark.anyio
async def test_set_intent_cache_uses_settings_ttl() -> None:
    """set_intent_cache with no explicit ttl uses Settings.intent_cache_ttl."""
    redis = FakeRedis()
    message = "מסעדות בירושלים"
    payload = {"intent": "store_search", "city": "ירושלים"}

    mock_settings = Settings(search_cache_ttl=555, intent_cache_ttl=777)
    with patch("api.cache.get_settings", return_value=mock_settings):
        await set_intent_cache(redis, message, payload)

    key = _intent_key(message)
    assert redis.last_ttl(key) == 777


@pytest.mark.anyio
async def test_set_intent_cache_explicit_ttl_overrides_settings() -> None:
    """An explicit ttl kwarg takes precedence over the Settings value."""
    redis = FakeRedis()
    message = "מסעדות בירושלים"
    payload = {"intent": "store_search", "city": "ירושלים"}

    mock_settings = Settings(search_cache_ttl=555, intent_cache_ttl=777)
    with patch("api.cache.get_settings", return_value=mock_settings):
        await set_intent_cache(redis, message, payload, ttl=99)

    key = _intent_key(message)
    assert redis.last_ttl(key) == 99
