"""Tests for scraper price sanitization (data-audit-v1 durable fix)."""
from scraper.shopify_product_scraper import _parse_price


def test_valid_price():
    assert _parse_price("129.90") == 129.90
    assert _parse_price(49) == 49.0

def test_none_and_unparseable():
    assert _parse_price(None) is None
    assert _parse_price("abc") is None

def test_rejects_sentinel():
    assert _parse_price("999999") is None
    assert _parse_price(999999.0) is None
    assert _parse_price(1000000) is None

def test_rejects_nonpositive():
    assert _parse_price(0) is None
    assert _parse_price("-5") is None
