"""tests/api/test_tool_clarify.py — Direct unit tests for the v2 agent's
clarify tool (W8 / AC-5).

`execute_clarify` is a pure pass-through: it accepts a `ClarifyParams` with
a single required field `question: str` (min_length=1, max_length=300) and
returns `(items=[], summary=params.question)`. There is no `kind` discriminator,
no branching on question type, and no recall/search behavior — the tool's
only job is to record the Hebrew question so `_infer_intent` can map the
turn to `intent="clarify"`.

Covered:
  - Happy path: question echoed verbatim
  - 300-character boundary: accepted, echoed unchanged
  - Empty question rejected (min_length=1)
  - Over-length (301-char) rejected (max_length=300)
  - Extra kwargs ignored via **_unused

Fixtures: `tool_context` and `mock_db` from tests/api/conftest.py are
available but not required by these tests (execute_clarify is stateless).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.agent.session_memory import SessionState
from api.agent.tools.clarify import ClarifyParams, execute_clarify


@pytest.mark.anyio
async def test_happy_path_echoes_question():
    """The summary is the question verbatim; items is the empty list."""
    items, summary = await execute_clarify(
        ClarifyParams(question="מהיכן אתה?"),
    )
    assert items == []
    assert summary == "מהיכן אתה?"


@pytest.mark.anyio
async def test_300_char_question_accepted_and_echoed():
    """A 300-character Hebrew question is accepted and echoed back unchanged."""
    question = "א" * 300
    items, summary = await execute_clarify(ClarifyParams(question=question))
    assert items == []
    assert summary == question
    assert len(summary) == 300


def test_empty_question_rejected():
    """ClarifyParams(question='') raises ValidationError (min_length=1)."""
    with pytest.raises(ValidationError):
        ClarifyParams(question="")


def test_over_length_question_rejected():
    """A 301-character question raises ValidationError (max_length=300)."""
    with pytest.raises(ValidationError):
        ClarifyParams(question="א" * 301)


@pytest.mark.anyio
async def test_extra_kwargs_swallowed_by_unused_kwargs():
    """`**_unused` swallows extra context keys; the return contract is unchanged."""
    items, summary = await execute_clarify(
        ClarifyParams(question="?מה התקציב שלך"),
        db="ignored",
        api_key="ignored",
        location="ignored",
        current_user="ignored",
        session_state=SessionState.empty(),  # use proper type; string would silently AttributeError if ever read
        anything_else=123,
    )
    assert items == []
    assert summary == "?מה התקציב שלך"
