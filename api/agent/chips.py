"""api/agent/chips.py — Memory-chip strip builder for the v2 chat UI (W7).

Surfaces personalization signals into a list of MemoryChip objects so the
frontend can render them above the conversation:

    👦 ילד 3   💰 ₪300   📍 ת"א

For logged-in users the source of truth is the DB (UserPreference +
UserInferredAttribute). For anonymous users, chips come from the per-session
`derived_facts` dict populated by `session_memory.save_session_state` from
this turn's tool_call args.

Ordering (left → right in the strip):
    1. Explicit preferences (most stable — user set them consciously)
    2. Confirmed inferred attributes (is_confirmed=True)
    3. Unconfirmed inferred attributes (confidence desc)
    4. Anonymous session-derived facts (only when no logged-in user)

Capped at 6 chips. Anything beyond is dropped — the strip is glanceable,
not a full profile view.

`build_chips` MUST be called AFTER `save_session_state` so anonymous chips
reflect the just-completed turn rather than lagging by one.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.session_memory import SessionState
from api.schemas import MemoryChip

logger = logging.getLogger(__name__)

_MAX_CHIPS = 6
# Strict > 0.5: 0.5 is the schema default ("no real signal"), so a row at exactly
# 0.5 means inference hasn't actually committed. Chips are an always-visible
# personalization surface; transparency for low-confidence guesses belongs in the
# ProfileDrawer, not here.
_CONFIDENCE_THRESHOLD = 0.5


async def build_chips(
    current_user: Optional[Any],
    session_state: SessionState,
    db: AsyncSession,
) -> list[MemoryChip]:
    """
    Synthesize the active chip list for the response.

    Anonymous users get chips from `session_state.derived_facts` only.
    Logged-in users get preferences + inferred attributes (confidence ≥ 0.5).

    Never raises — DB errors degrade to "no chips" silently.
    """
    chips: list[MemoryChip] = []

    if current_user is not None and getattr(current_user, "id", None) is not None:
        try:
            chips.extend(await _logged_in_chips(current_user.id, db))
        except Exception as exc:  # noqa: BLE001 — chips must never break chat
            logger.warning("build_chips: logged-in path failed (%s) — degrading", exc)
    else:
        chips.extend(_anon_chips(session_state))

    return chips[:_MAX_CHIPS]


async def _logged_in_chips(user_id: Any, db: AsyncSession) -> list[MemoryChip]:
    """Preferences + inferred attrs in canonical order."""
    from db.models import UserInferredAttribute, UserPreference

    # 1. Preferences (most stable — first)
    pref_rows = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    pref_map: dict[str, str] = {p.key: p.value for p in pref_rows.scalars().all()}
    pref_chips = _preference_chips(pref_map)

    # 2 + 3. Inferred attributes: confirmed first, then unconfirmed by confidence desc.
    # DB ordering is by is_confirmed DESC, then confidence DESC.
    inferred_rows = await db.execute(
        select(UserInferredAttribute)
        .where(UserInferredAttribute.user_id == user_id)
        .where(UserInferredAttribute.confidence > _CONFIDENCE_THRESHOLD)
        .order_by(
            UserInferredAttribute.is_confirmed.desc(),
            UserInferredAttribute.confidence.desc(),
        )
    )
    attrs = list(inferred_rows.scalars().all())

    # Pre-pass: if both `has_children` and `child_age_range` exist, keep only
    # the child_age_range row — _inferred_to_chip maps it to the compound chip
    # (👦 ילד {age}) per AC-3. The generic has_children chip would otherwise
    # duplicate it (two 👦 chips side by side).
    has_age_range = any(a.attribute == "child_age_range" for a in attrs)
    if has_age_range:
        attrs = [a for a in attrs if a.attribute != "has_children"]

    inferred_chips: list[MemoryChip] = []
    for attr in attrs:
        chip = _inferred_to_chip(attr)
        if chip is not None:
            inferred_chips.append(chip)

    return pref_chips + inferred_chips


def _preference_chips(pref_map: dict[str, str]) -> list[MemoryChip]:
    """Map UserPreference rows to chips. Spec rows per Sally's screen anatomy."""
    out: list[MemoryChip] = []

    # 💰 ₪{N} — default_max_price (spec)
    max_price = pref_map.get("default_max_price")
    if max_price:
        out.append(
            MemoryChip(
                icon="💰",
                label=f"₪{_clean_int_str(max_price)}",
                kind="preference",
                source=f"default_max_price={max_price}",
            )
        )

    # 📍 {city} — preferred_cities first entry (spec)
    cities_raw = pref_map.get("preferred_cities")
    if cities_raw:
        cities = _safe_json_list(cities_raw)
        if cities:
            out.append(
                MemoryChip(
                    icon="📍",
                    label=cities[0],
                    kind="preference",
                    source=f"preferred_cities[0]={cities[0]}",
                )
            )

    return out


def _inferred_to_chip(attr: Any) -> Optional[MemoryChip]:
    """
    Map a UserInferredAttribute row to a chip.

    Returns None for attributes that have no display mapping (we want to
    surface those quietly via the inferred-data API instead of inventing
    representations).
    """
    name = attr.attribute
    value = attr.value
    confirmed = bool(attr.is_confirmed)
    source = (attr.source or "")[:200] if hasattr(attr, "source") else None

    # 👦 ילד {age} — has_children + child_age_range (spec)
    # Built lazily inside has_children handler so we don't depend on row order.
    if name == "has_children" and str(value).lower() in ("true", "yes"):
        # We don't have child_age_range here — the caller has the rest of the
        # rows but mapping is per-row. Defer to child_age_range row if present,
        # otherwise show a generic chip.
        return MemoryChip(
            icon="👦", label="ילדים",
            kind="inferred", confirmed=confirmed, source=source,
        )

    if name == "child_age_range":
        return MemoryChip(
            icon="👦", label=f"ילד {value}",
            kind="inferred", confirmed=confirmed, source=source,
        )

    # Extensions (per story: ship if trivial; these are one-line mappings).
    if name == "gender" and value == "female":
        return MemoryChip(
            icon="👗", label="קניות נשים",
            kind="inferred", confirmed=confirmed, source=source,
        )
    if name == "gender" and value == "male":
        return MemoryChip(
            icon="👔", label="קניות גברים",
            kind="inferred", confirmed=confirmed, source=source,
        )
    if name == "price_sensitivity":
        if value == "budget":
            return MemoryChip(
                icon="💰", label="חסכוני",
                kind="inferred", confirmed=confirmed, source=source,
            )
        if value == "premium":
            return MemoryChip(
                icon="💎", label="פרימיום",
                kind="inferred", confirmed=confirmed, source=source,
            )

    return None


def _anon_chips(session_state: SessionState) -> list[MemoryChip]:
    """Build chips from anonymous-session derived_facts."""
    facts = session_state.derived_facts or {}
    out: list[MemoryChip] = []

    # 📍 {city} — search_*.city (spec, anon variant)
    if facts.get("city"):
        out.append(
            MemoryChip(
                icon="📍", label=facts["city"],
                kind="session", source=f"derived_facts.city={facts['city']}",
            )
        )

    # 💰 ₪{N} — search_products.max_price (spec, anon variant)
    if facts.get("max_price"):
        out.append(
            MemoryChip(
                icon="💰", label=f"₪{_clean_int_str(facts['max_price'])}",
                kind="session", source=f"derived_facts.max_price={facts['max_price']}",
            )
        )

    return out


# --- helpers ----------------------------------------------------------------


def _safe_json_list(raw: str) -> list[str]:
    """Decode a JSON list-of-strings preference value. Returns [] on any failure."""
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, list):
            return [str(x) for x in decoded if x]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _clean_int_str(value: str) -> str:
    """Render '300' from '300.0' / 300 / '300' etc. Rounds (not truncates) so
    '300.7' shows as '301' — chip shouldn't understate the user's actual budget.
    Falls back to the original string on any parse failure."""
    try:
        return str(round(float(value)))
    except (ValueError, TypeError):
        return str(value)
