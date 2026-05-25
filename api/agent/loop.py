"""api/agent/loop.py — Provider-agnostic tool-calling agent loop.

The agent receives a user message + history + tool registry, drives an LLM
through alternating reasoning/tool-execution turns, and returns the final
assistant text + accumulated tool results + a trace.

Provider-agnostic: uses the OpenAI SDK shape only. Swapping Gemini for
Claude/GPT-4o means changing `base_url` + `model` in `get_ai_client` —
no changes here.

Safety:
- `max_iterations` caps runaway loops (default 5)
- `cost_budget_usd` caps spend per call (default $0.10/turn — generous for W2)
- Tool execution errors are captured into trace as `error=...` messages
  back to the LLM; the loop continues so the LLM can recover
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from api.schemas import ChatMessage, ProductResult, ToolCallTrace

logger = logging.getLogger(__name__)


# Gemini-2.5-flash pricing as of 2026 (USD per token). Used to estimate
# cumulative cost when the API returns usage. If usage is missing, we
# fall back to a character-based estimate so the cost_budget guard still
# fires in degraded mode.
_PRICE_PER_INPUT_TOKEN = 0.075 / 1_000_000
_PRICE_PER_OUTPUT_TOKEN = 0.30 / 1_000_000
_CHARS_PER_TOKEN_ESTIMATE = 4  # rough fallback when usage is absent

# Per-tool execution timeout. Catches a hung _run_product_search etc.
# without strangling slow-but-legitimate work.
_DEFAULT_TOOL_TIMEOUT_S = 25.0

# Cap on accumulated product results across all tool calls in one turn.
# Prevents a runaway loop from returning 50+ duplicate cards.
_MAX_ACCUMULATED_RESULTS = 20


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Result of one full `run_agent` invocation."""

    message: str
    product_results: list[ProductResult] = field(default_factory=list)
    store_results: list = field(default_factory=list)  # placeholder for W3 store tool
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    iterations: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    # Assistant reasoning preamble emitted alongside tool_calls (some providers
    # do this — preserve for trace/debug rather than dropping silently).
    intermediate_content: list[str] = field(default_factory=list)
    # "content" | "max_iterations" | "cost_budget" | "error" | "safety_blocked" | "empty_response"
    terminated_by: str = "content"


def _estimate_call_cost(completion: Any, messages: list[dict[str, Any]]) -> float:
    """Estimate cost in USD for one LLM round-trip.

    Prefers the provider's usage object. Falls back to a conservative
    character-count estimate when usage isn't exposed.
    """
    usage = getattr(completion, "usage", None)
    if usage is not None:
        in_tokens = getattr(usage, "prompt_tokens", 0) or 0
        out_tokens = getattr(usage, "completion_tokens", 0) or 0
        return (in_tokens * _PRICE_PER_INPUT_TOKEN) + (out_tokens * _PRICE_PER_OUTPUT_TOKEN)
    # Fallback: rough char-count estimate. Conservative on the high side so
    # the cost guard fires earlier rather than later in degraded mode.
    in_chars = sum(len(str(m.get("content") or "")) for m in messages)
    in_tokens = max(1, in_chars // _CHARS_PER_TOKEN_ESTIMATE)
    out_chars = 0
    if getattr(completion, "choices", None):
        choice = completion.choices[0]
        msg = getattr(choice, "message", None)
        if msg is not None:
            out_chars = len(str(getattr(msg, "content", "") or ""))
    out_tokens = max(1, out_chars // _CHARS_PER_TOKEN_ESTIMATE)
    return (in_tokens * _PRICE_PER_INPUT_TOKEN) + (out_tokens * _PRICE_PER_OUTPUT_TOKEN)


# ---------------------------------------------------------------------------
# Default system prompt (W2 minimal — full Sally voice lands in W7)
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """\
You are FindMe — a Hebrew-first chat assistant that helps Israeli BuyMe \
gift-card holders find products and stores.

Tools (call AT MOST one per turn unless absolutely necessary):
- search_products: items to buy (electronics, fashion, gifts, etc.)
- search_stores: places to visit (restaurants, spas, retail, hotels)
- get_user_context: logged-in user's prefs/inferred/vouchers (skip for anon)
- recall_history: previous turn's tray — call when user says הראשונה / תראה לי שוב / כמו פעם שעברה
- clarify: ask ONE Hebrew question when you can't produce useful results

Routing rules:
- Product mentioned ("אוזניות סוני", "סמסונג", "מתנה לאמא 300") → search_products
  ALWAYS pass brand via brand= parameter, never bury it inside query
  Single-brand-only ("סמסונג", "Apple") is enough — do NOT ask follow-ups
- Place mentioned ("מסעדות בתל אביב", "ספא בירושלים") → search_stores
  Pass city verbatim (the synonym layer handles תל אביב ↔ ת"א ↔ Tel Aviv)
- "near me" / "לידי" / "באזור שלי" without GPS → clarify('מהיכן אתה?')
- Reference to prior turn → recall_history FIRST, then compose
- Generic help ("מה אפשר לקנות", "איך זה עובד", "what is this") → respond
  directly in Hebrew without calling any tool
- Whitespace / emoji-only / SQL-injection / 1-2 char nonsense → clarify

Reply style (after tools return):
- Hebrew only (even if user wrote English — keep brand/product names verbatim)
- 2-3 sentences max — user is on phone
- Reference the top result by name + price
- Empty results → suggest a related search
- Never invent prices, brands, or stores
"""


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


async def run_agent(
    *,
    message: str,
    history: list[ChatMessage],
    llm_client: AsyncOpenAI,
    model: str = "gemini-2.5-flash",
    tools: list[dict],
    tool_registry: dict[str, tuple[type[BaseModel], Callable]],
    tool_context: dict[str, Any],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_iterations: int = 5,
    request_timeout_s: float = 30.0,
    cost_budget_usd: float = 0.10,
    tool_timeout_s: float = _DEFAULT_TOOL_TIMEOUT_S,
) -> AgentResult:
    """
    Drive the LLM through tool-calling iterations until it returns final content
    (or we hit max_iterations / cost_budget_usd / a hard timeout).

    Arguments:
        message: the user's latest message
        history: previous turns (role=user|assistant) — sent as conversation context
        llm_client: OpenAI-compatible async client (Gemini, Claude, GPT-4o, etc.)
        model: model name string passed to the LLM
        tools: list of tool specs in OpenAI tool-calling format (passed to LLM)
        tool_registry: dispatch table {tool_name: (Pydantic Params class, async executor)}
        tool_context: kwargs forwarded to every tool executor (db, api_key, etc.)
        system_prompt: agent persona + behavior rules
        max_iterations: hard cap on tool→LLM round-trips
        request_timeout_s: per-LLM-call timeout
        cost_budget_usd: cumulative USD spend cap; loop terminates with
            terminated_by="cost_budget" once exceeded. Uses completion.usage
            when available, falls back to a character-count estimate otherwise.
        tool_timeout_s: per-tool-execution timeout (catches a hung tool)

    Returns:
        AgentResult with the final message, accumulated results, trace, and
        the terminated_by signal that callers use to map to user-visible intent.
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    start = time.monotonic()
    result = AgentResult(message="")
    cost_usd_so_far = 0.0

    # Build the conversation: system + history + new message
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for h in history:
        # Drop 'tool' role messages from history — they lack tool_call_id
        # and replaying them produces 400s on most providers. Memory replay
        # lands in W3 with a richer ChatMessage schema. Coerce any other
        # unexpected role to 'user' rather than dropping (preserves content).
        if h.role == "tool":
            continue
        role = h.role if h.role in ("user", "assistant") else "user"
        messages.append({"role": role, "content": h.content})
    messages.append({"role": "user", "content": message})

    for iteration in range(max_iterations):
        result.iterations = iteration + 1

        # Call the LLM
        try:
            completion = await asyncio.wait_for(
                llm_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    temperature=0,
                    max_tokens=512,
                ),
                timeout=request_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning("agent.loop: LLM call timed out at iter=%d", iteration + 1)
            result.message = "אירעה שגיאת זמן בעת חיפוש. נסה שוב."
            result.terminated_by = "error"
            break
        except Exception as exc:
            logger.exception("agent.loop: LLM call failed: %s", exc)
            result.message = "אירעה שגיאה בעת חיפוש. נסה שוב."
            result.terminated_by = "error"
            break

        # Estimate the cost of this turn and update the running total.
        cost_usd_so_far += _estimate_call_cost(completion, messages)
        result.total_cost_usd = cost_usd_so_far
        if cost_usd_so_far > cost_budget_usd:
            logger.warning(
                "agent.loop: cost budget exceeded at iter=%d ($%.4f > $%.4f)",
                iteration + 1, cost_usd_so_far, cost_budget_usd,
            )
            if not result.message:
                result.message = "החיפוש דורש יותר עיבוד מהמתוכנן. נסה לנסח קצר יותר."
            result.terminated_by = "cost_budget"
            break

        # Guard: provider may return empty choices on safety filter blocks.
        if not getattr(completion, "choices", None):
            logger.warning("agent.loop: completion returned no choices (safety filter?)")
            result.message = "הבקשה נחסמה. נסה לנסח אחרת."
            result.terminated_by = "safety_blocked"
            break

        choice = completion.choices[0]
        assistant_msg = choice.message
        tool_calls = getattr(assistant_msg, "tool_calls", None) or []
        assistant_content = assistant_msg.content or ""

        # If no tool calls, the LLM produced final content — terminate.
        # Guard the dual-None case: if content is also empty, return a
        # graceful fallback instead of a silent blank reply.
        if not tool_calls:
            if not assistant_content.strip():
                logger.warning("agent.loop: empty content + empty tool_calls")
                result.message = "לא הצלחתי להבין את הבקשה. אפשר לנסח אחרת?"
                result.terminated_by = "empty_response"
            else:
                result.message = assistant_content
                result.terminated_by = "content"
            break

        # Capture any reasoning preamble the LLM emitted alongside tool_calls
        # (some models return both). Without this, the preamble is lost.
        if assistant_content.strip():
            result.intermediate_content.append(assistant_content)

        # Filter out malformed tool_calls (missing tc.function) BEFORE we
        # append the assistant message. Otherwise an orphan assistant.tool_calls
        # entry with no matching role=tool reply will poison the next turn.
        well_formed_tcs = [tc for tc in tool_calls if getattr(tc, "function", None) is not None]
        if len(well_formed_tcs) < len(tool_calls):
            logger.warning(
                "agent.loop: dropped %d malformed tool_call(s) (missing .function)",
                len(tool_calls) - len(well_formed_tcs),
            )

        if not well_formed_tcs:
            # All tool_calls were malformed — fall back to treating the
            # response as content (which we know is empty here).
            result.message = "התקבלה תגובה לא תקינה מהדגם. נסה שוב."
            result.terminated_by = "error"
            break

        # Append the assistant message (with tool_calls) FIRST so the LLM's
        # subsequent reply has the right conversation shape.
        messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in well_formed_tcs
                ],
            }
        )

        for tc in well_formed_tcs:
            tc_start = time.monotonic()
            tool_name = tc.function.name
            raw_args = tc.function.arguments
            error: Optional[str] = None
            tool_output: str = ""
            result_count: Optional[int] = None
            parsed_args: dict[str, Any] = {}

            try:
                # Parse args (LLM returns JSON string per OpenAI spec).
                # Preserve the raw payload in the trace if parse fails so
                # Hebrew tool-call drift can be debugged later.
                try:
                    parsed_args = json.loads(raw_args) if raw_args else {}
                except (json.JSONDecodeError, TypeError) as je:
                    parsed_args = {"_raw_args": raw_args or "", "_parse_error": str(je)}
                    raise ValueError(f"tool arguments are not valid JSON: {je}")

                if tool_name not in tool_registry:
                    raise ValueError(f"unknown tool: {tool_name}")

                params_cls, executor = tool_registry[tool_name]
                params = params_cls.model_validate(parsed_args)

                # Execute under a per-tool timeout — a hung _run_product_search
                # must not freeze the whole FastAPI worker.
                tool_result = await asyncio.wait_for(
                    executor(params, **tool_context),
                    timeout=tool_timeout_s,
                )

                # Executors return (items, summary). Items may be None on
                # legitimate empty results.
                if isinstance(tool_result, tuple) and len(tool_result) == 2:
                    items, summary = tool_result
                    items = items or []
                    result_count = len(items)
                    # Route accumulated results by tool name. Tools that don't
                    # return tray items (clarify, get_user_context, recall_history)
                    # have items=[] and contribute via their summary only.
                    if tool_name == "search_products":
                        _accumulate_results(result.product_results, items)
                    elif tool_name == "search_stores":
                        _accumulate_results(result.store_results, items)
                    # clarify / get_user_context / recall_history: no items
                    # accumulated — their payload reaches the LLM via summary.

                    # Send STRUCTURED data back to the LLM so it can compose a
                    # reply that references items by name, price, store. The
                    # summary alone is insufficient — the LLM was inventing
                    # numbers when only the summary was visible.
                    tool_output = _serialize_tool_result_for_llm(items, summary, result_count)
                else:
                    tool_output = json.dumps({"summary": str(tool_result)}, ensure_ascii=False)

            except ValidationError as ve:
                error = f"invalid arguments: {ve.errors()[:3]}"
                tool_output = json.dumps({"error": error}, ensure_ascii=False)
            except asyncio.TimeoutError:
                error = f"tool '{tool_name}' timed out after {tool_timeout_s}s"
                logger.warning("agent.loop: %s", error)
                tool_output = json.dumps({"error": "tool execution timed out"}, ensure_ascii=False)
            except Exception as exc:  # noqa: BLE001 — surface all errors to LLM
                logger.exception("agent.loop: tool %s failed", tool_name)
                error = f"{type(exc).__name__}: {exc}"
                tool_output = json.dumps({"error": "tool failed", "detail": str(exc)}, ensure_ascii=False)

            duration_ms = (time.monotonic() - tc_start) * 1000

            result.tool_calls.append(
                ToolCallTrace(
                    name=tool_name,
                    args=parsed_args,
                    duration_ms=duration_ms,
                    error=error,
                    result_count=result_count,
                )
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_output,
                }
            )

        # Continue the loop — LLM now sees tool results and decides next step
    else:
        # Loop fell through without breaking — hit max_iterations.
        # If we accumulated results along the way, the UX message should
        # acknowledge them rather than imply the search produced nothing.
        result.terminated_by = "max_iterations"
        if not result.message:
            n = len(result.product_results) + len(result.store_results)
            if n > 0:
                result.message = f"מצאתי {n} תוצאות אבל לא הספקתי לנסח סיכום. הנה מה שיש:"
            else:
                result.message = "החיפוש לא הסתיים בזמן. אפשר לנסח שוב?"

    result.total_latency_ms = (time.monotonic() - start) * 1000
    return result


def _accumulate_results(accum: list, new_items: list) -> None:
    """Append new items into the accumulator, deduping by id and capping
    the total at `_MAX_ACCUMULATED_RESULTS`. Mutates `accum`.

    Dedup key: `product_id` for ProductResult, `id` for StoreResult/anything
    else. Items with no usable id are skipped (defensive — shouldn't happen
    on real DB rows).
    """
    if not new_items:
        return
    def _key(it):
        return getattr(it, "product_id", None) or getattr(it, "id", None)
    seen = {_key(it) for it in accum}
    for item in new_items:
        k = _key(item)
        if k is None or k in seen:
            continue
        accum.append(item)
        seen.add(k)
        if len(accum) >= _MAX_ACCUMULATED_RESULTS:
            break


def _serialize_tool_result_for_llm(
    items: list[Any],
    summary: str,
    result_count: int,
    *,
    max_items_to_inline: int = 5,
) -> str:
    """Build the JSON content of the role=tool message the LLM sees.

    Inlines the top-N items (by similarity / order) with the fields the
    LLM needs to compose a useful reply: name, brand, price, store_name,
    availability, url. Truncates payload size.
    """
    inline = []
    for it in items[:max_items_to_inline]:
        try:
            inline.append(
                {
                    "name": getattr(it, "canonical_name", None),
                    "brand": getattr(it, "brand", None),
                    "price": getattr(it, "price", None),
                    "currency": getattr(it, "currency", "ILS"),
                    "availability": getattr(it, "availability", None),
                    "store_name": getattr(getattr(it, "store", None), "name_he", None),
                    "store_city": getattr(getattr(it, "store", None), "city", None),
                    "url": getattr(it, "product_url", None),
                }
            )
        except Exception:  # noqa: BLE001 — never let serialization kill the loop
            continue
    payload = {
        "summary": summary or f"{result_count} results",
        "total_results": result_count,
        "shown": len(inline),
        "items": inline,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
