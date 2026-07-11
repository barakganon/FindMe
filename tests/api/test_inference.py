"""tests/api/test_inference.py — Coverage for api/inference.py.

`extract_and_update_attributes` is fire-and-forget (asyncio.create_task) passive
attribute inference. Per CLAUDE.md this must NEVER make real Gemini/DB calls in
tests and must NEVER blow up the caller — all failures are swallowed silently.
These tests exercise the raw-JSON parsing (fenced/unfenced), the scalar vs list
attribute upsert paths, and the silent-failure contract.
"""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from api.inference import extract_and_update_attributes

pytestmark = pytest.mark.anyio


def _completion_with_content(content: str) -> MagicMock:
    """Build a MagicMock standing in for an AsyncOpenAI ChatCompletion response."""
    completion = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    completion.choices = [choice]
    return completion


def _make_db_mock() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


async def test_extracts_scalar_and_list_attrs_from_plain_json():
    """Well-formed JSON (no fences) is parsed and both scalar + list attrs upsert."""
    payload = {
        "age_range": "25-35",
        "has_children": True,
        "child_age_range": "0-3",
        "gender": "female",
        "lifestyle": ["tech-enthusiast"],
        "price_sensitivity": "mid-range",
        "occasions": ["birthday"],
        "interests": ["gaming"],
        "confidence_notes": "explicit",
    }
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content(json.dumps(payload, ensure_ascii=False))
    )
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), "קניתי מתנה לבן 3 שלי", db, ai)

    # 5 scalar attrs (all truthy here) + 3 list attrs = 8 execute() calls
    assert db.execute.await_count == 8
    db.commit.assert_awaited_once()


async def test_has_children_bool_stored_as_string():
    """has_children is a Python bool; the source stringifies it before storing.

    Verify the exact string value passed to the upsert so a future refactor
    can't silently flip this to the Python repr or an int.
    """
    payload = {"has_children": True}
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content(json.dumps(payload))
    )
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), "יש לי ילדים", db, ai)

    calls = db.execute.await_args_list
    has_children_calls = [
        c for c in calls if c.args[1].get("attr") == "has_children"
    ]
    assert len(has_children_calls) == 1
    assert has_children_calls[0].args[1]["value"] == "True"


async def test_strips_markdown_json_fence_before_parsing():
    """Gemini often wraps JSON in ```json ... ``` — must still parse."""
    fenced = "```json\n" + json.dumps({"gender": "male"}) + "\n```"
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(return_value=_completion_with_content(fenced))
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), "אני גבר", db, ai)

    assert db.execute.await_count == 1
    db.commit.assert_awaited_once()


async def test_no_json_object_in_response_is_silently_skipped():
    """Response with no `{...}` substring at all — regex match fails, function
    returns early without touching the DB."""
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content("no useful info here")
    )
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), "בלה בלה", db, ai)

    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_malformed_json_inside_braces_is_swallowed():
    """Regex finds a `{...}` span but json.loads fails on it (e.g. trailing
    comma / truncated) — the broad except must swallow it, not raise."""
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content('{"gender": "male",}')  # trailing comma
    )
    db = _make_db_mock()

    # Must not raise.
    await extract_and_update_attributes(uuid4(), "test", db, ai)

    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_llm_call_exception_is_swallowed():
    """Network/API failure from the LLM client must never propagate — this
    runs fire-and-forget via asyncio.create_task() and must not affect the
    user-facing chat response."""
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), "test", db, ai)

    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_db_execute_exception_is_swallowed():
    """A DB failure mid-upsert must not raise out of the fire-and-forget task."""
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content(json.dumps({"gender": "female"}))
    )
    db = _make_db_mock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    await extract_and_update_attributes(uuid4(), "test", db, ai)

    db.commit.assert_not_awaited()


async def test_null_fields_are_not_upserted():
    """All-null payload (LLM found nothing) results in zero upserts but is not
    treated as an error — commit still runs since the try block reaches it."""
    payload = {
        "age_range": None,
        "has_children": None,
        "child_age_range": None,
        "gender": None,
        "lifestyle": [],
        "price_sensitivity": None,
        "occasions": [],
        "interests": [],
    }
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content(json.dumps(payload))
    )
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), "test", db, ai)

    db.execute.assert_not_awaited()
    db.commit.assert_awaited_once()


async def test_source_message_truncated_to_200_chars():
    """`source` column is populated from the raw user message, capped at 200
    chars per the source's `message[:200]` slice — verify the cap is applied."""
    long_message = "א" * 500
    ai = MagicMock()
    ai.chat.completions.create = AsyncMock(
        return_value=_completion_with_content(json.dumps({"gender": "male"}))
    )
    db = _make_db_mock()

    await extract_and_update_attributes(uuid4(), long_message, db, ai)

    call = db.execute.await_args_list[0]
    assert call.args[1]["source"] == long_message[:200]
    assert len(call.args[1]["source"]) == 200
