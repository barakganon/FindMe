"""
tests/normalization/test_name_normalizer.py — Unit tests for NormalizedName and NameNormalizer.

These tests exercise the Pydantic model directly, without making any real
Claude API calls.  Integration tests that call the live API should be placed
in a separate file guarded by a pytest mark (e.g. ``@pytest.mark.integration``).
"""

from __future__ import annotations

import pytest

from normalization.name_normalizer import NormalizedName


def test_normalize_returns_canonical_name() -> None:
    """NormalizedName can be instantiated directly with expected field values.

    Verifies that the Pydantic model accepts a typical normalization result
    (Hebrew brand with English model) and stores all fields correctly.
    """
    result = NormalizedName(
        canonical_name="Wireless Noise-Cancelling Headphones WH-1000XM5",
        brand="Sony",
        model="WH-1000XM5",
        language_detected="mixed",
        confidence=0.95,
    )

    assert result.canonical_name == "Wireless Noise-Cancelling Headphones WH-1000XM5"
    assert result.brand == "Sony"
    assert result.model == "WH-1000XM5"
    assert result.language_detected == "mixed"
    assert result.confidence == pytest.approx(0.95)
