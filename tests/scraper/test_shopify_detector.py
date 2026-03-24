"""
tests/scraper/test_shopify_detector.py — Unit tests for ShopifyDetector.

Tests that the Shopify fast-path detection behaves correctly when the
underlying HTTP layer raises errors or returns non-Shopify responses.
"""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from scraper.shopify_detector import ShopifyDetector


@pytest.mark.anyio
async def test_detect_shopify_returns_false_for_non_shopify_url() -> None:
    """ShopifyDetector.detect_shopify() returns False when the HTTP call raises.

    Patches BaseScraper.get_static_html to raise httpx.RequestError, simulating
    a URL that is not reachable or not a Shopify store.  The detector should
    swallow the exception and return False rather than propagating it.
    """
    with patch(
        "scraper.base.BaseScraper.get_static_html",
        new_callable=AsyncMock,
        side_effect=httpx.RequestError("connection refused"),
    ):
        detector = ShopifyDetector("https://example.com")
        result = await detector.detect_shopify()

    assert result is False
