"""normalization/city_synonyms.py — Map user-typed Israeli cities to BuyMe regional buckets.

The `stores.city` column does not contain canonical city names — it holds
BuyMe's own regional buckets (e.g. `ת"א והסביבה` = "Tel Aviv area"). A naive
ILIKE on the user's input misses 99% of stores: typing "תל אביב" returns 1
store (a single row with the canonicalized name) when the TLV bucket actually
contains 407.

This module exposes `expand_city(user_city)` which returns the list of city
strings the SQL layer should match against (the user's input + every relevant
bucket). The agent's `search_stores` tool calls this before invoking
`_run_store_search` so the OR-of-ILIKEs hits all relevant buckets.

Data: the synonym map below was hand-built from the local DB query:
    SELECT city, COUNT(*) FROM stores GROUP BY city ORDER BY count DESC

If new buckets appear in production, update `_BUCKETS_BY_CITY` here — no
schema migration needed.
"""

from __future__ import annotations

from typing import Iterable

# All known BuyMe regional bucket values observed in production (2026-05-16).
# Stored as the canonical Hebrew strings exactly as they appear in the DB.
_TLV_BUCKETS = ['ת"א והסביבה', 'תל אביב-יפו']
_JERUSALEM_BUCKETS = ['ירושלים והסביבה']
_HAIFA_BUCKETS = ['חיפה והסביבה']
_EILAT_BUCKETS = ['אילת והערבה']
_SHARON_BUCKETS = ['השרון והסביבה', 'רמת השרון']
_SOUTH_COAST_BUCKETS = ['אשקלון, אשדוד והסביבה']
_PETAH_TIKVA_BUCKETS = ['פתח תקווה ובקעת אונו']
_MODIIN_BUCKETS = ['מודיעין, השפלה והסביבה']
_CENTER_BUCKETS = ['מרכז']
_NORTH_BUCKETS = ['צפון']
_SOUTH_BUCKETS = ['דרום']
_GALIL_BUCKETS = ['הגליל והגולן']
_NEGEV_BUCKETS = ['הנגב']
_NATIONWIDE_BUCKETS = ['סניפים בפריסה ארצית']

# Map of normalized user input → list of bucket strings to match.
# Keys are lowercased + stripped; matching is case-insensitive substring.
# Hebrew and English aliases live in the same list per canonical city.
_CITY_TO_BUCKETS: dict[str, list[str]] = {
    # Tel Aviv (largest unlock — 408 stores)
    'תל אביב': _TLV_BUCKETS,
    'תל-אביב': _TLV_BUCKETS,
    'ת"א': _TLV_BUCKETS,
    'ת״א': _TLV_BUCKETS,  # Hebrew typographic quote
    'תא': _TLV_BUCKETS,
    'יפו': _TLV_BUCKETS,
    'tel aviv': _TLV_BUCKETS,
    'telaviv': _TLV_BUCKETS,
    'tlv': _TLV_BUCKETS,

    # Jerusalem
    'ירושלים': _JERUSALEM_BUCKETS,
    'ירושלים והסביבה': _JERUSALEM_BUCKETS,
    'י-ם': _JERUSALEM_BUCKETS,
    'ים': _JERUSALEM_BUCKETS,
    'jerusalem': _JERUSALEM_BUCKETS,

    # Haifa
    'חיפה': _HAIFA_BUCKETS,
    'haifa': _HAIFA_BUCKETS,

    # Eilat
    'אילת': _EILAT_BUCKETS,
    'eilat': _EILAT_BUCKETS,

    # Sharon (Herzliya, Ramat Hasharon, Kfar Saba, Ra'anana, etc.)
    'הרצליה': _SHARON_BUCKETS,
    'רעננה': _SHARON_BUCKETS,
    'כפר סבא': _SHARON_BUCKETS,
    'רמת השרון': _SHARON_BUCKETS,
    'הוד השרון': _SHARON_BUCKETS,
    'herzliya': _SHARON_BUCKETS,
    'raanana': _SHARON_BUCKETS,

    # Ashkelon/Ashdod
    'אשקלון': _SOUTH_COAST_BUCKETS,
    'אשדוד': _SOUTH_COAST_BUCKETS,
    'ashkelon': _SOUTH_COAST_BUCKETS,
    'ashdod': _SOUTH_COAST_BUCKETS,

    # Petah Tikva
    'פתח תקווה': _PETAH_TIKVA_BUCKETS,
    'פ"ת': _PETAH_TIKVA_BUCKETS,
    'אונו': _PETAH_TIKVA_BUCKETS,
    'קרית אונו': _PETAH_TIKVA_BUCKETS,
    'petah tikva': _PETAH_TIKVA_BUCKETS,

    # Modiin
    'מודיעין': _MODIIN_BUCKETS,
    'modiin': _MODIIN_BUCKETS,

    # Be'er Sheva / Negev
    'באר שבע': _NEGEV_BUCKETS,
    'beer sheva': _NEGEV_BUCKETS,
    'beersheva': _NEGEV_BUCKETS,

    # Galilee
    'נצרת': _GALIL_BUCKETS,
    'צפת': _GALIL_BUCKETS,
    'טבריה': _GALIL_BUCKETS,
}


def expand_city(user_city: str | None) -> list[str]:
    """Return the list of city/bucket strings to match against `stores.city`.

    The returned list always includes the user's original input (in case the
    DB has a direct match), followed by zero or more BuyMe regional buckets
    that contain stores from that city.

    Empty/None input → empty list (caller should skip the city filter entirely).
    Unknown city → just the user's input passed through (caller falls back to
    direct ILIKE, which will return whatever happens to match — same v1 behavior).

    Lookups are case-insensitive on the normalized key.
    """
    if not user_city:
        return []
    normalized = user_city.strip().lower()
    if not normalized:
        return []

    buckets = _CITY_TO_BUCKETS.get(normalized)
    if buckets is None:
        # Try removing common prefixes like "ב" (in) before the city name.
        # e.g. user types "בתל אביב" → strip "ב" → "תל אביב" → match.
        if normalized.startswith('ב'):
            without_b = normalized[1:].strip()
            buckets = _CITY_TO_BUCKETS.get(without_b)

    if buckets is None:
        # Unknown — pass through. The SQL layer's ILIKE will handle whatever
        # match it can find on the raw input.
        return [user_city]

    # Always include the user's original input first so a direct DB match
    # (e.g. the single 'תל אביב-יפו' row) is preserved.
    result: list[str] = [user_city]
    for b in buckets:
        if b not in result:
            result.append(b)
    return result


def known_cities() -> Iterable[str]:
    """Return the set of canonical user-input keys recognized by this module.

    Useful for diagnostics or for building a `did-you-mean` UX in the future.
    """
    return _CITY_TO_BUCKETS.keys()
