"""api/agent/tools/get_user_context.py — Personalization tool for the v2 agent (W3).

Returns the user's preferences, high-confidence inferred attributes, active
voucher cards, and recent search history. The agent uses this to:
- Default to the user's preferred city when a query is geo-ambiguous
- Honor a stored max_price preference when no budget is mentioned
- Surface "based on your last search…" framing in recommendations

Anonymous users (no `current_user` in tool_context) get an empty payload —
the agent must NOT rely on this for anon flows.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class GetUserContextParams(BaseModel):
    """No parameters — user is identified from tool_context.current_user."""
    pass


_PARAMS_SCHEMA = GetUserContextParams.model_json_schema()


_TOOL_DESCRIPTION = (
    "Look up the LOGGED-IN user's personalization data: explicit preferences "
    "(budget, preferred cities, categories), high-confidence inferred attributes "
    "(age range, gender, interests — only those with confidence ≥ 0.5), active "
    "voucher cards (network, balance, expiry), and last 3 search history items.\n\n"
    "Call this tool ONCE at the start of a turn when you suspect personalization "
    "would help — e.g. user said 'הפעם הקודמת' or 'באזור שלי הרגיל' or asked for "
    "a recommendation without specifying constraints.\n\n"
    "Do NOT call this tool every turn — it's slow (DB queries) and the user's "
    "context rarely changes within a single conversation.\n\n"
    "Returns an empty payload if the user is anonymous — anon flows must NOT depend on it."
)


GET_USER_CONTEXT_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "get_user_context",
        "description": _TOOL_DESCRIPTION,
        "parameters": _PARAMS_SCHEMA,
    },
}


async def execute_get_user_context(
    params: GetUserContextParams,
    *,
    db: AsyncSession,
    current_user: Optional[Any] = None,
    **_unused: object,
) -> tuple[list, str]:
    """
    Query user prefs + inferred + vouchers + history. Returns
    `(items, summary)` where items is empty (the tool's value is in the
    structured summary the loop serializes to the LLM) and summary is a
    Hebrew-prefixed JSON payload with all four sections.

    The runner-side `_serialize_tool_result_for_llm` will JSON-encode the
    summary, so the LLM sees the full context in machine-readable form.
    """
    if current_user is None or getattr(current_user, "id", None) is None:
        return [], "המשתמש לא מחובר"

    user_id = current_user.id
    # Local imports — models may not be loaded at agent module import time
    try:
        from db.models import (
            UserPreference,
            UserInferredAttribute,
            UserVoucherCard,
            UserSearchHistory,
        )
    except ImportError:
        return [], "מידע משתמש לא זמין"

    prefs = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    prefs_dict = {p.key: p.value for p in prefs.scalars().all()}

    inferred = await db.execute(
        select(UserInferredAttribute)
        .where(UserInferredAttribute.user_id == user_id)
        .where(UserInferredAttribute.confidence >= 0.5)
        .order_by(UserInferredAttribute.confidence.desc())
        .limit(5)
    )
    inferred_list = [
        {
            "attribute": a.attribute,
            "value": a.value,
            "confidence": round(float(a.confidence), 2),
        }
        for a in inferred.scalars().all()
    ]

    vouchers = await db.execute(
        select(UserVoucherCard)
        .where(UserVoucherCard.user_id == user_id)
        .where(UserVoucherCard.is_active.is_(True))
    )
    vouchers_list = [
        {
            "network": v.voucher_network,
            "nickname": v.nickname,
            "balance": float(v.balance) if v.balance is not None else None,
            "expiry": v.expiry_date.isoformat() if v.expiry_date else None,
        }
        for v in vouchers.scalars().all()
    ]

    history = await db.execute(
        select(UserSearchHistory)
        .where(UserSearchHistory.user_id == user_id)
        .order_by(UserSearchHistory.searched_at.desc())
        .limit(3)
    )
    history_list = [
        {
            "message": h.message,
            "intent": h.intent,
            "top_result": h.top_result_name,
        }
        for h in history.scalars().all()
    ]

    summary_obj = {
        "display_name": getattr(current_user, "display_name", None),
        "preferences": prefs_dict,
        "inferred_attributes": inferred_list,
        "voucher_cards": vouchers_list,
        "recent_searches": history_list,
    }

    summary = json.dumps(summary_obj, ensure_ascii=False, default=str)
    return [], summary
