"""api/routes/chat_v2.py — POST /api/chat/v2 — agentic conversation endpoint.

W2 thin slice: single tool (`search_products`), single LLM, no streaming, no
session memory persistence. Console-quality output only — the W2 question is
whether the model can call the tool correctly in Hebrew at ≥80% accuracy.

If the W2 kill-gate passes, W3 extends this with search_stores, get_user_context,
recall_history, clarify; W5 adds SSE streaming.

Anonymous users supported via `get_optional_user` — never blocked. Logged-in
users get their `User` injected into `tool_context` so future user-aware tools
(W3+) can read preferences / inferred attributes / history.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.loop import run_agent
from api.agent.tools import TOOL_SPECS, TOOLS
from api.auth import get_optional_user
from api.dependencies import get_ai_client, get_db, get_settings
from api.schemas import (
    AgentTrace,
    ChatRequest,
    ChatResponseV2,
    LocationFilter,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _infer_intent(terminated_by: str, trace: AgentTrace, message: str) -> str:
    """Best-effort intent label, for v1-shape backwards compat with the eval rubric.

    Maps the agent's terminated_by + tool-call signal to one of the v1 intent
    strings ('product_search' | 'store_search' | 'help' | 'clarify' | 'error').
    """
    # Errors and degraded terminations surface as an explicit "error" intent so
    # clients (and the eval harness) can distinguish them from real replies.
    if terminated_by in ("error", "safety_blocked", "empty_response"):
        return "error"

    tools_called = {tc.name for tc in trace.tool_calls if not tc.error}
    if "search_products" in tools_called:
        return "product_search"
    if "search_stores" in tools_called:  # W3+
        return "store_search"

    # No tools called — could be help or clarify. Use both message shape AND
    # length-in-characters (Hebrew counts as 1 char per codepoint in Python str,
    # so the threshold is roughly comparable across scripts).
    text = (message or "").strip()
    if not text or len(text) < 3:
        return "clarify"
    return "help"


@router.post("/chat/v2", response_model=ChatResponseV2)
async def chat_v2(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
    current_user: Annotated[Optional[object], Depends(get_optional_user)] = None,
) -> ChatResponseV2:
    """Run one turn of the agentic conversation loop and return the result."""
    settings = get_settings()
    started = time.monotonic()

    # Build a LocationFilter from session_context GPS if both coords present.
    # If exactly one coordinate is supplied, that's a client bug — log it
    # rather than silently ignoring (which would manifest as empty "near me"
    # results with no signal of why).
    location: Optional[LocationFilter] = None
    sc = body.session_context
    if sc:
        if sc.user_lat is not None and sc.user_lng is not None:
            location = LocationFilter(
                lat=sc.user_lat,
                lng=sc.user_lng,
                radius_km=10.0,
            )
        elif sc.user_lat is not None or sc.user_lng is not None:
            logger.warning(
                "chat_v2: session_context has partial GPS (lat=%r, lng=%r) — ignoring",
                sc.user_lat, sc.user_lng,
            )

    tool_context = {
        "db": db,
        "api_key": settings.gemini_api_key,
        "location": location,
        # current_user is None for anonymous; future user-aware tools (W3+)
        # can branch on its presence to fetch preferences / inferred attrs.
        "current_user": current_user,
    }

    result = await run_agent(
        message=body.message,
        history=body.history,
        llm_client=ai,
        model="gemini-2.5-flash",
        tools=TOOL_SPECS,
        tool_registry=TOOLS,
        tool_context=tool_context,
    )

    elapsed_ms = (time.monotonic() - started) * 1000

    trace = AgentTrace(
        tool_calls=result.tool_calls,
        iterations=result.iterations,
        total_latency_ms=result.total_latency_ms,
        total_cost_usd=result.total_cost_usd,
        terminated_by=result.terminated_by,
    )

    return ChatResponseV2(
        message=result.message,
        intent=_infer_intent(result.terminated_by, trace, body.message),
        product_results=result.product_results or None,
        store_results=result.store_results or None,
        needs_location=False,  # W2: no needs_location tool yet — falls back to false
        voucher_network=body.voucher_network,
        search_time_ms=elapsed_ms,
        trace=trace,
    )
