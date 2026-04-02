"""
api/chat_utils.py — User preference injection and intent enrichment.

Functions here are called from api/routes/chat.py for logged-in users only.
Anonymous users bypass all of this — the chat still works without it.
"""
from __future__ import annotations

import json

from api.schemas import ParsedIntent


def build_user_context_block(prefs: dict, implicit: list, history: list) -> str:
    """Build a Hebrew context block injected into the intent parser."""
    lines = ["--- הקשר אישי של המשתמש ---"]

    if prefs.get("default_max_price"):
        lines.append(f"תקציב רגיל: עד ₪{prefs['default_max_price']}")

    if prefs.get("preferred_cities"):
        try:
            cities = json.loads(prefs["preferred_cities"])
            lines.append(f"ערים מועדפות: {', '.join(cities)}")
        except Exception:
            pass

    if prefs.get("preferred_categories"):
        try:
            cats = json.loads(prefs["preferred_categories"])
            lines.append(f"קטגוריות מועדפות: {', '.join(cats)}")
        except Exception:
            pass

    # Top implicit signals (city searches)
    top_cities = [s for s in implicit if s.get("signal_type") == "city_search"][:3]
    if top_cities:
        lines.append(f"ערים שחיפש לאחרונה: {', '.join(s['signal_value'] for s in top_cities)}")

    # Recent search context (last 3)
    if history:
        lines.append("חיפושים אחרונים:")
        for h in history[:3]:
            searched_at = h.get("searched_at", "")[:10] if h.get("searched_at") else ""
            lines.append(f"  - {h.get('message', '')} ({searched_at})")

    lines.append("--- סוף הקשר ---")
    return "\n".join(lines)


def merge_preferences_into_search(
    parsed: ParsedIntent,
    prefs: dict,
    implicit: list,
) -> ParsedIntent:
    """
    Apply user preferences to parsed intent before running search.
    Never overrides explicit user choices — only fills in gaps.
    """
    # Budget: use parsed max_price if stated, otherwise fall back to preference
    if parsed.max_price is None and prefs.get("default_max_price"):
        try:
            parsed = parsed.model_copy(update={"max_price": float(prefs["default_max_price"])})
        except (ValueError, TypeError):
            pass

    # City: use parsed city if stated, otherwise check preferred cities
    if parsed.city is None and not parsed.needs_user_location:
        try:
            preferred_cities = json.loads(prefs.get("preferred_cities", "[]"))
            if preferred_cities:
                parsed = parsed.model_copy(update={"city": preferred_cities[0]})
        except Exception:
            pass

    return parsed


def apply_inferred_attributes(
    parsed: ParsedIntent,
    inferred: list[dict],
) -> ParsedIntent:
    """
    Use inferred attributes to enrich search intent.
    NEVER filters results — only boosts relevance signals.
    Only applies attributes with confidence >= 0.5.
    Adds metadata hints without restricting or modifying the core query.
    """
    high_conf = {
        a["attribute"]: a["value"]
        for a in inferred
        if a.get("confidence", 0) >= 0.5
    }

    # Price sensitivity: we could in future pass this as a hint to the response composer.
    # For now this is a no-op enrichment — the hook is here for the response composer extension.
    # No structural change to ParsedIntent to avoid breaking the Pydantic model.
    _ = high_conf.get("price_sensitivity")  # acknowledged, used in future

    return parsed
