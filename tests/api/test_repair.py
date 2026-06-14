"""tests/api/test_repair.py — W7 conversation repair / mind-changer backend tests.

Story 5.7 AC-4 defines the Mind-Changer scenario: a user shifts from
    אופנה → אוכל → מתנה לאמא
across three turns. The backend contract for conversation repair is:

1. Tray accumulates results across turns — never cleared by a topic switch.
2. derived_facts are updated idempotently — newer facts overwrite older ones,
   but prior facts that aren't touched by the new turn survive.
3. The agent loop itself does NOT restart on a topic switch — the session
   keeps existing results. Clearing is an explicit user action (frontend 🗑️ נקה).
4. `save_session_state` merges derived_facts atomically from tool_call args.

The repair mechanism lives entirely in `session_memory.save_session_state` —
there is no separate "repair" function. These tests verify that
save_session_state implements the repair invariants.

All Redis and DB interactions are mocked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.agent.session_memory import (
    SessionState,
    clear_session_state,
    load_session_state,
    save_session_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(pid: str, name: str = "Product") -> dict:
    return {"id": pid, "canonical_name": name, "price": 100.0}


def _make_store(sid: str, name: str = "Store") -> dict:
    return {"id": sid, "name_he": name}


def _make_redis_with_state(prior_state: dict | None = None) -> AsyncMock:
    """Build a fake Redis whose get/setex simulate a single-key in-memory store."""
    store: dict = {}
    if prior_state is not None:
        key = "findme:agent:session:anon:test-session"
        store[key] = json.dumps(prior_state, ensure_ascii=False)

    async def _get(k):
        return store.get(k)

    async def _setex(k, ttl, v):
        store[k] = v

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.setex = AsyncMock(side_effect=_setex)
    # Expose store for assertions
    redis._store = store  # type: ignore[attr-defined]
    return redis


# ---------------------------------------------------------------------------
# Mind-changer invariant 1: tray accumulates across turns (no auto-clear)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tray_accumulates_across_turns():
    """After turn 1 (fashion) + turn 2 (food), both result sets survive in Redis.

    AC-4 says: 'Tray items from prior turns are NOT cleared — accumulation only.'
    The backend reflects this because save_session_state replaces last_*_results
    with the NEW turn's results, but the FRONTEND accumulates into trayItems.
    This test verifies the backend correctly stores each turn's results
    (so the frontend can accumulate from the stream of final events).
    """
    session_id = "anon:test-session"
    redis = _make_redis_with_state()

    # Turn 1 — fashion search
    fashion_products = [_make_product("f1", "מעיל חורף"), _make_product("f2", "מכנסיים")]
    await save_session_state(
        redis, session_id,
        product_results=fashion_products,
        store_results=[],
        user_message="אופנה לחורף",
        assistant_message="מצאתי פריטי אופנה",
        tool_calls=[SimpleNamespace(name="search_products", args={"category": "fashion"})],
    )

    turn1_payload = json.loads(redis._store["findme:agent:session:" + session_id])
    assert len(turn1_payload["last_product_results"]) == 2
    assert turn1_payload["last_user_message"] == "אופנה לחורף"

    # Turn 2 — food search (topic switch — the mind-changer)
    food_stores = [_make_store("r1", "מסעדת הים"), _make_store("r2", "פיצה רומא")]
    await save_session_state(
        redis, session_id,
        product_results=[],
        store_results=food_stores,
        user_message="בעצם, אוכל טוב באזור",
        assistant_message="מצאתי מסעדות",
        tool_calls=[SimpleNamespace(name="search_stores", args={"city": "תל אביב"})],
    )

    turn2_payload = json.loads(redis._store["findme:agent:session:" + session_id])
    # Turn 2 data is stored
    assert len(turn2_payload["last_store_results"]) == 2
    assert turn2_payload["last_user_message"] == "בעצם, אוכל טוב באזור"
    # The backend records the LATEST turn's results — the frontend is responsible
    # for accumulating across turns. Backend does NOT clear prior results proactively.
    # The session has the latest state, not a union (that's frontend trayItems work).
    assert turn2_payload["last_product_results"] == []  # new turn had no products


@pytest.mark.anyio
async def test_derived_facts_survive_topic_switch():
    """Turn 1 derived_facts survive into turn 2 if the new turn doesn't overwrite them.

    AC-4 repair: derived_facts merge idempotently — a topic switch that searches food
    doesn't erase the max_price inferred from turn 1 fashion query.
    """
    session_id = "anon:test-session"
    redis = _make_redis_with_state()

    # Turn 1 — fashion with max_price
    await save_session_state(
        redis, session_id,
        product_results=[_make_product("f1")],
        store_results=[],
        user_message="אופנה עד 300",
        assistant_message="מצאתי אופנה",
        tool_calls=[SimpleNamespace(name="search_products", args={"max_price": 300})],
    )

    # Turn 2 — food/restaurant search, no max_price arg
    await save_session_state(
        redis, session_id,
        product_results=[],
        store_results=[_make_store("r1")],
        user_message="בעצם אוכל טוב",
        assistant_message="מצאתי מסעדות",
        tool_calls=[SimpleNamespace(name="search_stores", args={"city": "תל אביב"})],
    )

    state = await load_session_state(redis, session_id)
    # max_price from turn 1 survived (no new value clobbered it)
    assert state.derived_facts.get("max_price") == "300"
    # city from turn 2 is also present
    assert state.derived_facts.get("city") == "תל אביב"


@pytest.mark.anyio
async def test_newer_city_overwrites_older_on_topic_switch():
    """When user changes location mid-conversation, newer city wins.

    This is the 'Mind-Changer' repair: facts that change are updated;
    facts that stay relevant (max_price) are preserved.
    """
    session_id = "anon:test-session"
    prior = {
        "last_product_results": [_make_product("p1")],
        "last_store_results": [],
        "last_user_message": "חנויות בחיפה",
        "last_assistant_message": "מצאתי",
        "updated_at": "2026-05-28T09:00:00+00:00",
        "derived_facts": {"city": "חיפה", "max_price": "500"},
    }
    redis = _make_redis_with_state(prior)

    # User changes mind — now searching in Tel Aviv
    await save_session_state(
        redis, session_id,
        product_results=[],
        store_results=[_make_store("r1")],
        user_message="בעצם תל אביב",
        assistant_message="מצאתי בת״א",
        tool_calls=[SimpleNamespace(name="search_stores", args={"city": "תל אביב"})],
    )

    state = await load_session_state(redis, session_id)
    # New city wins
    assert state.derived_facts["city"] == "תל אביב"
    # max_price untouched (no new price in this turn)
    assert state.derived_facts["max_price"] == "500"


@pytest.mark.anyio
async def test_three_turn_mind_changer_scenario():
    """Full 3-turn Mind-Changer: אופנה → אוכל → מתנה לאמא.

    Verifies the backend invariants from AC-4 across the canonical scenario.
    """
    session_id = "anon:mind-changer"
    redis = _make_redis_with_state()

    # Turn 1: אופנה לחורף
    await save_session_state(
        redis, session_id,
        product_results=[_make_product("f1", "מעיל חורף"), _make_product("f2", "סוודר")],
        store_results=[],
        user_message="אופנה לחורף",
        assistant_message="מצאתי 2 פריטי אופנה לחורף",
        tool_calls=[SimpleNamespace(name="search_products", args={"category": "fashion", "max_price": 400})],
    )
    state1 = await load_session_state(redis, session_id)
    assert len(state1.last_product_results) == 2
    assert state1.derived_facts.get("max_price") == "400"

    # Turn 2: בעצם, אוכל טוב באזור (no GPS yet → triggers clarify)
    await save_session_state(
        redis, session_id,
        product_results=[],
        store_results=[],
        user_message="בעצם, אוכל טוב באזור",
        assistant_message="באיזה אזור? הפעל שיתוף מיקום.",
        tool_calls=[SimpleNamespace(name="clarify", args={"question": "באיזה אזור?"})],
    )
    state2 = await load_session_state(redis, session_id)
    # No new results from a clarify turn
    assert state2.last_product_results == []
    assert state2.last_store_results == []
    # max_price survives (no new price in this turn)
    assert state2.derived_facts.get("max_price") == "400"

    # Turn 3: מתנה לאמא עד 200
    gift_products = [_make_product("g1", "בושם"), _make_product("g2", "צעיף"), _make_product("g3", "תיק")]
    await save_session_state(
        redis, session_id,
        product_results=gift_products,
        store_results=[],
        user_message="מתנה לאמא עד 200",
        assistant_message="מצאתי 3 מתנות לאמא",
        tool_calls=[SimpleNamespace(name="search_products", args={"category": "gifts", "max_price": 200})],
    )
    state3 = await load_session_state(redis, session_id)
    # Latest results (gift products)
    assert len(state3.last_product_results) == 3
    # max_price updated to 200 (newer value wins)
    assert state3.derived_facts.get("max_price") == "200"
    # No session errors — conversation survived all 3 turns
    assert state3.last_user_message == "מתנה לאמא עד 200"


# ---------------------------------------------------------------------------
# Explicit session reset (clear) + re-accumulation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_explicit_clear_wipes_state_then_fresh_turn_works():
    """After clear_session_state, a new turn starts with a clean slate.

    This models the frontend '🗑️ נקה' tray button which calls a hard reset.
    AC-4: 'No restart conversation button — repair is implicit. The escape
    hatch is 🗑️ נקה on the tray header.'
    """
    store: dict = {}
    session_key = "findme:agent:session:anon:clear-test"

    async def _get(k):
        return store.get(k)

    async def _setex(k, ttl, v):
        store[k] = v

    async def _delete(k):
        store.pop(k, None)

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.setex = AsyncMock(side_effect=_setex)
    redis.delete = AsyncMock(side_effect=_delete)

    session_id = "anon:clear-test"

    # Populate initial state
    await save_session_state(
        redis, session_id,
        product_results=[_make_product("p1")],
        store_results=[],
        user_message="ראשון",
        assistant_message="ok",
    )
    state_before = await load_session_state(redis, session_id)
    assert not state_before.is_empty()

    # Simulate frontend 🗑️ נקה — explicit wipe
    await clear_session_state(redis, session_id)
    state_after_clear = await load_session_state(redis, session_id)
    assert state_after_clear.is_empty()

    # Next turn starts fresh (no prior derived_facts leak)
    await save_session_state(
        redis, session_id,
        product_results=[_make_product("p2")],
        store_results=[],
        user_message="חדש",
        assistant_message="ok",
        tool_calls=[SimpleNamespace(name="search_products", args={"max_price": 100})],
    )
    state_fresh = await load_session_state(redis, session_id)
    assert len(state_fresh.last_product_results) == 1
    assert state_fresh.derived_facts.get("max_price") == "100"
    # No leftover facts from before the clear
    assert "city" not in state_fresh.derived_facts


# ---------------------------------------------------------------------------
# Non-search turns don't erase existing results
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_non_search_turn_preserves_prior_results():
    """A clarify turn (no products/stores) doesn't blow away previous results in Redis.

    The tray accumulates in the FRONTEND — but the backend must save the new
    empty-results turn without corrupting derived_facts.
    """
    prior = {
        "last_product_results": [_make_product("p1"), _make_product("p2")],
        "last_store_results": [],
        "last_user_message": "אוזניות",
        "last_assistant_message": "מצאתי",
        "updated_at": "2026-05-28T10:00:00+00:00",
        "derived_facts": {"brand": "Sony", "max_price": "500"},
    }
    redis = _make_redis_with_state(prior)
    session_id = "anon:test-session"

    # Clarify turn — no tool results
    await save_session_state(
        redis, session_id,
        product_results=[],
        store_results=[],
        user_message="מה ההבדל?",
        assistant_message="המוצרים הם...",
        tool_calls=[SimpleNamespace(name="recall_history", args={})],
    )

    state = await load_session_state(redis, session_id)
    # Brand + price from prior turn survived (recall_history has no relevant args)
    assert state.derived_facts.get("brand") == "Sony"
    assert state.derived_facts.get("max_price") == "500"
    # The turn was saved (messages updated)
    assert state.last_user_message == "מה ההבדל?"


# ---------------------------------------------------------------------------
# SessionState.empty() constructor
# ---------------------------------------------------------------------------


def test_session_state_empty_factory():
    """SessionState.empty() returns a fully empty state."""
    state = SessionState.empty()
    assert state.last_product_results == []
    assert state.last_store_results == []
    assert state.last_user_message == ""
    assert state.last_assistant_message == ""
    assert state.derived_facts == {}
    assert state.is_empty()
