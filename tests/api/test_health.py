"""
tests/api/test_health.py — Tests for the /health endpoint.

Uses an in-process ASGI transport (no real network) so the test is fast and
does not require a running server or database connection.
"""

from __future__ import annotations

import pytest
import httpx
from httpx import AsyncClient, ASGITransport

from api.main import app


@pytest.mark.anyio
async def test_health_returns_200_and_status_ok() -> None:
    """GET /health returns HTTP 200 with ``{"status": "ok"}`` in the body.

    Uses httpx.AsyncClient with ASGITransport to call the FastAPI app directly
    in-process, without spinning up an actual HTTP server.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
