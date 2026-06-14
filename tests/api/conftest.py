"""tests/api/conftest.py — API-scoped pytest fixtures (W8).

These fixtures consolidate the mock setup for direct tool unit tests
(`tests/api/test_tool_*.py`) so each test file does not redefine the same
AsyncMock SQLAlchemy session or tool_context dict.

Fixtures:
    mock_db        — AsyncMock SQLAlchemy session with .execute() async.
    tool_context   — dict matching the kwargs every `execute_*` tool accepts.
    app_client     — httpx.AsyncClient wired to api.main.app with default
                     dependency overrides (DB/AI/Redis mocked, no real calls).

Helpers (importable):
    make_db_result(*items)   — Build a mock SQLAlchemy result whose
                               .scalars().all() returns the given items.
    make_user(user_id)       — Build a stand-in user object (id, email,
                               display_name) for current_user kwargs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from api.agent.session_memory import SessionState


def make_db_result(*items: Any) -> MagicMock:
    """Mock the SQLAlchemy result chain: result.scalars().all() → list(items)."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=list(items))
    scalars.first = MagicMock(return_value=items[0] if items else None)
    result.scalars = MagicMock(return_value=scalars)
    result.scalar_one_or_none = MagicMock(return_value=items[0] if items else None)
    return result


def make_user(user_id: str = "user-abc", **overrides: Any) -> SimpleNamespace:
    """Stand-in user object for tool_context['current_user']."""
    defaults: dict[str, Any] = {
        "id": user_id,
        "email": "tester@example.com",
        "display_name": "Tester",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def mock_db() -> MagicMock:
    """AsyncMock SQLAlchemy session. `.execute()` is async; configure
    return via `db.execute.return_value = <make_db_result(...)>`.
    """
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def tool_context(mock_db: MagicMock) -> dict:
    """The kwargs dict passed into every `execute_*` tool.

    Default: anonymous user, no GPS, empty session state, fresh mock DB.
    Tests may override any field locally before calling the tool.
    """
    return {
        "db": mock_db,
        "api_key": "fake-key",
        "location": None,
        "current_user": None,
        "session_state": SessionState.empty(),
    }


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    """`httpx.AsyncClient` wired to the FastAPI app with default deps overridden.

    DB → MagicMock generator, AI → MagicMock, Redis → AsyncMock. Tests that
    need richer behavior should set `app.dependency_overrides[get_*] = ...`
    before issuing requests and reset afterward.
    """
    from api.main import app
    from api.dependencies import get_db, get_ai_client, get_redis

    async def _override_db():
        yield MagicMock()

    def _override_ai():
        return MagicMock()

    # Use a single stable mock so tests can introspect calls after the request.
    _redis_mock = AsyncMock()

    async def _override_redis():
        return _redis_mock

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_ai_client] = _override_ai
    app.dependency_overrides[get_redis] = _override_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
