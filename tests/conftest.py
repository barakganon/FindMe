"""
tests/conftest.py — Shared pytest fixtures for the FindMe / BuyMe Smart Search test suite.

Fixtures provided:
    anyio_backend       — Forces anyio to use the asyncio event loop for all async tests.
    anthropic_client    — A MagicMock standing in for an instructor.AsyncInstructor
                          instance; prevents real API calls in unit tests.
"""

import pytest
from unittest.mock import MagicMock

# Register anyio pytest plugin so async tests work with pytest-anyio
pytest_plugins = ("anyio",)


@pytest.fixture
def anyio_backend() -> str:
    """Return the anyio backend to use for async tests.

    Returns:
        "asyncio" — all async tests run on the standard asyncio event loop.
    """
    return "asyncio"


@pytest.fixture
def anthropic_client() -> MagicMock:
    """Return a MagicMock standing in for an instructor.AsyncInstructor client.

    Prevents any real Anthropic API calls from being made during unit tests.
    Tests that need specific return values should configure this mock in the
    test body using ``anthropic_client.create.return_value = ...``.

    Returns:
        A :class:`unittest.mock.MagicMock` instance.
    """
    return MagicMock()
