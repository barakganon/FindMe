"""api/routes/chat_v2.py — POST /api/chat/v2 — agentic conversation endpoint.

W3 thin slice extended: 5 tools (search_products, search_stores,
get_user_context, recall_history, clarify) + Redis-backed session memory
so multi-turn references work without the client passing full history.

W5 will add SSE streaming. W7 will polish UI affordances.

Anonymous users supported via `get_optional_user` — never blocked. Anonymous
users that want memory across requests pass an `X-Session-ID: <uuid>` header
(frontend generates per device). Logged-in users get memory keyed by user.id.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from openai import AsyncOpenAI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.cost_guard import (
    is_over_budget,
    register_cost,
    seconds_until_midnight_utc,
)
from api.agent.invite_allowlist import block_reason, is_allowed
from api.agent.loop import run_agent
from api.agent.session_memory import (
    derive_session_id,
    load_session_state,
    save_session_state,
)
from api.agent.tools import TOOL_SPECS, TOOLS
from api.auth import get_optional_user
from api.dependencies import get_ai_client, get_db, get_redis, get_settings
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

    Maps the agent's terminated_by + tool-call signal to one of the intent
    strings: 'product_search' | 'store_search' | 'help' | 'clarify' | 'error'.
    """
    # Errors and degraded terminations surface as an explicit "error" intent.
    if terminated_by in ("error", "safety_blocked", "empty_response"):
        return "error"

    tools_called = {tc.name for tc in trace.tool_calls if not tc.error}

    # Explicit clarification has priority over other tools — when the agent
    # calls clarify, the intent is "the user needs to answer" regardless of
    # any other tool that may have run in the same turn.
    if "clarify" in tools_called:
        return "clarify"

    if "search_products" in tools_called:
        return "product_search"
    if "search_stores" in tools_called:
        return "store_search"
    # get_user_context / recall_history alone aren't a user-visible intent;
    # they're support tools. Fall through to the heuristic.

    text = (message or "").strip()
    if not text or len(text) < 3:
        return "clarify"
    return "help"


@router.post("/chat/v2", response_model=ChatResponseV2)
async def chat_v2(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[Optional[object], Depends(get_optional_user)] = None,
    x_session_id: Annotated[Optional[str], Header(alias="X-Session-ID")] = None,
) -> ChatResponseV2:
    """Run one turn of the agentic conversation loop and return the result."""
    # W5 gates: invite allowlist + daily cost budget. Both no-op by default
    # (env vars off) and only activate when explicitly turned on for the
    # soft-launch window.
    if not is_allowed(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=block_reason(current_user),
        )
    if await is_over_budget(redis):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "v2 daily cost budget exhausted",
                "fallback": "/api/chat",
            },
            headers={"Retry-After": str(seconds_until_midnight_utc())},
        )

    settings = get_settings()
    started = time.monotonic()

    # Session id: user.id (logged-in) > X-Session-ID header (anon w/ persistence)
    # > None (anonymous single-turn, no memory)
    session_id = derive_session_id(current_user, x_session_id)

    # Load prior turn's tray from Redis (graceful empty state if unavailable).
    session_state = await load_session_state(redis, session_id)

    # Build a LocationFilter from session_context GPS if both coords present.
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
        "current_user": current_user,
        "session_state": session_state,  # recall_history reads from here
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

    # Persist this turn's tray into session memory for the next turn's recall.
    # No-op if Redis is unavailable or session_id is None.
    await save_session_state(
        redis,
        session_id,
        product_results=result.product_results,
        store_results=result.store_results,
        user_message=body.message,
        assistant_message=result.message,
    )

    trace = AgentTrace(
        tool_calls=result.tool_calls,
        iterations=result.iterations,
        total_latency_ms=result.total_latency_ms,
        total_cost_usd=result.total_cost_usd,
        terminated_by=result.terminated_by,
    )

    intent = _infer_intent(result.terminated_by, trace, body.message)

    # Best-effort telemetry insert. Never blocks the response on failure —
    # if the DB insert raises (constraint, connection drop, schema drift),
    # we log and proceed. Telemetry is for observability, not correctness.
    await _record_trace(
        db,
        session_id=session_id,
        user_id=getattr(current_user, "id", None),
        message=body.message,
        intent=intent,
        trace=trace,
        voucher_network=body.voucher_network,
    )

    # Register this turn's cost in the daily counter. Best-effort.
    await register_cost(redis, result.total_cost_usd)

    return ChatResponseV2(
        message=result.message,
        intent=intent,
        product_results=result.product_results or None,
        store_results=result.store_results or None,
        # needs_location is now True when the agent called clarify with a
        # location-related question. Simple heuristic for W3; W5+ can refine.
        needs_location=_looks_like_location_prompt(trace),
        voucher_network=body.voucher_network,
        search_time_ms=elapsed_ms,
        trace=trace,
    )


async def _record_trace(
    db: AsyncSession,
    *,
    session_id: Optional[str],
    user_id: Optional[object],
    message: str,
    intent: str,
    trace: AgentTrace,
    voucher_network: str,
) -> None:
    """Insert one row into agent_traces. Best-effort — never raises."""
    try:
        from db.models import AgentTrace as AgentTraceModel

        # Serialize tool calls to JSON-safe dicts for the JSONB column.
        tool_calls_payload = [
            {
                "name": tc.name,
                "args": tc.args,
                "duration_ms": tc.duration_ms,
                "error": tc.error,
                "result_count": tc.result_count,
            }
            for tc in trace.tool_calls
        ]

        row = AgentTraceModel(
            session_id=session_id,
            user_id=user_id,
            message=message,
            intent=intent,
            tool_calls=tool_calls_payload,
            iterations=trace.iterations,
            total_latency_ms=trace.total_latency_ms,
            total_cost_usd=trace.total_cost_usd,
            terminated_by=trace.terminated_by,
            voucher_network=voucher_network,
        )
        db.add(row)
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — telemetry must never break chat
        logger.warning("chat_v2: agent_trace insert failed (%s) — proceeding", exc)
        try:
            await db.rollback()
        except Exception:
            pass


_LOCATION_KEYWORDS_IN_PROMPT = ("מהיכן", "מיקום", "עיר", "GPS", "location", "where are you")


def _looks_like_location_prompt(trace: AgentTrace) -> bool:
    """If the agent called clarify with a location-shaped question, surface
    needs_location=True so the frontend can offer a GPS button.
    """
    for tc in trace.tool_calls:
        if tc.name == "clarify" and not tc.error:
            q = (tc.args.get("question") or "") if isinstance(tc.args, dict) else ""
            if any(kw in q for kw in _LOCATION_KEYWORDS_IN_PROMPT):
                return True
    return False
