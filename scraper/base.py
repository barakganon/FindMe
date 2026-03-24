"""
scraper/base.py — Abstract base class for all FindMe scrapers.

All concrete scrapers must inherit from BaseScraper and implement:
    - scrape()         — return a list of raw product dicts
    - detect_shopify() — return True if the store runs on Shopify

Shared helpers (available to all subclasses):
    - get_raw_html()    — fetch a URL using Playwright (for JS-heavy pages)
    - get_static_html() — fetch a URL using httpx (for static pages)

Pydantic models exported from this module:
    - ProductItem    — a single scraped product
    - ScraperResult  — the envelope returned after a full scrape run
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import httpx
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
    TimeoutError as PlaywrightTimeout,
)
from pydantic import BaseModel, Field, HttpUrl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProductItem(BaseModel):
    """
    A single product scraped from a store catalog.

    All monetary values are in the currency specified by the ``currency`` field.
    Fields that are not available on a given store page default to None.
    """

    name: str = Field(..., description="Product display name as shown on the store page.")
    price: Optional[float] = Field(
        default=None,
        description="Numeric sale price. None if not parseable.",
    )
    currency: Optional[str] = Field(
        default="ILS",
        description="ISO-4217 currency code, e.g. 'ILS', 'USD'.",
    )
    availability: Optional[bool] = Field(
        default=None,
        description="True if the product is currently in stock / available.",
    )
    product_url: Optional[str] = Field(
        default=None,
        description="Canonical URL of the product page on the store's website.",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="URL of the primary product image.",
    )
    raw_description: Optional[str] = Field(
        default=None,
        description="Raw HTML or plain-text description as found on the page.",
    )
    category_hint: Optional[str] = Field(
        default=None,
        description="Category string taken directly from the store (not normalised).",
    )

    model_config = {"populate_by_name": True}


class ScraperResult(BaseModel):
    """
    Envelope that wraps the output of a single scraper run.

    ``items`` holds zero or more ProductItem dicts (after calling
    ``model_dump()`` on each ProductItem).  ``error`` is set to a
    human-readable message when the run failed, and None on success.
    """

    store_url: str = Field(..., description="The store URL that was scraped.")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when the scrape completed.",
    )
    items: list[dict] = Field(
        default_factory=list,
        description="List of ProductItem.model_dump() dicts.",
    )
    raw_snapshot_path: Optional[str] = Field(
        default=None,
        description="Filesystem path to the raw HTML / JSON snapshot saved during this run.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if the scrape failed; None on success.",
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BaseScraper(ABC):
    """
    Abstract base class for all FindMe product scrapers.

    Subclasses must implement :meth:`scrape` and :meth:`detect_shopify`.
    The shared helpers :meth:`get_raw_html` and :meth:`get_static_html`
    are available to all subclasses without any extra setup.

    Playwright resources are lazily created on the first call to
    :meth:`get_raw_html` and cleaned up when the context manager exits.

    Usage::

        async with MyConcreteScaper("https://example.com") as scraper:
            items = await scraper.scrape()

    Args:
        store_url: Root URL of the store being scraped (no trailing slash).
        headless:  Run Playwright in headless mode (default True).
    """

    def __init__(self, store_url: str, headless: bool = True) -> None:
        self.store_url: str = store_url.rstrip("/")
        self.headless: bool = headless

        # Playwright internals — lazily initialised
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseScraper":
        """Start Playwright and return self."""
        await self._start_playwright()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Shut down the Playwright browser cleanly."""
        await self._stop_playwright()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape(self) -> list[dict]:
        """
        Scrape the store catalog and return all products.

        Returns:
            A list of ``ProductItem.model_dump()`` dicts, one per product.
        """
        ...

    @abstractmethod
    async def detect_shopify(self) -> bool:
        """
        Determine whether the store runs on Shopify.

        Returns:
            True if the store exposes a valid ``/products.json`` endpoint.
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def get_raw_html(self, url: str) -> str:
        """
        Fetch ``url`` with a full Playwright browser and return the
        rendered HTML (after JavaScript has executed).

        Playwright is started lazily on the first call if the instance
        was not used as a context manager.

        Args:
            url: The page URL to load.

        Returns:
            The full rendered HTML string.

        Raises:
            PlaywrightTimeout: If the page does not load within 30 seconds.
        """
        if self._context is None:
            await self._start_playwright()

        page = await self._context.new_page()  # type: ignore[union-attr]
        try:
            logger.debug("get_raw_html → %s", url)
            await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            html: str = await page.content()
            return html
        except PlaywrightTimeout:
            logger.warning("Playwright timeout loading %s", url)
            raise
        finally:
            await page.close()

    async def get_static_html(self, url: str) -> str:
        """
        Fetch ``url`` using :mod:`httpx` (no JavaScript execution).

        Suitable for static pages such as ``/products.json`` or sitemap XML.

        Args:
            url: The URL to GET.

        Returns:
            The raw response body as a string.

        Raises:
            httpx.HTTPStatusError: On 4xx / 5xx responses.
            httpx.RequestError:    On network / DNS errors.
        """
        logger.debug("get_static_html → %s", url)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    # ------------------------------------------------------------------
    # Internal Playwright lifecycle helpers
    # ------------------------------------------------------------------

    async def _start_playwright(self) -> None:
        """Launch a Chromium browser and create a browser context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        logger.debug("Playwright started (headless=%s)", self.headless)

    async def _stop_playwright(self) -> None:
        """Cleanly close context, browser, and Playwright instance."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.debug("Playwright stopped")
