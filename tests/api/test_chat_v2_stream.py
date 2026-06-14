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


# ---------------------------------------------------------------------------
# W7 — chips in final event (AC-3 + AC-7)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stream_final_chips_populated_from_tool_calls(override_deps):
    """AC-7: when agent runs search_products with max_price, final.chips includes 💰 chip.

    Flow: run_agent returns tool_call with max_price arg → save_session_state extracts
    derived_facts → load_session_state reads them back → build_chips creates chip.
    We use a real (mocked) Redis that stores/retrieves JSON to exercise the full
    save → load → chips pipeline without touching Gemini or the DB.
    """
    import json as _json

    store: dict = {}

    async def fake_redis_get(key):
        return store.get(key)

    async def fake_redis_setex(key, ttl, value):
        store[key] = value

    async def fake_redis_delete(key):
        store.pop(key, None)

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(side_effect=fake_redis_get)
    redis_mock.setex = AsyncMock(side_effect=fake_redis_setex)
    redis_mock.delete = AsyncMock(side_effect=fake_redis_delete)

    async def _override_redis_stateful():
        return redis_mock

    app.dependency_overrides[get_redis] = _override_redis_stateful

    fake_result = AgentResult(
        message="מצאתי מוצרים.",
        product_results=[],
        store_results=[],
        tool_calls=[
            ToolCallTrace(
                name="search_products",
                args={"max_price": 300, "city": "תל אביב"},
                duration_ms=200.0,
                result_count=3,
            ),
        ],
        iterations=2,
        total_latency_ms=800.0,
        total_cost_usd=0.0001,
        terminated_by="content",
    )

    async def fake_run_agent(**kwargs):
        return fake_result

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "מוצרים בתל אביב עד 300", "history": []},
                headers={"X-Session-ID": "test-session-uuid-001"},
            )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    final = next(e for e in events if e["event"] == "final")
    chips = final["data"]["chips"]
    assert isinstance(chips, list)
    # At least max_price chip should appear (💰 ₪300)
    icons = [c["icon"] for c in chips]
    labels = [c["label"] for c in chips]
    assert "💰" in icons, f"Expected 💰 chip, got: {chips}"
    assert "₪300" in labels, f"Expected ₪300 label, got: {labels}"
    # City chip should also appear (📍 תל אביב)
    assert "📍" in icons, f"Expected 📍 chip, got: {chips}"


@pytest.mark.anyio
async def test_stream_emits_one_tool_call_event_per_tool(override_deps):
    """AC-4 contract: one tool_call SSE event per tool invoked (not batched)."""
    fake_result = AgentResult(
        message="מצאתי.",
        product_results=[],
        store_results=[],
        tool_calls=[
            ToolCallTrace(name="recall_history", args={}, duration_ms=50.0, result_count=0),
            ToolCallTrace(name="search_products", args={"brand": "LG"}, duration_ms=300.0, result_count=4),
        ],
        iterations=3,
        total_latency_ms=900.0,
        total_cost_usd=0.0002,
        terminated_by="content",
    )

    async def fake_run_agent(**kwargs):
        return fake_result

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "כמו פעם שעברה, LG", "history": []},
            )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    tool_call_events = [e for e in events if e["event"] == "tool_call"]
    # One event per tool call in result.tool_calls
    assert len(tool_call_events) == 2
    names = [e["data"]["name"] for e in tool_call_events]
    assert names[0] == "recall_history"
    assert names[1] == "search_products"


@pytest.mark.anyio
async def test_stream_tool_call_event_includes_required_fields(override_deps):
    """Each tool_call event must have name, args, duration_ms, result_count (AC-4 contract)."""
    fake_result = AgentResult(
        message="ok",
        product_results=[],
        store_results=[],
        tool_calls=[
            ToolCallTrace(name="clarify", args={"question": "איזה גיל?"}, duration_ms=10.0, result_count=0),
        ],
        iterations=1,
        total_latency_ms=200.0,
        total_cost_usd=0.00001,
        terminated_by="content",
    )

    async def fake_run_agent(**kwargs):
        return fake_result

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "מתנה", "history": []},
            )

    events = _parse_sse(resp.text)
    tc_event = next(e for e in events if e["event"] == "tool_call")
    data = tc_event["data"]
    assert data["name"] == "clarify"
    assert "args" in data
    assert "duration_ms" in data
    assert "result_count" in data


@pytest.mark.anyio
async def test_stream_final_includes_voucher_network(override_deps):
    """final event must echo back voucher_network from the request (never hardcodes 'buyme')."""
    fake_result = AgentResult(
        message="מצאתי.",
        product_results=[],
        store_results=[],
        tool_calls=[],
        iterations=1,
        total_latency_ms=400.0,
        total_cost_usd=0.00005,
        terminated_by="content",
    )

    async def fake_run_agent(**kwargs):
        return fake_result

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "שאלה", "history": [], "voucher_network": "buyme"},
            )

    events = _parse_sse(resp.text)
    final = next(e for e in events if e["event"] == "final")
    assert final["data"]["voucher_network"] == "buyme"
