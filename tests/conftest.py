"""
tests/conftest.py — Shared pytest fixtures for the FindMe / BuyMe Smart Search test suite.

Fixtures provided:
    anyio_backend   — Forces anyio to use the asyncio event loop for all async tests.
    ai_client       — A MagicMock standing in for an instructor.AsyncInstructor
                      instance; prevents real API calls in unit tests.
    redis_mock      — AsyncMock standing in for a redis.asyncio.Redis client
                      with `.get`, `.setex`, and `.delete` pre-bound (W8).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

pytest_plugins = ("anyio",)


@pytest.fixture
def anyio_backend() -> str:
    """Force anyio tests to run on the asyncio event loop."""
    return "asyncio"


@pytest.fixture
def ai_client() -> MagicMock:
    """MagicMock standing in for an instructor.AsyncInstructor client.

    Prevents any real Gemini API calls from being made during unit tests.
    Tests that need specific return values should configure this mock in the
    test body using ``ai_client.create.return_value = ...``.
    """
    return MagicMock()


@pytest.fixture
def redis_mock() -> AsyncMock:
    """AsyncMock standing in for redis.asyncio.Redis (W8).

    The async-only methods used by `api/agent/cost_guard.py`,
    `api/agent/session_memory.py`, and `api/cache.py` are pre-bound so test
    bodies can configure return values without re-stubbing the surface.

    Default behavior: every call returns None (Redis miss). Tests override
    per-call via ``redis_mock.get.return_value = b"..."`` etc.
    """
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.setex = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    client.incrbyfloat = AsyncMock(return_value=0.0)
    client.expire = AsyncMock(return_value=True)
    return client
