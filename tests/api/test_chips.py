"""tests/api/test_chips.py — W7 memory-chip builder unit tests.

Validates `api/agent/chips.build_chips` across the five scenarios:
    1. Anonymous user, no derived facts → empty
    2. Anonymous user, with derived facts → session chips only
    3. Logged-in user with inferred attributes only
    4. Logged-in user with preferences only
    5. Logged-in user with BOTH — ordering (prefs → confirmed → unconfirmed by confidence)
       and the 6-chip cap.

The DB is fully mocked at the SQLAlchemy session.execute layer.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.agent.chips import build_chips
from api.agent.session_memory import SessionState
from api.schemas import MemoryChip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_returning(prefs: list, inferred: list) -> MagicMock:
    """Build a mocked AsyncSession whose `execute` returns prefs then inferred."""
    db = MagicMock()
    pref_result = MagicMock()
    pref_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=prefs)))
    inf_result = MagicMock()
    inf_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=inferred)))
    db.execute = AsyncMock(side_effect=[pref_result, inf_result])
    return db


def _pref(key: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value)


def _inf(attribute: str, value: str, confidence: float, is_confirmed: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        attribute=attribute,
        value=value,
        confidence=confidence,
        is_confirmed=is_confirmed,
        source="test source",
    )


# ---------------------------------------------------------------------------
# Case 1 — Anonymous, no derived facts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_anon_empty_returns_no_chips():
    chips = await build_chips(
        current_user=None,
        session_state=SessionState.empty(),
        db=MagicMock(),
    )
    assert chips == []


# ---------------------------------------------------------------------------
# Case 2 — Anonymous, with derived facts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_anon_with_derived_facts():
    state = SessionState(derived_facts={"city": "תל אביב", "max_price": "300"})
    chips = await build_chips(
        current_user=None,
        session_state=state,
        db=MagicMock(),
    )
    icons = [c.icon for c in chips]
    labels = [c.label for c in chips]
    assert "📍" in icons
    assert "תל אביב" in labels
    assert "💰" in icons
    assert "₪300" in labels
    # All session-kind for anon
    assert all(c.kind == "session" for c in chips)
    # None confirmed (no DB)
    assert all(not c.confirmed for c in chips)


@pytest.mark.anyio
async def test_anon_derived_facts_brand_alone_not_a_chip():
    """Brand is collected as a derived fact but the strip does not show a brand chip."""
    state = SessionState(derived_facts={"brand": "Sony"})
    chips = await build_chips(current_user=None, session_state=state, db=MagicMock())
    assert chips == []


# ---------------------------------------------------------------------------
# Case 3 — Logged-in user, inferred only
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logged_in_inferred_only():
    user = SimpleNamespace(id="user-abc")
    db = _mock_db_returning(
        prefs=[],
        inferred=[
            _inf("child_age_range", "3", confidence=0.85, is_confirmed=True),
            _inf("gender", "female", confidence=0.7, is_confirmed=False),
        ],
    )
    chips = await build_chips(current_user=user, session_state=SessionState.empty(), db=db)
    assert len(chips) == 2
    # Confirmed should come before unconfirmed
    assert chips[0].label == "ילד 3"
    assert chips[0].confirmed is True
    assert chips[1].label == "קניות נשים"
    assert chips[1].confirmed is False
    assert all(c.kind == "inferred" for c in chips)


# ---------------------------------------------------------------------------
# Case 4 — Logged-in user, preferences only
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logged_in_prefs_only():
    user = SimpleNamespace(id="user-abc")
    db = _mock_db_returning(
        prefs=[
            _pref("default_max_price", "500"),
            _pref("preferred_cities", json.dumps(["תל אביב", "רמת גן"], ensure_ascii=False)),
        ],
        inferred=[],
    )
    chips = await build_chips(current_user=user, session_state=SessionState.empty(), db=db)
    # Order: money chip then city chip (matches _preference_chips function order)
    assert [c.icon for c in chips] == ["💰", "📍"]
    assert chips[0].label == "₪500"
    assert chips[1].label == "תל אביב"
    assert all(c.kind == "preference" for c in chips)


@pytest.mark.anyio
async def test_logged_in_preferred_cities_invalid_json_is_skipped():
    user = SimpleNamespace(id="user-abc")
    db = _mock_db_returning(
        prefs=[_pref("preferred_cities", "not-a-json-list")],
        inferred=[],
    )
    chips = await build_chips(current_user=user, session_state=SessionState.empty(), db=db)
    assert chips == []


# ---------------------------------------------------------------------------
# Case 5 — Logged-in user, both. Ordering + 6-chip cap.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logged_in_both_ordering_and_cap():
    user = SimpleNamespace(id="user-abc")
    db = _mock_db_returning(
        prefs=[
            _pref("default_max_price", "300"),
            _pref("preferred_cities", json.dumps(["תל אביב"], ensure_ascii=False)),
        ],
        inferred=[
            # is_confirmed=True should sort to top (matches DB ordering)
            _inf("child_age_range", "3", confidence=0.85, is_confirmed=True),
            _inf("gender", "female", confidence=0.8, is_confirmed=False),
            _inf("price_sensitivity", "budget", confidence=0.7, is_confirmed=False),
            _inf("price_sensitivity", "premium", confidence=0.65, is_confirmed=False),
            # Beyond the 6-cap — should be dropped
            _inf("gender", "male", confidence=0.6, is_confirmed=False),
        ],
    )
    chips = await build_chips(current_user=user, session_state=SessionState.empty(), db=db)
    # 6-cap enforced
    assert len(chips) <= 6
    # Preferences must come first
    pref_chips = [c for c in chips if c.kind == "preference"]
    inf_chips = [c for c in chips if c.kind == "inferred"]
    assert chips[: len(pref_chips)] == pref_chips
    # Among inferred, confirmed must come before any unconfirmed
    confirmed_positions = [i for i, c in enumerate(inf_chips) if c.confirmed]
    unconfirmed_positions = [i for i, c in enumerate(inf_chips) if not c.confirmed]
    if confirmed_positions and unconfirmed_positions:
        assert max(confirmed_positions) < min(unconfirmed_positions)


# ---------------------------------------------------------------------------
# DB-error path: never raises, returns empty
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logged_in_db_error_degrades_silently():
    user = SimpleNamespace(id="user-abc")
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    chips = await build_chips(current_user=user, session_state=SessionState.empty(), db=db)
    assert chips == []


# ---------------------------------------------------------------------------
# Logged-in user falls through to anon path NOT
# (confirms: logged-in path skips session-derived facts even if present)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logged_in_ignores_session_derived_facts():
    user = SimpleNamespace(id="user-abc")
    db = _mock_db_returning(prefs=[], inferred=[])
    state = SessionState(derived_facts={"city": "אילת"})
    chips = await build_chips(current_user=user, session_state=state, db=db)
    # Logged-in path doesn't pull from derived_facts — DB is the source of truth
    assert chips == []
