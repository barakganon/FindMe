"""tests/api/test_chat_v2_stream.py — SSE streaming endpoint tests (W5 + W8).

W5 added the four base tests (happy path, error, invite-block, budget-block).
W8 / AC-6 extends with:

  - SSE frame format: `_sse()` produces a single `event:\\ndata:\\n\\n` frame
  - Multi-frame parse: two `_sse()` outputs concatenated parse into two events
  - Multi-tool-call: each tool_call gets its own SSE frame
  - chips on final: anon empty / anon with derived_facts / logged-in user
  - X-Session-ID header is honored (anonymous → anon:<value>)
  - current_user takes precedence over X-Session-ID (user:<id>)

Multi-byte UTF-8 reassembly across read() boundaries belongs to the frontend
TextDecoder({stream: true}) — the backend emits one full UTF-8 frame per
event, so this contract is implicitly safe Python-side. Documented here
rather than skipped silently (per AC-6 note).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from api.agent.loop import AgentResult
from api.agent.session_memory import SessionState
from api.main import app
from api.dependencies import get_db, get_ai_client, get_redis
from api.schemas import MemoryChip, ToolCallTrace


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
# W8 / AC-6 extensions
# ---------------------------------------------------------------------------


def _make_agent_result(message: str = "ok", tool_calls=None) -> AgentResult:
    return AgentResult(
        message=message,
        product_results=[],
        store_results=[],
        tool_calls=tool_calls or [],
        iterations=1,
        total_latency_ms=100.0,
        total_cost_usd=0.0001,
        terminated_by="content",
    )


def test_sse_frame_format_single_event():
    """`_sse(event, data)` produces a single SSE frame: `event:<name>\\ndata:<json>\\n\\n`."""
    from api.routes.chat_v2_stream import _sse

    frame = _sse("thinking", {"stage": "thinking"})
    assert frame.startswith("event: thinking\n")
    assert "\ndata: " in frame
    assert frame.endswith("\n\n")
    # JSON parses
    data_line = [l for l in frame.split("\n") if l.startswith("data:")][0]
    parsed = json.loads(data_line[len("data:"):].strip())
    assert parsed == {"stage": "thinking"}


def test_sse_two_frames_concatenated_parse_to_two_events():
    """Two `_sse()` outputs concatenated in one string parse as two events."""
    from api.routes.chat_v2_stream import _sse

    combined = _sse("a", {"k": 1}) + _sse("b", {"k": 2})
    events = _parse_sse(combined)
    assert [e["event"] for e in events] == ["a", "b"]
    assert events[0]["data"] == {"k": 1}
    assert events[1]["data"] == {"k": 2}


@pytest.mark.anyio
async def test_stream_emits_one_tool_call_event_per_tool(monkeypatch, override_deps):
    """When the agent invokes 3 tools, the stream emits 3 distinct tool_call events."""
    fake_result = _make_agent_result(
        tool_calls=[
            ToolCallTrace(name="search_products", args={"brand": "Sony"}, duration_ms=100.0, result_count=5),
            ToolCallTrace(name="search_stores", args={"city": "תל אביב"}, duration_ms=80.0, result_count=2),
            ToolCallTrace(name="clarify", args={"question": "?"}, duration_ms=10.0, result_count=0),
        ]
    )

    async def fake_run_agent(**kwargs):
        return fake_result

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "אוזניות", "history": []},
            )

    events = _parse_sse(resp.text)
    tool_events = [e for e in events if e["event"] == "tool_call"]
    assert len(tool_events) == 3
    assert [e["data"]["name"] for e in tool_events] == [
        "search_products",
        "search_stores",
        "clarify",
    ]


@pytest.mark.anyio
async def test_stream_final_chips_empty_for_anon_no_derived_facts(monkeypatch, override_deps):
    """Anonymous user with empty session_state.derived_facts → chips=[]."""
    fake_result = _make_agent_result()

    async def fake_run_agent(**kwargs):
        return fake_result

    # Force the fresh-state reload to return a state with no derived_facts.
    async def fake_load_state(*args, **kwargs):
        return SessionState.empty()

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent), \
         patch("api.routes.chat_v2_stream.load_session_state", new=fake_load_state):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "x", "history": []},
            )

    events = _parse_sse(resp.text)
    final = next(e for e in events if e["event"] == "final")
    assert final["data"]["chips"] == []


@pytest.mark.anyio
async def test_stream_final_chips_anon_with_derived_facts(monkeypatch, override_deps):
    """Anonymous with derived_facts={city, max_price} → chips includes both."""
    fake_result = _make_agent_result()

    async def fake_run_agent(**kwargs):
        return fake_result

    fresh = SessionState(derived_facts={"city": "תל אביב", "max_price": "300"})

    async def fake_load_state(*args, **kwargs):
        return fresh

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent), \
         patch("api.routes.chat_v2_stream.load_session_state", new=fake_load_state):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "x", "history": []},
            )

    events = _parse_sse(resp.text)
    final = next(e for e in events if e["event"] == "final")
    chips = final["data"]["chips"]
    labels = [c["label"] for c in chips]
    assert "תל אביב" in labels
    assert "₪300" in labels
    assert all(c["kind"] == "session" for c in chips)


@pytest.mark.anyio
async def test_stream_final_chips_logged_in_uses_build_chips_db_path(monkeypatch, override_deps):
    """Logged-in user → chips are built via the DB path (mocked via build_chips
    patch so we don't have to wire up the SELECT chain in this test).
    """
    fake_result = _make_agent_result()

    async def fake_run_agent(**kwargs):
        return fake_result

    async def fake_get_user():
        return SimpleNamespace(id="user-xyz", display_name="X")

    async def fake_build_chips(current_user, session_state, db):
        return [MemoryChip(icon="📍", label="ירושלים", kind="preference")]

    from api.auth import get_optional_user
    app.dependency_overrides[get_optional_user] = fake_get_user

    try:
        with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent), \
             patch("api.agent.chips.build_chips", new=fake_build_chips):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat/v2/stream",
                    json={"message": "x", "history": []},
                )

        events = _parse_sse(resp.text)
        final = next(e for e in events if e["event"] == "final")
        chips = final["data"]["chips"]
        assert len(chips) == 1
        assert chips[0]["label"] == "ירושלים"
        assert chips[0]["kind"] == "preference"
    finally:
        app.dependency_overrides.pop(get_optional_user, None)


@pytest.mark.anyio
async def test_stream_honors_x_session_id_header_for_anon(monkeypatch, override_deps):
    """An anonymous request with `X-Session-ID: abc` derives session_id='anon:abc'."""
    fake_result = _make_agent_result()
    captured_session_ids: list = []

    async def fake_run_agent(**kwargs):
        return fake_result

    real_derive = __import__("api.agent.session_memory", fromlist=["derive_session_id"]).derive_session_id

    def spy_derive(user, header):
        sid = real_derive(user, header)
        captured_session_ids.append(sid)
        return sid

    with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent), \
         patch("api.routes.chat_v2_stream.derive_session_id", new=spy_derive):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/v2/stream",
                json={"message": "x", "history": []},
                headers={"X-Session-ID": "browser-uuid-123"},
            )

    assert resp.status_code == 200
    assert "anon:browser-uuid-123" in captured_session_ids


@pytest.mark.anyio
async def test_stream_current_user_overrides_x_session_id(monkeypatch, override_deps):
    """When current_user is set, session_id is `user:<id>` regardless of the
    X-Session-ID header.
    """
    fake_result = _make_agent_result()
    captured: list = []

    async def fake_run_agent(**kwargs):
        return fake_result

    async def fake_get_user():
        return SimpleNamespace(id="user-42", display_name="Forty-Two")

    real_derive = __import__("api.agent.session_memory", fromlist=["derive_session_id"]).derive_session_id

    def spy_derive(user, header):
        sid = real_derive(user, header)
        captured.append(sid)
        return sid

    from api.auth import get_optional_user
    app.dependency_overrides[get_optional_user] = fake_get_user
    try:
        with patch("api.routes.chat_v2_stream.run_agent", new=fake_run_agent), \
             patch("api.routes.chat_v2_stream.derive_session_id", new=spy_derive):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat/v2/stream",
                    json={"message": "x", "history": []},
                    headers={"X-Session-ID": "ignored-anon-id"},
                )
        assert resp.status_code == 200
        assert "user:user-42" in captured
        assert not any("ignored-anon-id" in sid for sid in captured if sid)
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
