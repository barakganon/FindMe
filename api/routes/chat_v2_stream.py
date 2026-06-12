"""api/routes/chat_v2_stream.py — POST /api/chat/v2/stream — SSE streaming variant of v2.

W5 thin slice. The agent loop itself doesn't yet yield partial LLM tokens
(would require integrating Gemini's stream=True + refactoring run_agent into
an async generator). For now this endpoint:

1. Emits a `thinking` SSE event immediately so the frontend can render
   "מחפש בקטלוג…" without waiting for the LLM round-trip.
2. Awaits the full `run_agent` call (same path as /api/chat/v2).
3. Emits a `tool_call` event per tool that was invoked.
4. Emits a `final` event with the full ChatResponseV2 shape.

True token-level streaming is a follow-up — see deferred-work.md.

Same gates as /api/chat/v2: cost guard, invite allowlist.
"""


import asyncio
import json
import logging
import time
from typing import Annotated, AsyncIterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from api.agent.cost_guard import (
    daily_budget_usd,
    is_over_budget,
    is_session_over_budget,
    register_cost,
    register_session_cost,
    seconds_until_midnight_utc,
    session_budget_usd,
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
from api.dependencies import get_ai_client, get_db, get_redis, get_settings, limiter
from api.schemas import (
    AgentTrace,
    ChatRequest,
    ChatResponseV2,
    LocationFilter,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse(event: str, data: dict) -> str:
    """Format a single SSE event."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/chat/v2/stream")
@limiter.limit(get_settings().chat_rate_limit)
async def chat_v2_stream(
    request: Request,
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[Optional[object], Depends(get_optional_user)] = None,
    x_session_id: Annotated[Optional[str], Header(alias="X-Session-ID")] = None,
) -> StreamingResponse:
    """Streaming variant of /api/chat/v2 — see module docstring for event contract."""
    # ----- Gates (same as /api/chat/v2) -----
    if not is_allowed(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=block_reason(current_user))

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
    session_id = derive_session_id(current_user, x_session_id)

    # Per-session cost cap (W9): circuit-break before run_agent if this session
    # has already spent its budget. Uses same 503+fallback shape as daily guard.
    if session_id and await is_session_over_budget(redis, session_id, session_budget_usd()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "v2 session cost budget exhausted",
                "fallback": "/api/chat",
            },
            headers={"Retry-After": str(seconds_until_midnight_utc())},
        )
    session_state = await load_session_state(redis, session_id)

    location: Optional[LocationFilter] = None
    sc = body.session_context
    if sc and sc.user_lat is not None and sc.user_lng is not None:
        location = LocationFilter(lat=sc.user_lat, lng=sc.user_lng, radius_km=10.0)

    tool_context = {
        "db": db,
        "api_key": settings.gemini_api_key,
        "location": location,
        "current_user": current_user,
        "session_state": session_state,
    }

    async def event_stream() -> AsyncIterator[str]:
        # 1. Immediate "thinking" event — lets the frontend render before LLM round-trip
        yield _sse("thinking", {"stage": "thinking"})

        # 2. Run the agent (no partial events yet — true token streaming is W5+)
        try:
            result = await run_agent(
                message=body.message,
                history=body.history,
                llm_client=ai,
                model="gemini-2.5-flash",
                tools=TOOL_SPECS,
                tool_registry=TOOLS,
                tool_context=tool_context,
            )
        except Exception as exc:  # noqa: BLE001 — surface to client
            logger.exception("chat_v2_stream: run_agent failed")
            yield _sse("error", {"error": f"{type(exc).__name__}: {exc}"})
            return

        elapsed_ms = (time.monotonic() - started) * 1000

        # 3. Emit one tool_call event per tool that was invoked
        for tc in result.tool_calls:
            yield _sse(
                "tool_call",
                {
                    "name": tc.name,
                    "args": tc.args,
                    "duration_ms": tc.duration_ms,
                    "error": tc.error,
                    "result_count": tc.result_count,
                },
            )

        # 4. Persist memory + register cost (best-effort, don't fail the stream)
        try:
            await save_session_state(
                redis,
                session_id,
                product_results=result.product_results,
                store_results=result.store_results,
                user_message=body.message,
                assistant_message=result.message,
                tool_calls=result.tool_calls,
            )
        except Exception:
            pass
        try:
            await register_cost(redis, result.total_cost_usd)
        except Exception:
            pass
        try:
            await register_session_cost(redis, session_id, result.total_cost_usd)
        except Exception:
            pass

        # 4b. Build memory chips from fresh state — must run AFTER save (W7).
        # Best-effort: chip-building failure must never break the stream.
        chips: list = []
        try:
            from api.agent.chips import build_chips
            fresh_state = await load_session_state(redis, session_id)
            chips = await build_chips(current_user, fresh_state, db)
        except Exception:
            pass

        # 5. Final event with the same shape as ChatResponseV2 (frontend can render results)
        trace = AgentTrace(
            tool_calls=result.tool_calls,
            iterations=result.iterations,
            total_latency_ms=result.total_latency_ms,
            total_cost_usd=result.total_cost_usd,
            terminated_by=result.terminated_by,
        )
        from api.routes.chat_v2 import _infer_intent, _looks_like_location_prompt

        final_response = ChatResponseV2(
            message=result.message,
            intent=_infer_intent(result.terminated_by, trace, body.message),
            product_results=result.product_results or None,
            store_results=result.store_results or None,
            needs_location=_looks_like_location_prompt(trace),
            voucher_network=body.voucher_network,
            search_time_ms=elapsed_ms,
            chips=chips,
            trace=trace,
        )
        # Serialize via Pydantic to get nested dicts (model_dump returns plain dict)
        yield _sse("final", final_response.model_dump(mode="json"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for proxies
        },
    )
