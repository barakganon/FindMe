"""tests/api/test_tool_recall_history.py — Direct unit tests for the v2 agent's
recall_history tool (W8 / AC-4).

Validates that `execute_recall_history` reads `last_product_results`,
`last_store_results`, and `last_user_message` off `session_state` and
serializes them into a JSON payload. The tool itself does NOT resolve
ordinal/name references — picking "the first one" is the LLM's job once
it sees the JSON. The tool only accepts `turn_offset` constrained to
exactly 1 (ge=1, le=1).

Covered:
  - session_state=None → fixed Hebrew "new session" message
  - session_state with empty trays → "no prior searches" Hebrew message
  - Populated state → JSON payload with previous_user_message + counts + items
  - More than 5 items → only first 5 in previous_products / previous_stores;
    counts reflect the full length
  - Pydantic validation on turn_offset (rejects 0 and 2)

Fixtures: `tool_context` and `mock_db` from tests/api/conftest.py are
available but not required — recall_history reads only session_state (no DB).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from api.agent.session_memory import SessionState
from api.agent.tools.recall_history import (
    RecallHistoryParams,
    execute_recall_history,
)


@pytest.mark.anyio
async def test_no_session_returns_new_session_message():
    """When session_state is None, the tool returns a fixed Hebrew message."""
    items, summary = await execute_recall_history(
        RecallHistoryParams(),
        session_state=None,
    )
    assert items == []
    assert summary == "אין היסטוריה זמינה — סשן חדש"


@pytest.mark.anyio
async def test_empty_trays_return_no_searches_message():
    """When session_state has empty product and store trays, the tool returns
    the "no prior searches" Hebrew message.
    """
    state = SessionState.empty()
    items, summary = await execute_recall_history(
        RecallHistoryParams(),
        session_state=state,
    )
    assert items == []
    assert summary == "אין היסטוריה זמינה — לא בוצעו חיפושים קודמים"


@pytest.mark.anyio
async def test_populated_state_returns_json_payload():
    """With 3 product dicts and a user message, the summary is valid JSON
    containing previous_user_message, counts, and the items.
    """
    products = [{"product_id": f"p{i}", "canonical_name": f"Item {i}"} for i in range(3)]
    state = SessionState(
        last_product_results=products,
        last_store_results=[],
        last_user_message="אוזניות סוני",
    )

    items, summary = await execute_recall_history(
        RecallHistoryParams(),
        session_state=state,
    )

    assert items == []
    payload = json.loads(summary)
    assert payload["previous_user_message"] == "אוזניות סוני"
    assert payload["previous_product_count"] == 3
    assert payload["previous_store_count"] == 0
    assert payload["previous_products"] == products
    assert payload["previous_stores"] == []


@pytest.mark.anyio
async def test_more_than_five_items_capped_to_five_with_full_count():
    """When `last_product_results` has 7 items, only the first 5 are in the
    `previous_products` array, but `previous_product_count` reflects the full 7.
    """
    products = [{"product_id": f"p{i}", "canonical_name": f"Item {i}"} for i in range(7)]
    state = SessionState(
        last_product_results=products,
        last_user_message="x",
    )

    items, summary = await execute_recall_history(
        RecallHistoryParams(),
        session_state=state,
    )

    payload = json.loads(summary)
    assert payload["previous_product_count"] == 7
    assert len(payload["previous_products"]) == 5
    assert payload["previous_products"] == products[:5]


def test_turn_offset_zero_rejected():
    """`turn_offset=0` raises Pydantic ValidationError (ge=1)."""
    with pytest.raises(ValidationError):
        RecallHistoryParams(turn_offset=0)


def test_turn_offset_two_rejected():
    """`turn_offset=2` raises Pydantic ValidationError (le=1)."""
    with pytest.raises(ValidationError):
        RecallHistoryParams(turn_offset=2)
