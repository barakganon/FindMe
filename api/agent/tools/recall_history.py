"""api/agent/tools/recall_history.py — Recall the last turn's tray (W3).

Reads from Redis-backed session memory so multi-turn references like "the
first one" / "תראה לי שוב" / "מה ההבדל בין השני לשלישי?" work without the
client passing full history.

If no session memory is available (anonymous without X-Session-ID, or empty
session), returns an empty payload and the agent should fall back to asking.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RecallHistoryParams(BaseModel):
    """How far back to look. W3 supports only the last turn."""

    turn_offset: int = Field(
        1,
        description="How many turns back to recall. Currently only 1 is supported (the immediately previous turn).",
        ge=1,
        le=1,
    )


_PARAMS_SCHEMA = RecallHistoryParams.model_json_schema()


_TOOL_DESCRIPTION = (
    "Recall the PRODUCTS and STORES the user saw in the previous turn of this "
    "conversation. Use this when the user refers back: 'תראה לי שוב', 'הראשונה', "
    "'מה ההבדל בין השני לשלישי?', 'like last week', 'the previous results'.\n\n"
    "Call this BEFORE search_products / search_stores when the user is asking "
    "about something they've already seen — avoids redundant searches and "
    "preserves the user's place in the conversation.\n\n"
    "Returns `last_product_results` and `last_store_results` from session memory. "
    "Returns empty if no prior turn is recorded (anonymous user with no session, "
    "or first turn of the conversation)."
)


RECALL_HISTORY_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "recall_history",
        "description": _TOOL_DESCRIPTION,
        "parameters": _PARAMS_SCHEMA,
    },
}


async def execute_recall_history(
    params: RecallHistoryParams,
    *,
    session_state: Optional[object] = None,
    **_unused: object,
) -> tuple[list, str]:
    """
    Return prior turn's tray from session_state (passed via tool_context).

    Returns an items list (empty — the actual data is in the summary JSON
    so the LLM sees structured fields per the loop's serialization contract)
    and a summary string that is the JSON payload of the recalled tray.
    """
    if session_state is None:
        return [], "אין היסטוריה זמינה — סשן חדש"

    products = getattr(session_state, "last_product_results", None) or []
    stores = getattr(session_state, "last_store_results", None) or []
    last_msg = getattr(session_state, "last_user_message", "") or ""

    if not products and not stores:
        return [], "אין היסטוריה זמינה — לא בוצעו חיפושים קודמים"

    # Return the recall payload as the summary; the loop's serializer puts
    # this into the role=tool content for the LLM.
    import json

    payload = {
        "previous_user_message": last_msg,
        "previous_product_count": len(products),
        "previous_store_count": len(stores),
        "previous_products": products[:5],   # top 5 to keep payload bounded
        "previous_stores": stores[:5],
    }
    return [], json.dumps(payload, ensure_ascii=False, default=str)
