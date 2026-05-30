"""tests/api/test_tool_search_stores.py — Direct unit tests for the v2 agent's
search_stores tool (W8 / AC-2).

Strategy: mock `api.routes.chat._run_store_search` (lazy import source) and
exercise the city-synonym fan-out + dedupe/filter/slice/summary branches of
`execute_search_stores`. No DB calls. The `normalization.city_synonyms.expand_city`
function is exercised live — it's pure Python with no I/O.

Covered branches:
  - Single-city expansion (תל אביב → 3 buckets) → 3 fan-out calls
  - No-city branch (city=None → expand to [None], 1 call with parsed.city=None)
  - Dedupe by `id` (same id across buckets appears once, first-seen order)
  - online_only filter applied after merge
  - limit truncation
  - Early-stop heuristic (len(merged) ≥ limit * 3 → break before exhausting)
  - Per-bucket exception swallowed → loop continues with remaining buckets
  - Empty-result Hebrew summary
  - Non-empty Hebrew summary with city segment
  - Unknown city → expand returns [city], exactly 1 call
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from api.agent.tools.search_stores import (
    SearchStoresParams,
    execute_search_stores,
)
from api.schemas import LocationFilter, StoreResult


def _store(
    sid: str,
    *,
    name_he: str = "מסעדה",
    city: Optional[str] = "תל אביב",
    is_online: bool = False,
) -> StoreResult:
    return StoreResult(
        id=sid,
        name_he=name_he,
        name_en=None,
        buyme_url=None,
        buyme_category="restaurant",
        address=None,
        city=city,
        lat=None,
        lng=None,
        distance_km=None,
        is_online=is_online,
        product_count=10,
    )


@pytest.mark.anyio
async def test_tel_aviv_expands_to_three_buckets(tool_context):
    """`city='תל אביב'` → expand_city returns 3 entries (original + 2 buckets).
    Each call gets a ParsedIntent carrying the per-bucket city + the query/store_type.
    """
    captured_cities: list[Optional[str]] = []

    async def fake_run(*, parsed, location, db):
        captured_cities.append(parsed.city)
        return [_store(f"s-{parsed.city}")]

    with patch(
        "api.routes.chat._run_store_search",
        new=AsyncMock(side_effect=fake_run),
    ):
        items, _ = await execute_search_stores(
            SearchStoresParams(query="מסעדות", city="תל אביב", store_type="restaurant"),
            **tool_context,
        )

    assert len(captured_cities) == 3
    assert captured_cities[0] == "תל אביב"  # original first
    assert 'ת"א והסביבה' in captured_cities
    assert "תל אביב-יפו" in captured_cities
    assert len(items) == 3  # 3 distinct ids


@pytest.mark.anyio
async def test_no_city_single_call_with_none(tool_context):
    """`city=None` → expand_city returns []; the tool falls back to [None] so
    _run_store_search is called exactly once with parsed.city=None.
    """
    captured: dict = {}

    async def fake_run(*, parsed, **_):
        captured["count"] = captured.get("count", 0) + 1
        captured["last_city"] = parsed.city
        return [_store("s1")]

    with patch(
        "api.routes.chat._run_store_search",
        new=AsyncMock(side_effect=fake_run),
    ):
        items, _ = await execute_search_stores(
            SearchStoresParams(query="cafe"),
            **tool_context,
        )

    assert captured["count"] == 1
    assert captured["last_city"] is None
    assert [s.id for s in items] == ["s1"]


@pytest.mark.anyio
async def test_dedupe_preserves_first_seen_order(tool_context):
    """When two buckets return a store with the same id, the merged list
    contains it once with first-seen ordering preserved.
    """
    batches = iter([
        [_store("a"), _store("b")],
        [_store("b"), _store("c")],  # `b` is duplicate, skipped
        [_store("d")],
    ])

    async def fake_run(**_):
        return next(batches)

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        items, _ = await execute_search_stores(
            SearchStoresParams(query="x", city="תל אביב"),
            **tool_context,
        )

    assert [s.id for s in items] == ["a", "b", "c", "d"]


@pytest.mark.anyio
async def test_online_only_filters_after_merge(tool_context):
    """With online_only=True, physical-store results are dropped from the final list."""
    async def fake_run(**_):
        return [
            _store("on1", is_online=True),
            _store("off1", is_online=False),
            _store("on2", is_online=True),
        ]

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        items, _ = await execute_search_stores(
            SearchStoresParams(query="x", online_only=True),
            **tool_context,
        )

    assert all(s.is_online for s in items)
    assert {s.id for s in items} == {"on1", "on2"}


@pytest.mark.anyio
async def test_limit_truncation(tool_context):
    """When merged results exceed `params.limit`, the output is sliced."""
    async def fake_run(**_):
        return [_store(f"s{i}") for i in range(15)]

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        items, _ = await execute_search_stores(
            SearchStoresParams(query="x", limit=4),
            **tool_context,
        )

    assert len(items) == 4
    assert [s.id for s in items] == ["s0", "s1", "s2", "s3"]


@pytest.mark.anyio
async def test_early_stop_when_buffer_exceeds_three_times_limit(tool_context):
    """Once `len(merged) >= params.limit * 3`, the loop breaks before exhausting
    `cities_to_try`. With limit=2 and bucket 0 returning 6 distinct stores,
    the loop must stop after the first bucket.
    """
    call_count = {"n": 0}

    async def fake_run(**_):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_store(f"s{i}") for i in range(6)]  # 6 >= limit*3 (2*3)
        return [_store("unreachable")]

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        await execute_search_stores(
            SearchStoresParams(query="x", city="תל אביב", limit=2),
            **tool_context,
        )

    assert call_count["n"] == 1


@pytest.mark.anyio
async def test_per_bucket_exception_is_swallowed(tool_context):
    """If one bucket's _run_store_search raises, the loop continues and the
    surviving buckets' results are returned. No exception escapes.
    """
    call_count = {"n": 0}

    async def fake_run(**_):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated DB error on bucket 2")
        return [_store(f"bucket-{call_count['n']}")]

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        items, summary = await execute_search_stores(
            SearchStoresParams(query="x", city="תל אביב"),
            **tool_context,
        )

    assert call_count["n"] == 3  # all 3 buckets attempted
    assert {s.id for s in items} == {"bucket-1", "bucket-3"}
    assert "נמצאו" in summary


@pytest.mark.anyio
async def test_empty_result_summary(tool_context):
    """When no buckets yield any store, the summary is the Hebrew "not found" string."""
    with patch("api.routes.chat._run_store_search", new=AsyncMock(return_value=[])):
        items, summary = await execute_search_stores(
            SearchStoresParams(query="ggh", city="תל אביב"),
            **tool_context,
        )

    assert items == []
    assert summary == "לא נמצאו חנויות מתאימות."


@pytest.mark.anyio
async def test_non_empty_summary_with_city_segment(tool_context):
    """Non-empty results yield `f"נמצאו {N} חנויות. הראשונה: {name} ב-{city}."`
    The city segment is included when top.city is truthy.
    """
    async def fake_run(**_):
        return [_store("s1", name_he="גרג", city="תל אביב-יפו")]

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        items, summary = await execute_search_stores(
            SearchStoresParams(query="גרג", city="תל אביב"),
            **tool_context,
        )

    assert items
    assert "נמצאו 1 חנויות" in summary
    assert "גרג" in summary
    assert "ב-תל אביב-יפו" in summary


@pytest.mark.anyio
async def test_unknown_city_passes_through_once(tool_context):
    """`city='Nowheresville'` triggers exactly one _run_store_search call
    (expand_city returns the input as-is when no synonym matches).
    """
    captured: dict = {}

    async def fake_run(*, parsed, **_):
        captured["count"] = captured.get("count", 0) + 1
        captured["city"] = parsed.city
        return []

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        await execute_search_stores(
            SearchStoresParams(query="x", city="Nowheresville"),
            **tool_context,
        )

    assert captured["count"] == 1
    assert captured["city"] == "Nowheresville"


@pytest.mark.anyio
async def test_location_kwarg_forwarded_to_search(tool_context):
    """A LocationFilter passed via tool_context.location reaches
    `_run_store_search` as the `location` kwarg unchanged.
    """
    loc = LocationFilter(lat=32.08, lng=34.78, radius_km=3.0)
    tool_context["location"] = loc
    captured: dict = {}

    async def fake_run(*, parsed, location, db):
        captured["location"] = location
        return []

    with patch("api.routes.chat._run_store_search", new=AsyncMock(side_effect=fake_run)):
        await execute_search_stores(
            SearchStoresParams(query="cafe"),
            **tool_context,
        )

    assert captured["location"] is loc
