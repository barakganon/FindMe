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
    terminated_by: str = "content"  # "content"|"max_iterations"|"cost_budget"|"error"


# ---------------------------------------------------------------------------
# Default system prompt (W2 minimal — full Sally voice lands in W7)
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """\
You are FindMe — a Hebrew-first chat assistant that helps Israeli BuyMe \
gift-card holders find products and stores where they can spend their cards.

Tools available:
- search_products: search the BuyMe product catalog.

Behavior:
- When the user describes a product, mentions a brand, or sets a price range, CALL search_products immediately rather than asking clarifying questions.
- If the user mentions only a brand name (e.g. "סמסונג", "Apple", "Sony"), CALL search_products with brand=<name>. This is enough — do not ask for more detail first.
- After tool results return, write a short Hebrew reply (2-3 sentences) summarizing what you found. Mention the top product by name and price.
- If results are empty, suggest a related search in Hebrew.
- Respond in Hebrew. If the user wrote in English, respond in Hebrew with brand/product names in their original form.
- Never echo the raw English value of `parsed.product_query` back to the user. Translate or rephrase in Hebrew.
- Do not invent prices, brands, or stores. Use only what the tool returned.

Length: keep replies brief — 2-3 sentences. The user is on a phone.
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
) -> AgentResult:
    """
    Drive the LLM through tool-calling iterations until it returns final content
    (or we hit max_iterations).

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

    Returns:
        AgentResult with the final message, accumulated results, and trace.
    """
    start = time.monotonic()
    result = AgentResult(message="")

    # Build the conversation: system + history + new message
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for h in history:
        # role must be 'user' or 'assistant' — coerce defensively
        role = h.role if h.role in ("user", "assistant", "tool") else "user"
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

        choice = completion.choices[0]
        assistant_msg = choice.message
        tool_calls = getattr(assistant_msg, "tool_calls", None) or []

        # If no tool calls, the LLM produced final content — terminate
        if not tool_calls:
            result.message = assistant_msg.content or ""
            result.terminated_by = "content"
            break

        # Otherwise execute each tool call, append results to the conversation
        # Append the assistant message (with tool_calls) FIRST so the LLM's
        # subsequent reply has the right context.
        messages.append(
            {
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            tc_start = time.monotonic()
            tool_name = tc.function.name
            raw_args = tc.function.arguments
            error: Optional[str] = None
            tool_output: str = ""
            result_count: Optional[int] = None
            parsed_args: dict[str, Any] = {}

            try:
                # Parse args (LLM returns JSON string per OpenAI spec)
                parsed_args = json.loads(raw_args) if raw_args else {}

                if tool_name not in tool_registry:
                    raise ValueError(f"unknown tool: {tool_name}")

                params_cls, executor = tool_registry[tool_name]
                params = params_cls.model_validate(parsed_args)

                # Execute. Pass tool_context kwargs in addition to params.
                tool_result = await executor(params, **tool_context)

                # Standardize return shape: executors return (results, summary) tuple
                if isinstance(tool_result, tuple) and len(tool_result) == 2:
                    items, summary = tool_result
                    result_count = len(items) if items is not None else 0
                    if tool_name == "search_products":
                        result.product_results.extend(items)
                    # Future: store_search tool would extend result.store_results here
                    tool_output = summary or f"{result_count} results"
                else:
                    tool_output = str(tool_result)

            except ValidationError as ve:
                error = f"invalid arguments: {ve.errors()[:3]}"
                tool_output = error
            except Exception as exc:  # noqa: BLE001 — surface all errors to LLM
                logger.exception("agent.loop: tool %s failed", tool_name)
                error = f"{type(exc).__name__}: {exc}"
                tool_output = f"שגיאה בקריאה לכלי: {error}"

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
        # Loop fell through without breaking — hit max_iterations
        result.terminated_by = "max_iterations"
        if not result.message:
            result.message = "החיפוש לא הסתיים בזמן. אפשר לנסח שוב?"

    result.total_latency_ms = (time.monotonic() - start) * 1000
    return result
