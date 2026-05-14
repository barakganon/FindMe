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
    "Call this tool whenever the user describes a product, mentions a brand, or sets a price range. "
    "The user may write in Hebrew or English — pass values through as-is, the search is bilingual.\n\n"
    "Always prefer calling this tool over asking clarifying questions when the user has given any "
    "concrete signal (a brand, a category, a budget, a recipient, an occasion).\n\n"
    "Examples of correct usage:\n"
    "  - User: 'אוזניות סוני'                  → search_products(query='headphones', brand='Sony')\n"
    "  - User: 'סמסונג'                        → search_products(brand='Samsung')   [single brand is enough]\n"
    "  - User: 'Apple'                         → search_products(brand='Apple')     [single brand is enough]\n"
    "  - User: 'מתנה לאמא עד 300 שקל'        → search_products(query='gift for mom', max_price=300)\n"
    "  - User: 'Sony WH-1000XM5'              → search_products(query='WH-1000XM5', brand='Sony')\n"
    "  - User: 'שעון אפל'                     → search_products(query='watch', brand='Apple')\n"
    "  - User: 'אוזניות בלוטות גיימינג'      → search_products(query='wireless gaming headphones')\n"
    "  - User: 'spa בירושלים'                  → for *physical store* queries, do NOT call search_products; "
    "those are stores, not products. (Only call search_products for things you can buy and own.)\n\n"
    "Returns a list of product results with name, brand, price (or null if unavailable), store info, "
    "and a direct BuyMe purchase link. Sorts in-stock items before out-of-stock."
)


SEARCH_PRODUCTS_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "search_products",
        "description": _TOOL_DESCRIPTION,
        "parameters": _PARAMS_SCHEMA,
    },
}


# ---------------------------------------------------------------------------
# Execution — wraps the production search path
# ---------------------------------------------------------------------------


async def execute_search_products(
    params: SearchProductsParams,
    *,
    db: AsyncSession,
    api_key: str,
    location: Optional[LocationFilter] = None,
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

    # Apply limit + online_only filter (the production path doesn't honor either,
    # so we trim here).
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
