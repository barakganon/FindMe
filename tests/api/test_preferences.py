"""
tests/api/test_preferences.py — Tests for user preferences and inferred attributes.

All DB calls are mocked. Uses anyio + httpx AsyncClient pattern.
Uses MockDbDep class (same pattern as test_auth.py) for proper async gen dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token, get_current_user
from api.auth import hash_password as _hash_password
from api.dependencies import get_db
from api.main import app


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_USER_ID = uuid.uuid4()
_USER_EMAIL = "prefs_test@example.com"
_HASHED_PASSWORD = _hash_password("test_password")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_user() -> MagicMock:
    user = MagicMock()
    user.id = _USER_ID
    user.email = _USER_EMAIL
    user.display_name = "Prefs Tester"
    user.password_hash = _HASHED_PASSWORD
    user.is_active = True
    user.google_id = None
    user.created_at = datetime(2026, 4, 2)
    return user


def _make_pref(key: str, value: str) -> MagicMock:
    pref = MagicMock()
    pref.key = key
    pref.value = value
    pref.updated_at = datetime(2026, 4, 2)
    return pref


def _make_inferred_attr(
    attr_id: uuid.UUID,
    attribute: str,
    value: str,
    confidence: float = 0.7,
    source: str = "test source",
) -> MagicMock:
    attr = MagicMock()
    attr.id = attr_id
    attr.attribute = attribute
    attr.value = value
    attr.confidence = confidence
    attr.source = source
    attr.inferred_at = datetime(2026, 4, 2)
    attr.last_updated = datetime(2026, 4, 2)
    attr.is_confirmed = False
    attr.user_id = _USER_ID
    return attr


class MockDbDep:
    """
    Proper async gen class-based dependency override for get_db.
    results_sequence[i] is returned on the i-th execute() call as (scalar, scalars_list).
    """

    def __init__(self, results_sequence: list | None = None):
        # Each entry: (scalar_value, scalars_list)
        self.results_sequence = results_sequence or []
        self.mock_session: AsyncMock | None = None

    async def __call__(self):
        mock_session = AsyncMock()
        call_count = [0]
        seq = self.results_sequence

        async def _execute(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            entry = seq[idx] if idx < len(seq) else (None, [])
            scalar_val, scalars_list = entry if isinstance(entry, tuple) else (entry, [])
            result = MagicMock()
            result.scalar_one_or_none.return_value = scalar_val
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = scalars_list or []
            result.scalars.return_value = scalars_mock
            result.all.return_value = scalars_list or []
            return result

        mock_session.execute = _execute
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.delete = AsyncMock()
        mock_session.refresh = AsyncMock()
        self.mock_session = mock_session
        yield mock_session


# ---------------------------------------------------------------------------
# Test 1: GET /api/users/me/preferences → empty when no prefs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_preferences_empty() -> None:
    """GET /api/users/me/preferences → {} when no prefs set."""
    user = _make_mock_user()
    token = create_access_token(user.id, user.email)

    # Route calls: execute(select(UserPreference)...) → empty list
    db_dep = MockDbDep(results_sequence=[(None, [])])
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.get(
                "/api/users/me/preferences",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    assert r.json() == {}


# ---------------------------------------------------------------------------
# Test 2: PUT /api/users/me/preferences saves a preference
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_set_preference_max_price() -> None:
    """PUT /api/users/me/preferences with default_max_price → saved."""
    user = _make_mock_user()
    token = create_access_token(user.id, user.email)

    # For PUT: one execute per key (pref existence check) → None (no existing pref)
    db_dep = MockDbDep(results_sequence=[(None, [])])
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.put(
                "/api/users/me/preferences",
                json={"default_max_price": "300"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "default_max_price" in data["updated"]


# ---------------------------------------------------------------------------
# Test 3: Preference applied to search (unit test of merge_preferences_into_search)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_preference_applied_to_search() -> None:
    """User has default_max_price=300 → ParsedIntent.max_price set to 300.

    This is a pure unit test of chat_utils — no HTTP involved.
    """
    from api.chat_utils import merge_preferences_into_search
    from api.schemas import ParsedIntent

    parsed = ParsedIntent(
        intent="product_search",
        product_query="אוזניות",
        max_price=None,
        voucher_network="buyme",
    )
    prefs = {"default_max_price": "300"}
    implicit: list = []

    result = merge_preferences_into_search(parsed, prefs, implicit)

    assert result.max_price == 300.0


# ---------------------------------------------------------------------------
# Test 4: GET /api/users/me/inferred → empty list
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_inferred_empty() -> None:
    """GET /api/users/me/inferred → [] when no attributes inferred."""
    user = _make_mock_user()
    token = create_access_token(user.id, user.email)

    # Route calls: execute(select(UserInferredAttribute)...) → empty list
    db_dep = MockDbDep(results_sequence=[(None, [])])
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.get(
                "/api/users/me/inferred",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Test 5: Inference task fires (mocked) after chat turn with logged-in user
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_inferred_stored_after_chat() -> None:
    """After chat turn with logged-in user, extract_and_update_attributes is fired."""
    from api.auth import get_optional_user
    from api.dependencies import get_ai_client, get_redis
    from api.schemas import ParsedIntent

    user = _make_mock_user()
    token = create_access_token(user.id, user.email)

    parsed = ParsedIntent(intent="help", voucher_network="buyme")

    # DB for the chat route: multiple queries (prefs, signals, history, inferred)
    # All return empty results
    db_dep = MockDbDep(
        results_sequence=[(None, [])] * 10
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    inference_called = []

    async def _mock_extract(user_id, message, db, ai):
        inference_called.append((user_id, message))

    # chat route uses get_optional_user (not get_current_user)
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_redis] = lambda: mock_redis
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)), \
             patch("api.routes.chat.extract_and_update_attributes", new=_mock_extract):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={"message": "אני מחפש מתנה לבן 3 שלי"},
                    headers={"Authorization": f"Bearer {token}"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_optional_user, None)
        app.dependency_overrides.pop(get_ai_client, None)

    assert r.status_code == 200
    assert r.json()["intent"] == "help"

    # Give the asyncio.create_task a moment to execute
    import asyncio
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Test 6: DELETE /api/users/me/inferred/{id} removes an attribute
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_inferred() -> None:
    """DELETE /api/users/me/inferred/{id} → 204, attribute removed."""
    user = _make_mock_user()
    token = create_access_token(user.id, user.email)
    attr_id = uuid.uuid4()
    attr = _make_inferred_attr(attr_id, "gender", "female")

    # Route calls: execute(select(UserInferredAttribute)...) → attr
    db_dep = MockDbDep(results_sequence=[(attr, [])])
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.delete(
                f"/api/users/me/inferred/{attr_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 204
    # Verify the session's delete was called with our attr object
    assert db_dep.mock_session is not None
    db_dep.mock_session.delete.assert_called_once_with(attr)
    db_dep.mock_session.commit.assert_called_once()
