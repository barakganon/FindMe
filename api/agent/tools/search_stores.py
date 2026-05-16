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
    Execute the search_stores tool. Wraps `_run_store_search` from chat.py
    and applies the city synonym expansion from `normalization.city_synonyms`
    to address F-11 (BuyMe regional buckets vs user-typed city names).

    Strategy: when the user supplies a city, expand it to a list of BuyMe
    bucket strings + the original input, run `_run_store_search` once per
    expansion, dedupe by store.id, and merge. Typically results in 1-2
    queries (most cities map to one bucket).
    """
    from api.routes.chat import _run_store_search
    from normalization.city_synonyms import expand_city

    # Expand the user's city to BuyMe regional buckets. Empty list = no city
    # filter at all (skip the city dimension). Single-element list = no
    # expansion (no match in synonym map, just pass through).
    cities_to_try = expand_city(params.city) if params.city else [None]

    # Run one search per city/bucket, dedupe by store id, cap at params.limit.
    seen_ids: set[str] = set()
    merged: list[StoreResult] = []
    for city in cities_to_try:
        parsed = ParsedIntent(
            intent="store_search",
            product_query=params.query,
            city=city,
            store_type=params.store_type,
        )
        try:
            batch = await _run_store_search(
                parsed=parsed,
                location=location,
                db=db,
            )
        except Exception:
            # One bucket failing shouldn't abort the whole tool call.
            continue
        for r in batch:
            rid = r.id
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            merged.append(r)
        if len(merged) >= params.limit * 3:
            # Plenty of candidates — stop early to avoid unnecessary queries.
            break

    if params.online_only:
        merged = [r for r in merged if r.is_online]
    results = merged[: params.limit]

    if not results:
        summary = "לא נמצאו חנויות מתאימות."
    else:
        top = results[0]
        loc_text = f" ב-{top.city}" if top.city else ""
        summary = f"נמצאו {len(results)} חנויות. הראשונה: {top.name_he}{loc_text}."

    return results, summary
