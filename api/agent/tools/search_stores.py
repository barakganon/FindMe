"""api/agent/tools/search_stores.py — Store search tool for the v2 agent (W3).

Wraps the existing `_run_store_search` from `api/routes/chat.py` so the
agent can find BuyMe stores by city + type without duplicating the geo
query logic.

Tool description is biased toward F-11 (city normalization) — the QA finding
that "מסעדות בתל אביב" returned 1 store when the BuyMe `ת"א והסביבה` bucket
holds 407. The actual SQL-layer synonym fix is W4 audit work; this tool
documents the intent so the agent passes the user's city verbatim.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import LocationFilter, ParsedIntent, StoreResult


class SearchStoresParams(BaseModel):
    """Parameters the LLM passes when calling search_stores."""

    query: Optional[str] = Field(
        None,
        description=(
            "Free-text store name or keyword in Hebrew or English. "
            "Optional. Examples: 'גרג', 'cafe greg', 'sushi'."
        ),
    )
    city: Optional[str] = Field(
        None,
        description=(
            "Israeli city name in Hebrew or English (e.g. 'תל אביב', 'Tel Aviv', "
            "'ירושלים', 'חיפה', 'אילת'). The catalog stores cities as BuyMe "
            "regional buckets, so pass the user's city verbatim — the SQL layer "
            "will expand to the matching bucket."
        ),
    )
    store_type: Optional[str] = Field(
        None,
        description=(
            "One of: 'restaurant', 'retail', 'spa', 'hotel', 'leisure'. "
            "Filter to stores of this category. Omit for all categories."
        ),
    )
    online_only: bool = Field(
        False,
        description="If true, return only online stores (no physical location).",
    )
    limit: int = Field(
        10,
        description="Maximum number of store results to return. Default 10.",
        ge=1,
        le=20,
    )


_PARAMS_SCHEMA = SearchStoresParams.model_json_schema()


_TOOL_DESCRIPTION = (
    "Search BuyMe partner STORES (not products) by city, type, or name. "
    "Use this when the user asks about places to GO — restaurants, spas, "
    "hotels, retail chains — rather than items to BUY.\n\n"
    "Examples of correct usage:\n"
    "  - 'מסעדות בתל אביב'         → search_stores(city='תל אביב', store_type='restaurant')\n"
    "  - 'spa בירושלים'             → search_stores(city='ירושלים', store_type='spa')\n"
    "  - 'חנויות אופנה בתל אביב'   → search_stores(city='תל אביב', store_type='retail')\n"
    "  - 'מלון אילת'                → search_stores(city='אילת', store_type='hotel')\n"
    "  - 'restaurants in Tel Aviv'  → search_stores(city='Tel Aviv', store_type='restaurant')\n\n"
    "When the user says 'near me' / 'לידי' / 'באזור שלי' / 'קרוב אלי', do NOT call this "
    "tool — call `clarify` instead to ask the user for their city or GPS location.\n\n"
    "Returns a list of stores with name, city, address, BuyMe URL, distance (if "
    "GPS provided), and product count."
)


SEARCH_STORES_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "search_stores",
        "description": _TOOL_DESCRIPTION,
        "parameters": _PARAMS_SCHEMA,
    },
}


async def execute_search_stores(
    params: SearchStoresParams,
    *,
    db: AsyncSession,
    location: Optional[LocationFilter] = None,
    **_unused: object,
) -> tuple[list[StoreResult], str]:
    """
    Execute the search_stores tool. Wraps `_run_store_search` from chat.py.
    """
    from api.routes.chat import _run_store_search

    # ParsedIntent shim — _run_store_search reads city, store_type, online_only.
    parsed = ParsedIntent(
        intent="store_search",
        product_query=params.query,
        city=params.city,
        store_type=params.store_type,
    )

    results = await _run_store_search(
        parsed=parsed,
        location=location,
        db=db,
    )

    # Apply online_only + limit post-fetch (mirror search_products pattern).
    if params.online_only:
        results = [r for r in results if r.is_online]
    results = results[: params.limit]

    if not results:
        summary = "לא נמצאו חנויות מתאימות."
    else:
        top = results[0]
        loc_text = f" ב-{top.city}" if top.city else ""
        summary = f"נמצאו {len(results)} חנויות. הראשונה: {top.name_he}{loc_text}."

    return results, summary
