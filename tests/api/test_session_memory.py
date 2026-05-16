"""tests/api/test_session_memory.py — W3 session memory unit tests.

Redis is fully mocked. Covers session-id derivation, save/load round-trip,
Redis-down graceful degradation, anonymous-without-header fallback.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.agent.session_memory import (
    SessionState,
    derive_session_id,
    load_session_state,
    save_session_state,
)


# ---------------------------------------------------------------------------
# Session ID derivation
# ---------------------------------------------------------------------------


def test_session_id_user_takes_precedence():
    user = SimpleNamespace(id="user-abc-123")
    assert derive_session_id(user, "header-uuid") == "user:user-abc-123"


def test_session_id_anonymous_with_header():
    assert derive_session_id(None, "uuid-xyz") == "anon:uuid-xyz"


def test_session_id_anonymous_no_header_returns_none():
    assert derive_session_id(None, None) is None


def test_session_id_user_without_id_falls_back_to_header():
    user = SimpleNamespace(id=None)
    assert derive_session_id(user, "header-fallback") == "anon:header-fallback"


# ---------------------------------------------------------------------------
# load_session_state
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_load_empty_when_no_session_id():
    redis = AsyncMock()
    state = await load_session_state(redis, None)
    assert state.is_empty()
    # Should NOT have touched Redis
    redis.get.assert_not_called()


@pytest.mark.anyio
async def test_load_empty_when_redis_is_none():
    state = await load_session_state(None, "user:abc")
    assert state.is_empty()


@pytest.mark.anyio
async def test_load_empty_when_key_missing():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    state = await load_session_state(redis, "user:abc")
    assert state.is_empty()


@pytest.mark.anyio
async def test_load_returns_state_when_present():
    payload = json.dumps({
        "last_product_results": [{"id": "p1", "name": "Sony XM5"}],
        "last_store_results": [],
        "last_user_message": "אוזניות סוני",
        "last_assistant_message": "מצאתי",
        "updated_at": "2026-05-16T10:00:00+00:00",
    })
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=payload)
    state = await load_session_state(redis, "user:abc")
    assert not state.is_empty()
    assert state.last_user_message == "אוזניות סוני"
    assert len(state.last_product_results) == 1
    assert state.last_product_results[0]["name"] == "Sony XM5"


@pytest.mark.anyio
async def test_load_returns_empty_on_redis_error():
    """Redis exception must not propagate — chat continues without memory."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    state = await load_session_state(redis, "user:abc")
    assert state.is_empty()


@pytest.mark.anyio
async def test_load_returns_empty_on_corrupt_json():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="not json {{{")
    state = await load_session_state(redis, "user:abc")
    assert state.is_empty()


# ---------------------------------------------------------------------------
# save_session_state
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_save_noop_when_no_session_id():
    redis = AsyncMock()
    await save_session_state(
        redis, None,
        product_results=[], store_results=[],
        user_message="x", assistant_message="y",
    )
    redis.setex.assert_not_called()


@pytest.mark.anyio
async def test_save_persists_with_ttl():
    redis = AsyncMock()
    redis.setex = AsyncMock()
    await save_session_state(
        redis, "user:abc",
        product_results=[],
        store_results=[],
        user_message="אוזניות",
        assistant_message="מצאתי",
    )
    redis.setex.assert_called_once()
    call = redis.setex.call_args
    key, ttl, payload = call.args
    assert key == "findme:agent:session:user:abc"
    assert ttl == 60 * 60 * 2  # 2 hours
    parsed = json.loads(payload)
    assert parsed["last_user_message"] == "אוזניות"
    assert parsed["last_assistant_message"] == "מצאתי"


@pytest.mark.anyio
async def test_save_noop_on_redis_error():
    """Redis save failure must NOT raise — degrades silently."""
    redis = AsyncMock()
    redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))
    # Should not raise
    await save_session_state(
        redis, "user:abc",
        product_results=[], store_results=[],
        user_message="x", assistant_message="y",
    )


@pytest.mark.anyio
async def test_save_serializes_pydantic_results():
    """ProductResult/StoreResult instances must serialize cleanly."""
    from api.schemas import ProductResult, StoreInfo

    store = StoreInfo(
        id="s1", name_he="חנות", name_en=None, buyme_url=None,
        is_online=True, city="ת״א", lat=None, lng=None, distance_km=None,
    )
    product = ProductResult(
        product_id="p1", canonical_name="Sony XM5", brand="Sony", category_path=None,
        store=store, price=1299.0, currency="ILS", availability=True,
        product_url=None, match_score=0.92,
    )
    redis = AsyncMock()
    redis.setex = AsyncMock()
    await save_session_state(
        redis, "user:abc",
        product_results=[product], store_results=[],
        user_message="אוזניות", assistant_message="ok",
    )
    call = redis.setex.call_args
    payload = json.loads(call.args[2])
    assert payload["last_product_results"][0]["canonical_name"] == "Sony XM5"
    assert payload["last_product_results"][0]["price"] == 1299.0
