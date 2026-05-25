"""tests/api/test_city_synonyms.py — W4 city normalization unit tests."""

from __future__ import annotations

import pytest

from normalization.city_synonyms import expand_city, known_cities


# ---------------------------------------------------------------------------
# Pass-through cases
# ---------------------------------------------------------------------------


def test_empty_returns_empty():
    assert expand_city("") == []
    assert expand_city(None) == []
    assert expand_city("   ") == []


def test_unknown_city_passes_through():
    """An unrecognized city should return just the user's input — caller
    falls back to direct ILIKE, same as v1 behavior."""
    result = expand_city("Foobarville")
    assert result == ["Foobarville"]


# ---------------------------------------------------------------------------
# Tel Aviv (largest unlock)
# ---------------------------------------------------------------------------


def test_tel_aviv_hebrew_expands_to_buckets():
    """תל אביב must include both ת"א והסביבה (407 stores) AND תל אביב-יפו (1)."""
    result = expand_city("תל אביב")
    assert 'ת"א והסביבה' in result
    assert "תל אביב-יפו" in result
    # Original input is always first
    assert result[0] == "תל אביב"


def test_tel_aviv_abbreviated_ascii_quote():
    """ת"א with ASCII straight quote must match."""
    result = expand_city('ת"א')
    assert 'ת"א והסביבה' in result


def test_tel_aviv_abbreviated_hebrew_quote():
    """ת״א with Hebrew typographic quote must match (different unicode char)."""
    result = expand_city("ת״א")
    assert 'ת"א והסביבה' in result


def test_tel_aviv_no_quote():
    """תא (no quote at all) must match."""
    result = expand_city("תא")
    assert 'ת"א והסביבה' in result


def test_tel_aviv_english_lowercase():
    """tel aviv must match (case-insensitive)."""
    result = expand_city("tel aviv")
    assert 'ת"א והסביבה' in result


def test_tel_aviv_english_titlecase():
    """Tel Aviv must match."""
    result = expand_city("Tel Aviv")
    assert 'ת"א והסביבה' in result


def test_tel_aviv_with_leading_bet_prefix():
    """בתל אביב (in Tel Aviv) — leading ב should be stripped to match."""
    result = expand_city("בתל אביב")
    assert 'ת"א והסביבה' in result


# ---------------------------------------------------------------------------
# Other named cities
# ---------------------------------------------------------------------------


def test_jerusalem_hebrew_and_english():
    assert "ירושלים והסביבה" in expand_city("ירושלים")
    assert "ירושלים והסביבה" in expand_city("Jerusalem")
    assert "ירושלים והסביבה" in expand_city("jerusalem")


def test_haifa():
    assert "חיפה והסביבה" in expand_city("חיפה")
    assert "חיפה והסביבה" in expand_city("Haifa")


def test_eilat():
    assert "אילת והערבה" in expand_city("אילת")


def test_herzliya_maps_to_sharon():
    """Herzliya doesn't have its own bucket — should map to השרון והסביבה."""
    result = expand_city("הרצליה")
    assert "השרון והסביבה" in result


def test_ashkelon_and_ashdod_share_bucket():
    """Both map to the combined bucket."""
    assert "אשקלון, אשדוד והסביבה" in expand_city("אשקלון")
    assert "אשקלון, אשדוד והסביבה" in expand_city("אשדוד")


def test_petah_tikva():
    assert "פתח תקווה ובקעת אונו" in expand_city("פתח תקווה")


# ---------------------------------------------------------------------------
# Coverage diagnostic
# ---------------------------------------------------------------------------


def test_known_cities_includes_all_major():
    """Sanity check — the main cities must be in the synonym map."""
    known = set(known_cities())
    for required in [
        "תל אביב", "ירושלים", "חיפה", "אילת",
        "tel aviv", "jerusalem",
        "פתח תקווה", "אשקלון", "מודיעין",
    ]:
        assert required in known, f"Missing required synonym: {required!r}"
