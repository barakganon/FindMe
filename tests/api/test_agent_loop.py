"""tests/api/test_agent_loop.py — Unit tests for the v2 agent loop.

All LLM calls are mocked. The tests cover the four core behaviors W2 needs:
1. Terminates cleanly when the LLM returns content (no tool calls)
2. Dispatches a tool call, appends result, and lets the LLM compose a reply
3. Handles tool-execution errors gracefully (surfaces error to LLM, continues)
4. Respects max_iterations (returns a defined terminated_by, no infinite loop)
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from api.agent.loop import run_agent
from api.schemas import ChatMessage


# ---------------------------------------------------------------------------
# Mock helpers — build OpenAI-shaped completion objects
# ---------------------------------------------------------------------------


def _mock_completion(content: str | None = None, tool_calls: list | None = None):
    """Build a mock OpenAI chat.completions.create() return value."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _mock_tool_call(call_id: str, name: str, args: dict):
    """Build a mock tool_call object matching the OpenAI SDK shape."""
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _mock_llm(side_effect_completions: list):
    """Build an AsyncOpenAI mock that returns the provided completions in order."""
    client = MagicMock()
    create_mock = AsyncMock(side_effect=side_effect_completions)
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = create_mock
    return client


# ---------------------------------------------------------------------------
# Mock tool — captures invocations without real DB/Gemini calls
# ---------------------------------------------------------------------------


class _FakeParams(BaseModel):
    query: str | None = None
    brand: str | None = None


async def _fake_tool_ok(params: _FakeParams, **kwargs):
    """Tool that always succeeds, returns a marker list + summary."""
    return ([{"id": "fake-1", "name": "Mock Item", "brand": params.brand}], f"מצאתי 1: {params.query or params.brand}")


async def _fake_tool_raises(params: _FakeParams, **kwargs):
    raise RuntimeError("boom — tool exploded")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_terminates_when_llm_returns_content():
    """LLM produces final content without tool calls → loop exits with content."""
    llm = _mock_llm([_mock_completion(content="שלום! איך אפשר לעזור?")])
    result = await run_agent(
        message="היי",
        history=[],
        llm_client=llm,
        tools=[],
        tool_registry={},
        tool_context={},
    )
    assert result.message == "שלום! איך אפשר לעזור?"
    assert result.iterations == 1
    assert result.tool_calls == []
    assert result.terminated_by == "content"


@pytest.mark.anyio
async def test_dispatches_tool_then_composes_reply():
    """LLM calls a tool, gets a result, then composes the final reply."""
    llm = _mock_llm(
        [
            _mock_completion(
                tool_calls=[
                    _mock_tool_call(
                        "call-1", "fake_tool", {"query": "headphones", "brand": "Sony"}
                    )
                ]
            ),
            _mock_completion(content="מצאתי לך אוזניות Sony."),
        ]
    )
    result = await run_agent(
        message="אוזניות סוני",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "fake_tool"}}],
        tool_registry={"fake_tool": (_FakeParams, _fake_tool_ok)},
        tool_context={},
    )
    assert result.iterations == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "fake_tool"
    assert result.tool_calls[0].args == {"query": "headphones", "brand": "Sony"}
    assert result.tool_calls[0].error is None
    assert result.tool_calls[0].result_count == 1
    assert result.message == "מצאתי לך אוזניות Sony."
    assert result.terminated_by == "content"


@pytest.mark.anyio
async def test_tool_error_surfaces_to_llm_and_continues():
    """When a tool raises, the error is captured into the trace AND surfaced
    as a `tool` role message back to the LLM, which can then recover."""
    llm = _mock_llm(
        [
            _mock_completion(
                tool_calls=[_mock_tool_call("call-1", "bad_tool", {"query": "x"})]
            ),
            _mock_completion(content="מצטערת, אירעה תקלה. נסה לנסח אחרת."),
        ]
    )
    result = await run_agent(
        message="something",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "bad_tool"}}],
        tool_registry={"bad_tool": (_FakeParams, _fake_tool_raises)},
        tool_context={},
    )
    assert result.iterations == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].error is not None
    assert "boom" in result.tool_calls[0].error
    assert result.message.startswith("מצטערת")
    assert result.terminated_by == "content"


@pytest.mark.anyio
async def test_respects_max_iterations():
    """If the LLM keeps calling tools forever, the loop terminates at max_iterations."""
    # Build N completions all with tool calls so the loop never naturally terminates
    looping_completions = [
        _mock_completion(
            tool_calls=[_mock_tool_call(f"call-{i}", "fake_tool", {"query": f"q{i}"})]
        )
        for i in range(10)  # more than max_iterations
    ]
    llm = _mock_llm(looping_completions)
    result = await run_agent(
        message="loop forever",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "fake_tool"}}],
        tool_registry={"fake_tool": (_FakeParams, _fake_tool_ok)},
        tool_context={},
        max_iterations=3,
    )
    assert result.iterations == 3
    assert result.terminated_by == "max_iterations"
    assert len(result.tool_calls) == 3
    assert result.message  # has a fallback message


@pytest.mark.anyio
async def test_history_threaded_into_conversation():
    """The user's history is included in the LLM's message list."""
    history = [
        ChatMessage(role="user", content="היי"),
        ChatMessage(role="assistant", content="שלום!"),
    ]
    llm = _mock_llm([_mock_completion(content="זוכר, בוודאי.")])
    result = await run_agent(
        message="זוכר אותי?",
        history=history,
        llm_client=llm,
        tools=[],
        tool_registry={},
        tool_context={},
    )
    # Inspect what the LLM was called with
    create_call = llm.chat.completions.create.await_args
    messages_sent = create_call.kwargs["messages"]
    # system + 2 history turns + 1 new user message = 4
    assert len(messages_sent) == 4
    assert messages_sent[0]["role"] == "system"
    assert messages_sent[1] == {"role": "user", "content": "היי"}
    assert messages_sent[2] == {"role": "assistant", "content": "שלום!"}
    assert messages_sent[3] == {"role": "user", "content": "זוכר אותי?"}
    assert result.message == "זוכר, בוודאי."


@pytest.mark.anyio
async def test_invalid_tool_args_surfaces_validation_error():
    """If the LLM emits bad tool arguments, the validation error is captured
    in the trace and surfaced back to the LLM."""

    class _StrictParams(BaseModel):
        required_field: str

    async def _strict_tool(params: _StrictParams, **kwargs):
        return ([], "shouldn't reach here")

    llm = _mock_llm(
        [
            _mock_completion(
                tool_calls=[
                    _mock_tool_call("call-1", "strict_tool", {"wrong_field": "x"})
                ]
            ),
            _mock_completion(content="אעדיף שאדע יותר פרטים."),
        ]
    )
    result = await run_agent(
        message="something",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "strict_tool"}}],
        tool_registry={"strict_tool": (_StrictParams, _strict_tool)},
        tool_context={},
    )
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].error is not None
    assert "invalid arguments" in result.tool_calls[0].error
    assert result.terminated_by == "content"


# ---------------------------------------------------------------------------
# Tests for review-finding patches (2026-05-16)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_empty_content_and_no_tool_calls_yields_fallback():
    """Both content=None and tool_calls=None must not produce a silent blank reply."""
    llm = _mock_llm([_mock_completion(content=None, tool_calls=None)])
    result = await run_agent(
        message="היי",
        history=[],
        llm_client=llm,
        tools=[],
        tool_registry={},
        tool_context={},
    )
    assert result.message  # non-empty fallback
    assert result.terminated_by == "empty_response"


@pytest.mark.anyio
async def test_completion_with_no_choices_is_safety_blocked():
    """Empty choices list (Gemini safety filter) terminates with safety_blocked, not generic error."""
    # Build a real-shape namespace (not MagicMock) so the cost estimator can
    # introspect usage cleanly instead of getting auto-magic attrs.
    empty = SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0),
    )
    llm = _mock_llm([empty])
    result = await run_agent(
        message="anything",
        history=[],
        llm_client=llm,
        tools=[],
        tool_registry={},
        tool_context={},
    )
    assert result.terminated_by == "safety_blocked"
    assert result.message  # has a user-facing fallback


@pytest.mark.anyio
async def test_malformed_tool_call_is_dropped():
    """A tool_call whose .function is None must not crash the iteration —
    the loop drops it and (if no others remain) terminates with error."""
    bad_tc = SimpleNamespace(id="x", function=None)
    llm = _mock_llm([_mock_completion(tool_calls=[bad_tc])])
    result = await run_agent(
        message="x",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "fake_tool"}}],
        tool_registry={"fake_tool": (_FakeParams, _fake_tool_ok)},
        tool_context={},
    )
    assert result.terminated_by == "error"
    # The malformed call should NOT appear in the trace (it was dropped pre-dispatch)
    assert len(result.tool_calls) == 0


@pytest.mark.anyio
async def test_tool_timeout_surfaces_to_trace_and_continues():
    """A tool that exceeds tool_timeout_s must be reported in the trace and not hang the worker."""
    import asyncio as _asyncio

    async def _slow_tool(params: _FakeParams, **kwargs):
        await _asyncio.sleep(5.0)  # longer than the timeout we'll set
        return ([], "never reached")

    llm = _mock_llm(
        [
            _mock_completion(tool_calls=[_mock_tool_call("c1", "slow_tool", {})]),
            _mock_completion(content="הכלי לא הספיק. נסה שוב."),
        ]
    )
    result = await run_agent(
        message="anything",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "slow_tool"}}],
        tool_registry={"slow_tool": (_FakeParams, _slow_tool)},
        tool_context={},
        tool_timeout_s=0.5,
    )
    assert len(result.tool_calls) == 1
    assert "timed out" in (result.tool_calls[0].error or "")
    assert result.terminated_by == "content"


@pytest.mark.anyio
async def test_cost_budget_exceeded_terminates():
    """When cumulative cost exceeds cost_budget_usd, the loop must terminate."""

    # Each completion has a usage object reporting very high token counts so the
    # estimator pushes us over budget after the first call.
    def _expensive_completion():
        msg = SimpleNamespace(content="...", tool_calls=None)
        choice = SimpleNamespace(message=msg)
        usage = SimpleNamespace(prompt_tokens=10_000_000, completion_tokens=10_000_000)
        return SimpleNamespace(choices=[choice], usage=usage)

    llm = _mock_llm([_expensive_completion()])
    result = await run_agent(
        message="x",
        history=[],
        llm_client=llm,
        tools=[],
        tool_registry={},
        tool_context={},
        cost_budget_usd=0.01,
    )
    assert result.terminated_by == "cost_budget"
    assert result.total_cost_usd > 0.01


@pytest.mark.anyio
async def test_invalid_max_iterations_rejected():
    """max_iterations < 1 must raise rather than silently no-op."""
    llm = _mock_llm([_mock_completion(content="x")])
    with pytest.raises(ValueError, match="max_iterations"):
        await run_agent(
            message="x",
            history=[],
            llm_client=llm,
            tools=[],
            tool_registry={},
            tool_context={},
            max_iterations=0,
        )


@pytest.mark.anyio
async def test_tool_result_includes_structured_items_for_llm():
    """The role=tool content must include structured item data (JSON), not
    just a Hebrew summary string. The LLM needs prices/names to compose replies."""
    from api.schemas import ProductResult, StoreInfo
    import json as _json

    async def _tool_with_real_results(params: _FakeParams, **kwargs):
        store = StoreInfo(
            id="s1", name_he="חנות", name_en=None, buyme_url="https://buyme.co.il/s1",
            is_online=True, city="תל אביב", lat=None, lng=None, distance_km=None,
        )
        item = ProductResult(
            product_id="p1", canonical_name="Sony XM5", brand="Sony", category_path=None,
            store=store, price=1299.0, currency="ILS", availability=True,
            product_url="https://x", match_score=0.9,
        )
        return ([item], "מצאתי 1: Sony XM5")

    llm = _mock_llm(
        [
            _mock_completion(tool_calls=[_mock_tool_call("c1", "real_tool", {"brand": "Sony"})]),
            _mock_completion(content="הנה המוצר."),
        ]
    )
    result = await run_agent(
        message="x",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "real_tool"}}],
        tool_registry={"real_tool": (_FakeParams, _tool_with_real_results)},
        tool_context={},
    )
    # The tool dispatch must have been called twice (first LLM with tools, second to compose).
    # Inspect the second LLM call's messages — the tool message should have JSON-encoded items.
    create_call = llm.chat.completions.create.await_args_list[1]
    msgs = create_call.kwargs["messages"]
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    payload = _json.loads(tool_msgs[0]["content"])
    assert "items" in payload
    assert payload["items"][0]["name"] == "Sony XM5"
    assert payload["items"][0]["price"] == 1299.0


@pytest.mark.anyio
async def test_dedup_accumulates_unique_products():
    """When the LLM calls search_products multiple times, accumulator dedups by product_id."""
    from api.schemas import ProductResult, StoreInfo
    from api.agent.loop import _accumulate_results

    store = StoreInfo(
        id="s1", name_he="חנות", name_en=None, buyme_url=None,
        is_online=True, city=None, lat=None, lng=None, distance_km=None,
    )

    def _mk_item(pid: str) -> ProductResult:
        return ProductResult(
            product_id=pid, canonical_name=f"Item {pid}", brand=None, category_path=None,
            store=store, price=10.0, currency="ILS", availability=True,
            product_url=None, match_score=0.5,
        )

    accum: list = []
    _accumulate_results(accum, [_mk_item("p1"), _mk_item("p2"), _mk_item("p3")])
    _accumulate_results(accum, [_mk_item("p2"), _mk_item("p4")])  # p2 is dup
    assert [it.product_id for it in accum] == ["p1", "p2", "p3", "p4"]


@pytest.mark.anyio
async def test_history_tool_role_messages_are_dropped():
    """History entries with role=tool must be dropped from the LLM conversation
    (they lack tool_call_id and would 400 the provider)."""
    from api.schemas import ChatMessage

    history = [
        ChatMessage(role="user", content="א"),
        ChatMessage(role="tool", content="this should be dropped"),
        ChatMessage(role="assistant", content="ב"),
    ]
    llm = _mock_llm([_mock_completion(content="ok")])
    await run_agent(
        message="ג",
        history=history,
        llm_client=llm,
        tools=[],
        tool_registry={},
        tool_context={},
    )
    create_call = llm.chat.completions.create.await_args
    msgs = create_call.kwargs["messages"]
    # system + 2 valid history turns + 1 new user msg = 4 (tool message dropped)
    assert len(msgs) == 4
    assert all(m["role"] != "tool" for m in msgs)
    # The "dropped" content is also gone
    assert all("dropped" not in (m.get("content", "") or "") for m in msgs)


@pytest.mark.anyio
async def test_json_parse_failure_preserves_raw_args_in_trace():
    """When tool_call arguments are malformed JSON, the trace must preserve
    the raw payload so debugging is possible."""
    bad_tc = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="fake_tool", arguments='{"brand": MALFORMED'),
    )
    llm = _mock_llm(
        [
            _mock_completion(tool_calls=[bad_tc]),
            _mock_completion(content="לא הצלחתי לקרוא לכלי."),
        ]
    )
    result = await run_agent(
        message="x",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "fake_tool"}}],
        tool_registry={"fake_tool": (_FakeParams, _fake_tool_ok)},
        tool_context={},
    )
    assert len(result.tool_calls) == 1
    tc_trace = result.tool_calls[0]
    assert tc_trace.error is not None
    # Raw payload preserved for debugging
    assert "_raw_args" in tc_trace.args
    assert "MALFORMED" in tc_trace.args["_raw_args"]


@pytest.mark.anyio
async def test_intermediate_content_captured_when_alongside_tool_calls():
    """When the LLM emits BOTH content (reasoning) AND tool_calls, the content
    must be captured in result.intermediate_content rather than dropped."""
    llm = _mock_llm(
        [
            _mock_completion(
                content="חושב על זה...",
                tool_calls=[_mock_tool_call("c1", "fake_tool", {"query": "x"})],
            ),
            _mock_completion(content="הנה התוצאה."),
        ]
    )
    result = await run_agent(
        message="x",
        history=[],
        llm_client=llm,
        tools=[{"type": "function", "function": {"name": "fake_tool"}}],
        tool_registry={"fake_tool": (_FakeParams, _fake_tool_ok)},
        tool_context={},
    )
    assert result.message == "הנה התוצאה."
    assert "חושב על זה..." in result.intermediate_content


# ---------------------------------------------------------------------------
# W3 tools — clarify, recall_history, get_user_context, search_stores
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_clarify_tool_dispatch_and_intent_inference():
    """When the agent calls clarify, the trace records it and the route's
    _infer_intent maps it to 'clarify'."""
    from api.agent.tools import TOOLS, ClarifyParams, execute_clarify
    from api.routes.chat_v2 import _infer_intent
    from api.schemas import AgentTrace, ToolCallTrace

    # Direct execute returns the question verbatim
    params = ClarifyParams(question="מהיכן אתה?")
    items, summary = await execute_clarify(params)
    assert items == []
    assert summary == "מהיכן אתה?"

    # Synthetic trace with a clarify call → intent="clarify"
    trace = AgentTrace(
        tool_calls=[ToolCallTrace(name="clarify", args={"question": "מהיכן אתה?"})],
        iterations=2,
    )
    assert _infer_intent("content", trace, "מסעדות לידי") == "clarify"


@pytest.mark.anyio
async def test_clarify_intent_takes_priority_over_other_tools():
    """If both clarify AND search_products were called in one turn, intent=clarify."""
    from api.routes.chat_v2 import _infer_intent
    from api.schemas import AgentTrace, ToolCallTrace

    trace = AgentTrace(
        tool_calls=[
            ToolCallTrace(name="search_products", args={"brand": "Sony"}),
            ToolCallTrace(name="clarify", args={"question": "איזה דגם?"}),
        ],
    )
    assert _infer_intent("content", trace, "אוזניות") == "clarify"


@pytest.mark.anyio
async def test_search_stores_intent_inference():
    from api.routes.chat_v2 import _infer_intent
    from api.schemas import AgentTrace, ToolCallTrace

    trace = AgentTrace(
        tool_calls=[ToolCallTrace(name="search_stores", args={"city": "Tel Aviv"})],
    )
    assert _infer_intent("content", trace, "מסעדות בתל אביב") == "store_search"


@pytest.mark.anyio
async def test_recall_history_with_no_session_state():
    """recall_history with session_state=None returns the 'no history' summary."""
    from api.agent.tools import RecallHistoryParams, execute_recall_history

    items, summary = await execute_recall_history(
        RecallHistoryParams(turn_offset=1),
        session_state=None,
    )
    assert items == []
    assert "אין היסטוריה" in summary


@pytest.mark.anyio
async def test_recall_history_with_empty_session_state():
    """recall_history with an empty SessionState returns the 'no history' summary."""
    from api.agent.session_memory import SessionState
    from api.agent.tools import RecallHistoryParams, execute_recall_history

    items, summary = await execute_recall_history(
        RecallHistoryParams(turn_offset=1),
        session_state=SessionState.empty(),
    )
    assert items == []
    assert "אין היסטוריה" in summary


@pytest.mark.anyio
async def test_recall_history_returns_prior_tray():
    """recall_history returns serialized prior products + stores from session."""
    from api.agent.session_memory import SessionState
    from api.agent.tools import RecallHistoryParams, execute_recall_history

    state = SessionState(
        last_product_results=[
            {"product_id": "p1", "canonical_name": "Sony XM5", "price": 1299},
        ],
        last_store_results=[
            {"id": "s1", "name_he": "חנות"},
        ],
        last_user_message="אוזניות סוני",
        last_assistant_message="מצאתי",
        updated_at="2026-05-16T10:00:00+00:00",
    )
    items, summary = await execute_recall_history(
        RecallHistoryParams(turn_offset=1),
        session_state=state,
    )
    assert items == []
    payload = json.loads(summary)
    assert payload["previous_user_message"] == "אוזניות סוני"
    assert payload["previous_product_count"] == 1
    assert payload["previous_store_count"] == 1


@pytest.mark.anyio
async def test_get_user_context_anonymous():
    """get_user_context returns 'not logged in' summary when current_user is None."""
    from api.agent.tools import GetUserContextParams, execute_get_user_context

    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        db=None,  # never accessed for anon
        current_user=None,
    )
    assert items == []
    assert "לא מחובר" in summary


@pytest.mark.anyio
async def test_location_clarify_sets_needs_location():
    """When the agent calls clarify with a location-shaped question, the
    route's _looks_like_location_prompt heuristic returns True."""
    from api.routes.chat_v2 import _looks_like_location_prompt
    from api.schemas import AgentTrace, ToolCallTrace

    trace = AgentTrace(
        tool_calls=[ToolCallTrace(name="clarify", args={"question": "מהיכן אתה?"})],
    )
    assert _looks_like_location_prompt(trace) is True

    trace_non_loc = AgentTrace(
        tool_calls=[ToolCallTrace(name="clarify", args={"question": "מה התקציב שלך?"})],
    )
    assert _looks_like_location_prompt(trace_non_loc) is False


# ---------------------------------------------------------------------------
# W6 — Brand re-rank in search_products
# ---------------------------------------------------------------------------


def _make_product(name: str, brand: str | None):
    from api.schemas import ProductResult, StoreInfo
    store = StoreInfo(
        id="s", name_he="", name_en=None, buyme_url=None,
        is_online=True, city=None, lat=None, lng=None, distance_km=None,
    )
    return ProductResult(
        product_id=name, canonical_name=name, brand=brand, category_path=None,
        store=store, price=None, currency="ILS", availability=True,
        product_url=None, match_score=0.5,
    )


def test_rerank_by_brand_matching_items_first():
    """Items whose brand contains the requested brand sort first."""
    from api.agent.tools.search_products import _rerank_by_brand

    items = [
        _make_product("A_Edifier", "Edifier"),
        _make_product("B_Sony", "Sony"),
        _make_product("C_NoBrand", None),
        _make_product("D_SonyCorp", "Sony Corp"),
    ]
    ranked = _rerank_by_brand(items, "Sony")
    names = [r.canonical_name for r in ranked]
    # Sony items first (B, D), then non-matching (Edifier), then None
    assert names == ["B_Sony", "D_SonyCorp", "A_Edifier", "C_NoBrand"]


def test_rerank_by_brand_case_insensitive():
    from api.agent.tools.search_products import _rerank_by_brand

    items = [
        _make_product("A_Other", "Edifier"),
        _make_product("B_SonyLower", "sony"),
    ]
    ranked = _rerank_by_brand(items, "SONY")
    assert ranked[0].canonical_name == "B_SonyLower"


def test_rerank_by_brand_preserves_within_tier_order():
    """Stable sort: original order maintained within each tier."""
    from api.agent.tools.search_products import _rerank_by_brand

    items = [
        _make_product("Sony1", "Sony"),
        _make_product("Sony2", "Sony"),
        _make_product("Sony3", "Sony"),
    ]
    ranked = _rerank_by_brand(items, "Sony")
    assert [r.canonical_name for r in ranked] == ["Sony1", "Sony2", "Sony3"]


def test_rerank_by_brand_noop_when_brand_empty():
    """Empty brand string → no rerank."""
    from api.agent.tools.search_products import _rerank_by_brand

    items = [
        _make_product("X", "Edifier"),
        _make_product("Y", "Sony"),
    ]
    assert _rerank_by_brand(items, "") == items
    assert _rerank_by_brand(items, "   ") == items


def test_rerank_by_brand_noop_when_results_empty():
    from api.agent.tools.search_products import _rerank_by_brand

    assert _rerank_by_brand([], "Sony") == []
