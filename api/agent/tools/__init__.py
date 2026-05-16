"""api/agent/tools — Tools available to the agentic conversation loop.

Each tool exports:
- A Pydantic `Params` model describing its inputs
- A `SPEC` dict in OpenAI tool-calling format (consumed by the LLM)
- An async `execute(params, ...)` function that runs the tool

The agent loop dispatches by tool name from the `TOOLS` registry below.

W2 shipped: search_products
W3 adds: search_stores, get_user_context, recall_history, clarify
"""

from __future__ import annotations

from api.agent.tools.clarify import (
    CLARIFY_SPEC,
    ClarifyParams,
    execute_clarify,
)
from api.agent.tools.get_user_context import (
    GET_USER_CONTEXT_SPEC,
    GetUserContextParams,
    execute_get_user_context,
)
from api.agent.tools.recall_history import (
    RECALL_HISTORY_SPEC,
    RecallHistoryParams,
    execute_recall_history,
)
from api.agent.tools.search_products import (
    SEARCH_PRODUCTS_SPEC,
    SearchProductsParams,
    execute_search_products,
)
from api.agent.tools.search_stores import (
    SEARCH_STORES_SPEC,
    SearchStoresParams,
    execute_search_stores,
)

# Tool registry — name → (params model, executor)
# The agent loop uses this to dispatch tool calls.
TOOLS: dict[str, tuple[type, callable]] = {
    "search_products": (SearchProductsParams, execute_search_products),
    "search_stores": (SearchStoresParams, execute_search_stores),
    "get_user_context": (GetUserContextParams, execute_get_user_context),
    "recall_history": (RecallHistoryParams, execute_recall_history),
    "clarify": (ClarifyParams, execute_clarify),
}

# Tool specs — passed to the LLM as the `tools` parameter
TOOL_SPECS: list[dict] = [
    SEARCH_PRODUCTS_SPEC,
    SEARCH_STORES_SPEC,
    GET_USER_CONTEXT_SPEC,
    RECALL_HISTORY_SPEC,
    CLARIFY_SPEC,
]

__all__ = [
    "TOOLS",
    "TOOL_SPECS",
    # Re-exports for explicit imports
    "SearchProductsParams",
    "SearchStoresParams",
    "GetUserContextParams",
    "RecallHistoryParams",
    "ClarifyParams",
    "execute_search_products",
    "execute_search_stores",
    "execute_get_user_context",
    "execute_recall_history",
    "execute_clarify",
    "SEARCH_PRODUCTS_SPEC",
    "SEARCH_STORES_SPEC",
    "GET_USER_CONTEXT_SPEC",
    "RECALL_HISTORY_SPEC",
    "CLARIFY_SPEC",
]
