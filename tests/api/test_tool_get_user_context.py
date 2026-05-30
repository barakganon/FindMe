"""tests/api/test_tool_get_user_context.py — Direct unit tests for the v2 agent's
get_user_context tool (W8 / AC-3).

Strategy: stub `db.execute` to return a chain of mock results — one per
SELECT issued by the tool (prefs, inferred, vouchers, history). Verify:

  - Anonymous (current_user=None) → empty payload, "המשתמש לא מחובר"
  - Logged-in with preferences only → prefs serialized into JSON summary
  - Logged-in with HIGH-confidence inferred only → inferred listed
  - Logged-in with both prefs + inferred → both appear, prefs first
  - DB error → graceful Hebrew "מידע משתמש לא זמין" via ImportError path
  - Confidence boundary: 0.5 is INCLUDED (>= threshold), 0.499 is EXCLUDED
    (this is enforced by the SQL `confidence >= 0.5` predicate — tests
    simulate by returning rows the mock pretends survived the WHERE clause)

Note: the tool uses `confidence >= 0.5` (SQL-level, not Python-level).
The boundary test relies on configuring the mock to behave as if the SQL
filter has already been applied: rows with confidence=0.5 ARE in the mock
result; rows with confidence=0.499 are NOT. This is the same contract the
production DB enforces.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.agent.tools.get_user_context import (
    GetUserContextParams,
    execute_get_user_context,
)
from tests.api.conftest import make_db_result, make_user


def _wire_execute(db: MagicMock, *result_lists) -> None:
    """Bind db.execute as an AsyncMock that returns make_db_result(...)
    for each consecutive SELECT issued by the tool.
    """
    db.execute = AsyncMock(
        side_effect=[make_db_result(*items) for items in result_lists]
    )


@pytest.mark.anyio
async def test_anonymous_user_returns_not_signed_in(tool_context):
    """current_user=None → empty items + Hebrew "not signed in" summary."""
    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )
    assert items == []
    assert summary == "המשתמש לא מחובר"


@pytest.mark.anyio
async def test_user_without_id_returns_not_signed_in(tool_context):
    """A current_user object with id=None is treated as anonymous."""
    tool_context["current_user"] = SimpleNamespace(id=None)
    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )
    assert items == []
    assert summary == "המשתמש לא מחובר"


@pytest.mark.anyio
async def test_preferences_only(tool_context):
    """User with prefs but no inferred / vouchers / history.

    The summary JSON includes the preferences dict; inferred is empty.
    """
    tool_context["current_user"] = make_user()
    prefs = [
        SimpleNamespace(key="city", value="תל אביב"),
        SimpleNamespace(key="max_price", value="500"),
    ]
    _wire_execute(tool_context["db"], prefs, [], [], [])

    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )

    assert items == []
    payload = json.loads(summary)
    assert payload["preferences"] == {"city": "תל אביב", "max_price": "500"}
    assert payload["inferred_attributes"] == []
    assert payload["voucher_cards"] == []
    assert payload["recent_searches"] == []


@pytest.mark.anyio
async def test_inferred_only_high_confidence(tool_context):
    """User with only high-confidence inferred attributes.

    Confidence is rounded to 2 decimals in the payload.
    """
    tool_context["current_user"] = make_user()
    inferred = [
        SimpleNamespace(attribute="age_range", value="25-34", confidence=0.85),
        SimpleNamespace(attribute="gender", value="female", confidence=0.62),
    ]
    _wire_execute(tool_context["db"], [], inferred, [], [])

    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )

    payload = json.loads(summary)
    assert payload["preferences"] == {}
    assert payload["inferred_attributes"] == [
        {"attribute": "age_range", "value": "25-34", "confidence": 0.85},
        {"attribute": "gender", "value": "female", "confidence": 0.62},
    ]


@pytest.mark.anyio
async def test_both_prefs_and_inferred(tool_context):
    """Both prefs and inferred populate the summary together; prefs come first
    (by virtue of being the first key in the dict the tool builds).
    """
    tool_context["current_user"] = make_user()
    prefs = [SimpleNamespace(key="city", value="ירושלים")]
    inferred = [SimpleNamespace(attribute="interests", value="hiking", confidence=0.75)]
    _wire_execute(tool_context["db"], prefs, inferred, [], [])

    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )

    payload = json.loads(summary)
    assert payload["preferences"] == {"city": "ירושלים"}
    assert payload["inferred_attributes"][0]["attribute"] == "interests"
    # Dict insertion order — display_name → preferences → inferred → vouchers → recent
    keys = list(payload.keys())
    assert keys.index("preferences") < keys.index("inferred_attributes")


@pytest.mark.anyio
async def test_confidence_05_included_0499_excluded(tool_context):
    """Per the SQL predicate `confidence >= 0.5`, a row with confidence=0.5
    is included; 0.499 is excluded (the mock simulates the filtered set).
    Confidence is rounded to 2 decimals in the payload.
    """
    tool_context["current_user"] = make_user()
    # Mock returns only the 0.5 row — the 0.499 row was filtered by SQL
    inferred = [SimpleNamespace(attribute="time_of_day", value="evening", confidence=0.5)]
    _wire_execute(tool_context["db"], [], inferred, [], [])

    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )

    payload = json.loads(summary)
    assert payload["inferred_attributes"] == [
        {"attribute": "time_of_day", "value": "evening", "confidence": 0.5},
    ]


@pytest.mark.anyio
async def test_db_unavailable_returns_graceful_message(tool_context, monkeypatch):
    """If `db.models` cannot be imported (ImportError path), the tool returns
    the Hebrew "info unavailable" fallback without raising.
    """
    tool_context["current_user"] = make_user()
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def fake_import(name, *args, **kwargs):
        if name == "db.models":
            raise ImportError("simulated db.models import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    items, summary = await execute_get_user_context(
        GetUserContextParams(),
        **tool_context,
    )
    assert items == []
    assert summary == "מידע משתמש לא זמין"
