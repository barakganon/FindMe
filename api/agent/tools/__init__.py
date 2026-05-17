"""api/agent/tools — Tools available to the agentic conversation loop.

Each tool exports:
- A Pydantic `Params` model describing its inputs
- A `SPEC` dict in OpenAI tool-calling format (consumed by the LLM)
- An async `execute(params, ...)` function that runs the tool

The agent loop dispatches by tool name from the `TOOLS` registry below.
"""

from __future__ import annotations

from api.agent.tools.search_products import (
    SEARCH_PRODUCTS_SPEC,
    SearchProductsParams,
    execute_search_products,
)

# Tool registry — name → (params model, executor)
# The agent loop uses this to dispatch tool calls.
TOOLS: dict[str, tuple[type, callable]] = {
    "search_products": (SearchProductsParams, execute_search_products),
}

# Tool specs — passed to the LLM as the `tools` parameter
TOOL_SPECS: list[dict] = [SEARCH_PRODUCTS_SPEC]

__all__ = [
    "TOOLS",
    "TOOL_SPECS",
    "SearchProductsParams",
    "execute_search_products",
    "SEARCH_PRODUCTS_SPEC",
]
