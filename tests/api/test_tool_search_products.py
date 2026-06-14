"""tests/api/test_tool_search_products.py — Direct unit tests for the v2 agent's
search_products tool (W8 / AC-1).

Strategy: mock `api.routes.chat._run_product_search` (the source of the lazy import
inside the tool) so no DB, embedding, or Gemini call is made. Each test exercises
one well-defined branch of `execute_search_products`:

  - Hebrew brand+query happy path → search_text is "brand query" prefixed
  - English happy path with max_price + city → fields propagate
  - No params → short-circuits before _run_product_search
  - Brand re-rank — three tiers, stable
  - Brand re-rank skipped when brand=None
  - online_only filters BEFORE limit slice
  - online_only=False preserves physical stores
  - limit slicing (post-rerank)
  - Internal cap caveat (online_only with fewer-than-limit survivors)
  - location kwarg propagation

Fixtures: `tool_context` from tests/api/conftest.py supplies the kwargs dict.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from api.agent.tools.search_products import (
    SearchProductsParams,
    execute_search_products,
)
from api.schemas import LocationFilter, ProductResult, StoreInfo


def _store(store_id: str = "s1", is_online: bool = True, city: str = "Tel Aviv") -> StoreInfo:
    return StoreInfo(
        id=store_id,
        name_he="חנות לדוגמה",
        name_en="Sample Store",
        buyme_url="https://buyme.co.il/s",
        is_online=is_online,
        city=city,
        lat=None,
        lng=None,
        distance_km=None,
    )


def _product(
    name: str,
    brand: Optional[str] = None,
    *,
    online: bool = True,
    pid: Optional[str] = None,
) -> ProductResult:
    return ProductResult(
        product_id=pid or f"p-{name}",
        canonical_name=name,
        brand=brand,
        category_path=None,
        store=_store(is_online=online),
        price=99.0,
        currency="ILS",
        availability=True,
        product_url=None,
        match_score=0.7,
    )


@pytest.mark.anyio
async def test_hebrew_brand_and_query_propagate_to_search(tool_context):
    """`query='אוזניות', brand='סוני'` → search_text='סוני אוזניות' and parsed
    fields forwarded; non-empty results yield the count-and-first-result summary.
    """
    fake_result = [_product("אוזניות סוני WH-1000", brand="סוני")]
    captured: dict = {}

    async def fake_run(*, search_text, parsed, location, db, api_key):
        captured["search_text"] = search_text
        captured["parsed"] = parsed
        captured["location"] = location
        return fake_result

    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(side_effect=fake_run),
    ):
        items, summary = await execute_search_products(
            SearchProductsParams(query="אוזניות", brand="סוני"),
            **tool_context,
        )

    assert captured["search_text"] == "סוני אוזניות"
    assert captured["parsed"].brand == "סוני"
    assert captured["parsed"].product_query == "אוזניות"
    assert captured["parsed"].max_price is None
    assert captured["parsed"].city is None
    assert items == fake_result
    assert summary.startswith("נמצאו 1 תוצאות")
    assert "אוזניות סוני WH-1000" in summary
    assert "(סוני)" in summary


@pytest.mark.anyio
async def test_english_query_with_max_price_and_city(tool_context):
    """English happy path. max_price + city propagate; brand is prefixed in search_text."""
    fake_result = [_product("Sony WH-1000XM5", brand="Sony")]
    captured: dict = {}

    async def fake_run(*, search_text, parsed, **_):
        captured["search_text"] = search_text
        captured["parsed"] = parsed
        return fake_result

    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(side_effect=fake_run),
    ):
        items, summary = await execute_search_products(
            SearchProductsParams(
                query="headphones",
                brand="Sony",
                max_price=500,
                city="Tel Aviv",
            ),
            **tool_context,
        )

    assert captured["search_text"] == "Sony headphones"
    assert captured["parsed"].max_price == 500.0
    assert captured["parsed"].city == "Tel Aviv"
    assert items == fake_result
    assert "Sony WH-1000XM5" in summary


@pytest.mark.anyio
async def test_no_params_short_circuits(tool_context):
    """When both query and brand are None, the tool returns the dedicated
    Hebrew "no params" message WITHOUT calling _run_product_search.
    """
    called = AsyncMock()
    with patch(
        "api.routes.chat._run_product_search",
        new=called,
    ):
        items, summary = await execute_search_products(
            SearchProductsParams(),
            **tool_context,
        )

    assert items == []
    assert summary == "לא הועברו פרמטרי חיפוש."
    called.assert_not_called()


@pytest.mark.anyio
async def test_brand_rerank_three_tiers_stable(tool_context):
    """Mock returns mixed brand fields; verify the three-tier stable sort.

    Input order:  Sony, Bose, None, "sony pro", ""
    Expected:     Sony, "sony pro", Bose, None, ""
                  (case-insensitive substring matches first; non-matching
                  truthy brands second; None/empty last; within-tier original.)
    """
    fake_result = [
        _product("a", brand="Sony", pid="a"),
        _product("b", brand="Bose", pid="b"),
        _product("c", brand=None, pid="c"),
        _product("d", brand="sony pro", pid="d"),
        _product("e", brand="", pid="e"),
    ]

    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(return_value=fake_result),
    ):
        items, _ = await execute_search_products(
            SearchProductsParams(brand="Sony"),
            **tool_context,
        )

    ordered_ids = [p.product_id for p in items]
    assert ordered_ids == ["a", "d", "b", "c", "e"]


@pytest.mark.anyio
async def test_brand_rerank_skipped_when_brand_is_none(tool_context):
    """When `brand` is None, the rerank step is a no-op and original order is preserved."""
    fake_result = [
        _product("a", brand="Sony", pid="a"),
        _product("b", brand="Bose", pid="b"),
        _product("c", brand=None, pid="c"),
    ]
    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(return_value=fake_result),
    ):
        items, _ = await execute_search_products(
            SearchProductsParams(query="headphones"),
            **tool_context,
        )

    assert [p.product_id for p in items] == ["a", "b", "c"]


@pytest.mark.anyio
async def test_online_only_filters_before_limit_slice(tool_context):
    """Mock returns 7 products (4 online, 3 offline); online_only=True with
    limit=3 → exactly 3 online results (not 3-of-7 then filtered to fewer).
    """
    fake_result = [
        _product("p0", pid="0", online=True),
        _product("p1", pid="1", online=False),
        _product("p2", pid="2", online=True),
        _product("p3", pid="3", online=False),
        _product("p4", pid="4", online=True),
        _product("p5", pid="5", online=False),
        _product("p6", pid="6", online=True),
    ]
    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(return_value=fake_result),
    ):
        items, _ = await execute_search_products(
            SearchProductsParams(query="x", online_only=True, limit=3),
            **tool_context,
        )

    assert len(items) == 3
    assert [p.product_id for p in items] == ["0", "2", "4"]
    assert all(p.store.is_online for p in items)


@pytest.mark.anyio
async def test_online_only_false_keeps_physical_stores(tool_context):
    """Default online_only=False — physical-store results stay in the output."""
    fake_result = [
        _product("p0", pid="0", online=False),
        _product("p1", pid="1", online=True),
    ]
    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(return_value=fake_result),
    ):
        items, _ = await execute_search_products(
            SearchProductsParams(query="x", limit=5),
            **tool_context,
        )

    assert len(items) == 2
    assert items[0].store.is_online is False


@pytest.mark.anyio
async def test_limit_slicing_post_rerank(tool_context):
    """Mock returns 8 results, limit=5 → 5 results returned in post-rerank order."""
    fake_result = [_product(f"p{i}", pid=str(i)) for i in range(8)]
    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(return_value=fake_result),
    ):
        items, _ = await execute_search_products(
            SearchProductsParams(query="x", limit=5),
            **tool_context,
        )

    assert len(items) == 5
    assert [p.product_id for p in items] == ["0", "1", "2", "3", "4"]


@pytest.mark.anyio
async def test_internal_cap_caveat_no_repaging(tool_context):
    """When `_run_product_search` returns at most _CHAT_PAGE_SIZE=10 and most
    are physical, the tool returns the surviving subset and does NOT attempt
    to re-page. Verify _run_product_search was called exactly once.
    """
    fake_result = [
        _product(f"p{i}", pid=str(i), online=(i < 2))  # 2 online, 8 offline
        for i in range(10)
    ]
    mock_search = AsyncMock(return_value=fake_result)
    with patch(
        "api.routes.chat._run_product_search",
        new=mock_search,
    ):
        items, summary = await execute_search_products(
            SearchProductsParams(query="x", online_only=True, limit=10),
            **tool_context,
        )

    assert len(items) == 2  # fewer than limit
    assert all(p.store.is_online for p in items)
    assert mock_search.call_count == 1


@pytest.mark.anyio
async def test_location_kwarg_propagated(tool_context):
    """A LocationFilter passed via tool_context.location reaches _run_product_search
    as the `location` kwarg unchanged.
    """
    loc = LocationFilter(lat=32.08, lng=34.78, radius_km=5.0)
    tool_context["location"] = loc
    captured: dict = {}

    async def fake_run(*, location, **_):
        captured["location"] = location
        return []

    with patch(
        "api.routes.chat._run_product_search",
        new=AsyncMock(side_effect=fake_run),
    ):
        items, summary = await execute_search_products(
            SearchProductsParams(query="cafe"),
            **tool_context,
        )

    assert captured["location"] is loc
    assert items == []
    assert summary == "לא נמצאו תוצאות מתאימות."
