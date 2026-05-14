"""api/routes/chat_v2.py — POST /api/chat/v2 — agentic conversation endpoint.

W2 thin slice: single tool (`search_products`), single LLM, no streaming, no
session memory persistence. Console-quality output only — the W2 question is
whether the model can call the tool correctly in Hebrew at ≥80% accuracy.

If the W2 kill-gate passes, W3 extends this with search_stores, get_user_context,
recall_history, clarify; W5 adds SSE streaming.

Anonymous users supported via `get_optional_user` — never blocked.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.loop import run_agent
from api.agent.tools import TOOL_SPECS, TOOLS
from api.dependencies import get_ai_client, get_db, get_settings
from api.schemas import (
    AgentTrace,
    ChatRequest,
    ChatResponseV2,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _infer_intent(trace: AgentTrace, message: str) -> str:
    """Best-effort intent label from the trace, for v1-shape backwards compat.

    Maps to the four v1 intent strings so eval scoring + clients keep working.
    """
    tools_called = {tc.name for tc in trace.tool_calls}
    if "search_products" in tools_called:
        return "product_search"
    if "search_stores" in tools_called:  # W3+
        return "store_search"
    # No tools called — could be help/clarify. Heuristic:
    if not message or len(message.strip()) < 4:
        return "clarify"
    return "help"


@router.post("/chat/v2", response_model=ChatResponseV2)
async def chat_v2(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
) -> ChatResponseV2:
    """Run one turn of the agentic conversation loop and return the result."""
    settings = get_settings()
    started = time.monotonic()

    location = None
    if body.session_context and body.session_context.user_lat is not None and body.session_context.user_lng is not None:
        # Build a LocationFilter shim for tools that take optional location
        from api.schemas import LocationFilter

        location = LocationFilter(
            lat=body.session_context.user_lat,
            lng=body.session_context.user_lng,
            radius_km=10.0,
        )

    tool_context = {
        "db": db,
        "api_key": settings.gemini_api_key,
        "location": location,
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
        terminated_by=result.terminated_by,
    )

    return ChatResponseV2(
        message=result.message,
        intent=_infer_intent(trace, body.message),
        product_results=result.product_results or None,
        store_results=result.store_results or None,
        needs_location=False,  # W2: no needs_location tool yet — falls back to false
        voucher_network=body.voucher_network,
        search_time_ms=elapsed_ms,
        trace=trace,
    )
