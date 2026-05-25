"""api/agent/tools/search_products.py — Product search tool for the v2 agent.

Wraps the existing `_run_product_search` from `api/routes/chat.py` so the
agent can reuse the production search path (hybrid pgvector + ILIKE) without
duplicating logic.

Tool description is biased toward F-01 (brand filter) and F-09 (single-brand
queries) — the QA findings that single-shot intent parsing got wrong. Examples
in the description teach Gemini-2.5-flash to call this tool on brand-only
queries that v1 routed to clarify.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import LocationFilter, ParsedIntent, ProductResult


# ---------------------------------------------------------------------------
# Tool parameters
# ---------------------------------------------------------------------------


class SearchProductsParams(BaseModel):
    """Parameters the LLM passes when calling search_products."""

    query: Optional[str] = Field(
        None,
        description=(
            "Free-text product description in any language (Hebrew or English). "
            "Optional if brand is specified. Examples: 'headphones', 'אוזניות', 'gift for mom'."
        ),
    )
    brand: Optional[str] = Field(
        None,
        description=(
            "Brand name in either language (e.g. 'Sony', 'סוני', 'Apple', 'אפל', 'Samsung'). "
            "Case-insensitive substring match against the product brand field."
        ),
    )
    max_price: Optional[float] = Field(
        None,
        description="Maximum price in ILS (₪). Excludes products priced above this.",
        ge=0.0,
    )
    city: Optional[str] = Field(
        None,
        description=(
            "Israeli city name in Hebrew or English (e.g. 'תל אביב', 'Tel Aviv', "
            "'ירושלים', 'Jerusalem'). Filter to stores in or near this city."
        ),
    )
    online_only: bool = Field(
        False,
        description="If true, return only products from online stores (no physical location).",
    )
    limit: int = Field(
        10,
        description="Maximum number of results to return. Default 10.",
        ge=1,
        le=20,
    )


# ---------------------------------------------------------------------------
# OpenAI tool spec — consumed by the LLM
# ---------------------------------------------------------------------------

# Build JSON schema from the Pydantic model.
# We use mode='serialization' + by_alias=False so Gemini sees field names as defined.
_PARAMS_SCHEMA = SearchProductsParams.model_json_schema()

_TOOL_DESCRIPTION = (
    "Search the BuyMe gift-card catalog of ~135,000 products across 1,226 partner stores in Israel. "
    "Call this tool whenever the user describes a PRODUCT to buy, mentions a brand, or sets a price range. "
    "The user may write in Hebrew or English — pass brand and query values through as-is.\n\n"
    "## WHEN to call\n"
    "  - User: 'אוזניות סוני'                  → search_products(query='headphones', brand='Sony')\n"
    "  - User: 'סמסונג'                        → search_products(brand='Samsung')   [single brand is enough]\n"
    "  - User: 'Apple'                         → search_products(brand='Apple')     [English single brand]\n"
    "  - User: 'מתנה לאמא עד 300 שקל'        → search_products(query='gift for mom', max_price=300)\n"
    "  - User: 'Sony WH-1000XM5'              → search_products(query='WH-1000XM5', brand='Sony')\n"
    "  - User: 'שעון אפל'                     → search_products(query='watch', brand='Apple')\n"
    "  - User: 'אוזניות בלוטות גיימינג'      → search_products(query='wireless gaming headphones')\n"
    "  - User: 'צעצועים לילדים'                → search_products(query='kids toys')\n\n"
    "## When NOT to call (use a different tool or just respond)\n"
    "  - User asks about PLACES (restaurants, spas, retail stores, hotels) → use `search_stores` instead.\n"
    "  - User says 'near me' / 'לידי' / 'באזור שלי' without GPS → use `clarify` to ask for city.\n"
    "  - User asks 'how does this work' / 'מה זה' / 'איך זה עובד' / 'what is BuyMe' → DO NOT call any tool, "
    "respond directly with help text in Hebrew.\n"
    "  - User types only whitespace / emoji-only / SQL-injection-shaped strings → use `clarify`.\n"
    "  - User references previous turn ('הראשונה', 'תראה לי שוב', 'מה ההבדל') → call `recall_history` first, "
    "do not search again.\n\n"
    "## Brand handling (CRITICAL — F-01 fix)\n"
    "When the user mentions a brand, ALWAYS pass it via the `brand` parameter — never bury it inside `query`. "
    "The tool's post-search re-rank elevates brand-matching items, but only when `brand` is set explicitly.\n\n"
    "Returns: list of product results with name, brand, price (or null if unavailable), store info, "
    "and BuyMe purchase link. Sorts brand-matches first when `brand` is set, then in-stock before out-of-stock."
)


SEARCH_PRODUCTS_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "search_products",
        "description": _TOOL_DESCRIPTION,
        "parameters": _PARAMS_SCHEMA,
    },
}


def _rerank_by_brand(results: list[ProductResult], brand: str) -> list[ProductResult]:
    """Stable post-search sort that elevates products with matching brand.

    Three tiers (highest first):
      1. brand contains the requested brand (case-insensitive substring)
      2. brand is set but does NOT match
      3. brand is None / empty

    Within each tier, original order is preserved (Python's sort is stable).
    """
    if not brand or not results:
        return results
    needle = brand.strip().lower()
    if not needle:
        return results

    def _tier(item: ProductResult) -> int:
        b = (item.brand or "").lower()
        if not b:
            return 2  # last
        if needle in b:
            return 0  # first
        return 1  # middle

    # Use stable sort on tier only — preserves within-tier ordering.
    return sorted(results, key=_tier)


# ---------------------------------------------------------------------------
# Execution — wraps the production search path
# ---------------------------------------------------------------------------


async def execute_search_products(
    params: SearchProductsParams,
    *,
    db: AsyncSession,
    api_key: str,
    location: Optional[LocationFilter] = None,
    **_unused: object,  # forward-compat: tool_context may carry extra kwargs (e.g. current_user)
) -> tuple[list[ProductResult], str]:
    """
    Execute the search_products tool.

    Returns:
        (results, summary) — list of ProductResult + short Hebrew summary
        for the LLM to incorporate into its final reply.

    Implementation reuses `_run_product_search` from `api/routes/chat.py` so
    the hybrid pgvector + ILIKE search logic is not duplicated. Local import
    avoids a circular dependency at module import time.
    """
    from api.routes.chat import _run_product_search

    # Build the search text. F-01 fix: concatenate brand + query so the
    # embedding picks up brand semantics and ILIKE matches the brand token.
    parts = [p for p in (params.brand, params.query) if p]
    search_text = " ".join(parts) if parts else ""

    if not search_text:
        return [], "לא הועברו פרמטרי חיפוש."

    # ParsedIntent shim — _run_product_search only reads city, max_price.
    parsed = ParsedIntent(
        intent="product_search",
        product_query=params.query,
        brand=params.brand,
        max_price=params.max_price,
        city=params.city,
    )

    results = await _run_product_search(
        search_text=search_text,
        parsed=parsed,
        location=location,
        db=db,
        api_key=api_key,
    )

    # W6: brand re-rank — when the user asked for a specific brand, post-sort
    # the candidate list so brand-matching items rise to the top. This is a
    # SOFT filter: non-matching items are kept (in original order) AFTER the
    # matching ones, so the user still gets a useful set even when the brand
    # is rare or absent in the catalog.
    #
    # Why a soft filter and not a hard SQL clause: the SQL-layer brand filter
    # was explicitly disabled at chat.py:372 ("brand is already in search_text
    # for semantic matching") — proved wrong by F-01 QA but the SQL fix is
    # deferred. Soft re-rank gives most of the F-01/F-08 win without touching
    # the search SQL.
    if params.brand:
        results = _rerank_by_brand(results, params.brand)

    # Apply online_only BEFORE slicing to `limit`. Caveat: _run_product_search
    # already caps internally at _CHAT_PAGE_SIZE, so when online_only=True and
    # most of the top-N candidates are physical stores, this can return fewer
    # than `params.limit`. Structural fix (push online_only into the search SQL
    # so the cap applies post-filter) is part of the W4 audit refactor — see
    # deferred-work.md entry on _run_product_search circular dependency.
    if params.online_only:
        results = [r for r in results if r.store.is_online]
    results = results[: params.limit]

    if not results:
        summary = "לא נמצאו תוצאות מתאימות."
    else:
        top = results[0]
        brand_text = f" ({top.brand})" if top.brand else ""
        summary = f"נמצאו {len(results)} תוצאות. הראשונה: {top.canonical_name}{brand_text}."

    return results, summary
