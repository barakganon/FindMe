"""
tests/api/test_auth.py — Tests for auth routes: register, login, get_me, import_session.

All DB calls are mocked — no live database required.
Uses anyio + httpx AsyncClient (same pattern as test_chat.py).

Key pattern: MockDbDep is a class with async __call__ using yield (async gen function),
which FastAPI correctly recognizes as an async generator dependency.
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
_USER_EMAIL = "test@example.com"
_USER_PASSWORD = "secret123"
_USER_DISPLAY_NAME = "Test User"

# Pre-compute bcrypt hash once at module load time (slow op, do it once)
_HASHED_PASSWORD = _hash_password(_USER_PASSWORD)


# ---------------------------------------------------------------------------
# Helper: mock User ORM object
# ---------------------------------------------------------------------------


def _make_mock_user(
    user_id: uuid.UUID = _USER_ID,
    email: str = _USER_EMAIL,
    display_name: str = _USER_DISPLAY_NAME,
    password_hash: str | None = None,
    is_active: bool = True,
) -> MagicMock:
    """Build a mock User ORM object that looks real enough for auth logic."""
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.display_name = display_name
    user.password_hash = password_hash if password_hash is not None else _HASHED_PASSWORD
    user.is_active = is_active
    user.google_id = None
    user.created_at = datetime(2026, 4, 2, 12, 0, 0)
    return user


# ---------------------------------------------------------------------------
# Helper: MockDbDep — async generator dependency class
# ---------------------------------------------------------------------------


class MockDbDep:
    """
    FastAPI dependency override for get_db.

    Must be a class with async __call__ that yields so FastAPI correctly
    identifies it as an async generator dependency (is_async_gen_callable == True).
    The scalar_sequence controls what scalar_one_or_none() returns on successive
    execute() calls.
    """

    def __init__(self, scalar_sequence: list | None = None, refresh_fn=None):
        self.scalar_sequence = scalar_sequence or []
        self.refresh_fn = refresh_fn  # optional async fn(obj) called on refresh

    async def __call__(self):
        mock_session = AsyncMock()
        call_count = [0]
        seq = self.scalar_sequence

        async def _execute(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            scalar_val = seq[idx] if idx < len(seq) else None
            result.scalar_one_or_none.return_value = scalar_val
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
            result.all.return_value = []
            return result

        async def _refresh(obj):
            if self.refresh_fn:
                await self.refresh_fn(obj)
            # Default: ensure the object has basic identity attributes
            if not hasattr(obj, 'id') or obj.id is None:
                obj.id = _USER_ID
            if not hasattr(obj, 'email') or obj.email is None:
                obj.email = _USER_EMAIL

        mock_session.execute = _execute
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.delete = AsyncMock()
        mock_session.refresh = _refresh
        yield mock_session


# ---------------------------------------------------------------------------
# Test 1: Register new user
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_register_new_user() -> None:
    """POST /api/auth/register with new email → 200, returns token and user dict."""
    # first execute returns None → no duplicate user exists
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[None])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.post(
                "/api/auth/register",
                json={
                    "email": _USER_EMAIL,
                    "password": _USER_PASSWORD,
                    "display_name": _USER_DISPLAY_NAME,
                },
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert "user" in data
    assert data["user"]["email"] == _USER_EMAIL
    assert isinstance(data["token"], str)
    assert len(data["token"]) > 10


# ---------------------------------------------------------------------------
# Test 2: Register with duplicate email
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_register_duplicate_email() -> None:
    """POST /api/auth/register with existing email → 400."""
    existing_user = _make_mock_user()
    # first execute returns existing user → duplicate detected
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[existing_user])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.post(
                "/api/auth/register",
                json={"email": _USER_EMAIL, "password": _USER_PASSWORD},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 400
    assert "אימייל" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Test 3: Login with valid credentials
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_login_valid() -> None:
    """POST /api/auth/login with correct credentials → 200, returns token."""
    user = _make_mock_user(password_hash=_HASHED_PASSWORD)
    # execute returns user → password verified
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[user])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.post(
                "/api/auth/login",
                json={"email": _USER_EMAIL, "password": _USER_PASSWORD},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["user"]["email"] == _USER_EMAIL


# ---------------------------------------------------------------------------
# Test 4: Login with wrong password
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_login_wrong_password() -> None:
    """POST /api/auth/login with wrong password → 401."""
    user = _make_mock_user(password_hash=_HASHED_PASSWORD)
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[user])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.post(
                "/api/auth/login",
                json={"email": _USER_EMAIL, "password": "wrongpassword"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Test 5: GET /api/auth/me with valid token
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_me_valid_token() -> None:
    """GET /api/auth/me with valid Bearer token → 200, returns user profile."""
    user = _make_mock_user()
    token = create_access_token(user.id, user.email)

    # get_current_user: decodes JWT → DB lookup returns user
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[user])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["email"] == _USER_EMAIL
    assert "id" in data


# ---------------------------------------------------------------------------
# Test 6: GET /api/auth/me with garbage token → 401
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_me_invalid_token() -> None:
    """GET /api/auth/me with garbage token → 401."""
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[None])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer garbage.token.here"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Test 7: Anonymous chat (no Authorization header)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chat_anonymous_still_works() -> None:
    """POST /api/chat with no Authorization header → 200 (anonymous works)."""
    from api.dependencies import get_ai_client, get_redis
    from api.schemas import ParsedIntent

    parsed = ParsedIntent(intent="help", voucher_network="buyme")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    # No user returned → anonymous
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[None])
    app.dependency_overrides[get_redis] = lambda: mock_redis
    try:
        with patch("api.routes.chat._parse_intent", new=AsyncMock(return_value=parsed)):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/chat",
                    json={"message": "מה אפשר לקנות?"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis, None)
        app.dependency_overrides.pop(get_ai_client, None)

    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "help"


# ---------------------------------------------------------------------------
# Test 8: POST /api/auth/import-session
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_import_session() -> None:
    """POST /api/auth/import-session with history → 200, history imported."""
    user = _make_mock_user()
    token = create_access_token(user.id, user.email)

    # Override get_current_user directly — cleanest approach for protected routes
    app.dependency_overrides[get_current_user] = lambda: user
    # DB override for the import operations (add/commit)
    app.dependency_overrides[get_db] = MockDbDep(scalar_sequence=[])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            r = await client.post(
                "/api/auth/import-session",
                json={
                    "session_history": [
                        {"role": "user", "content": "אוזניות סוני"},
                        {"role": "assistant", "content": "מצאתי 3 תוצאות"},
                    ],
                    "session_context": {
                        "user_lat": 32.08,
                        "user_lng": 34.78,
                        "location_label": "תל אביב",
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    # Both turns in session_history count toward "imported"
    assert data["imported"] == 2
