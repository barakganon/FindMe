"""tests/api/test_chat_v2_stream.py — W5 SSE streaming endpoint tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from api.agent.loop import AgentResult
from api.main import app
from api.dependencies import get_db, get_ai_client, get_redis
from api.schemas import ToolCallTrace


def _override_db():
    async def gen():
        yield MagicMock()
    return gen()


def _override_ai():
    return MagicMock()


async def _override_redis():
    return AsyncMock()


def _parse_sse(text: str) -> list[dict]:
    """Parse an SSE stream body into a list of {event, data} dicts."""
    events: list[dict] = []
    current_event = None
    for line in text.splitlines():
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and current_event:
            import json as _json
            events.append({"event": current_event, "data": _json.loads(line[5:].strip())})
            current_event = None
    return events


@pytest.fixture
def override_deps():
    """Override DB/AI/Redis FastAPI deps; clean up after."""
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_ai_client] = _override_ai
    app.dependency_overrides[get_redis] = _override_redis
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_stream_emits_thinking_then_tool_call_then_final(monkeypatch, override_deps):
    """Happy path — verify the event order on a tool-using turn."""
    fake_result = AgentResult(
        message="מצאתי 5 אוזניות סוני.",
        product_results=[],
        store_results=[],
        tool_calls=[
            ToolCallTrace(name="search_products", args={"brand": "Sony"}, duration_ms=400.0, result_count=5),
        ],
        iterations=2,
        total_latency_ms=1500.0,
        total_cost_usd=0.0003,
        terminated_by="content",
    )

    async def fake_run_agent(**kwargs):
        return fake_result

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "אוזניות סוני", "history": []},
            )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    event_names = [e["event"] for e in events]
    # First event is "thinking", then tool_call(s), then final
    assert event_names[0] == "thinking"
    assert "tool_call" in event_names
    assert event_names[-1] == "final"

    final = next(e for e in events if e["event"] == "final")
    assert final["data"]["message"] == "מצאתי 5 אוזניות סוני."
    assert final["data"]["intent"] == "product_search"
    # W7: final must include a `chips` field (anon, no derived facts pre-turn → may be populated from this turn)
    assert "chips" in final["data"]
    assert isinstance(final["data"]["chips"], list)


@pytest.mark.anyio
async def test_stream_emits_error_on_agent_failure(monkeypatch, override_deps):
    """When run_agent raises, the stream emits an `error` event and ends cleanly."""
    async def boom(**kwargs):
        raise RuntimeError("kaboom")

    with patch("api.routes.chat_v2_stream.run_agent", new=boom):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "x", "history": []},
            )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_names = [e["event"] for e in events]
    assert event_names[0] == "thinking"
    assert "error" in event_names
    err_event = next(e for e in events if e["event"] == "error")
    assert "kaboom" in err_event["data"]["error"]


@pytest.mark.anyio
async def test_stream_blocked_by_invite_only(monkeypatch, override_deps):
    """When V2_INVITE_ONLY=true and anon disallowed, anonymous request gets 403."""
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_ALLOW_ANON", "false")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/chat/v2/stream",
            json={"message": "x", "history": []},
        )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_stream_blocked_by_daily_budget(monkeypatch, override_deps):
    """When daily cost exceeds budget, stream returns 503 with Retry-After."""
    monkeypatch.setenv("DAILY_COST_BUDGET_USD", "0.001")

    async def _redis_over():
        m = AsyncMock()
        m.get = AsyncMock(return_value="999.0")  # way over
        return m

    app.dependency_overrides[get_redis] = _redis_over

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/chat/v2/stream",
            json={"message": "x", "history": []},
        )
    assert resp.status_code == 503
    assert "Retry-After" in resp.headers


@pytest.mark.anyio
async def test_stream_blocked_by_session_budget(monkeypatch, override_deps):
    """When session cost exceeds per-session budget, stream returns 503 with Retry-After."""
    # Set a tiny session budget so any session cost trips it
    monkeypatch.setenv("PER_SESSION_COST_BUDGET_USD", "0.001")

    session_id = "test-session-over-budget"

    async def _redis_session_over():
        m = AsyncMock()
        # daily key returns 0.0 (fine); session key returns 999.0 (over budget)
        async def _get(key: str):
            if "session_cost" in key:
                return "999.0"
            return "0.0"
        m.get = AsyncMock(side_effect=_get)
        return m

    app.dependency_overrides[get_redis] = _redis_session_over

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/chat/v2/stream",
            json={"message": "x", "history": []},
            headers={"X-Session-ID": session_id},
        )
    assert resp.status_code == 503
    assert "Retry-After" in resp.headers
    body = resp.json()
    assert body["detail"]["fallback"] == "/api/chat"
    assert "session" in body["detail"]["error"]
