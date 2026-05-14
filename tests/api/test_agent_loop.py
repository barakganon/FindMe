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
