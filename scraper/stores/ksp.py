"""
scraper/stores/ksp.py — Product catalog scraper for KSP (ksp.co.il).

KSP is one of Israel's largest consumer-electronics and computer-hardware
retailers, with both physical stores and an online shop at ksp.co.il.

Strategy:
    1. Fetch ``/sitemap.xml`` using :meth:`~scraper.base.BaseScraper.get_static_html`
       (KSP is NOT Shopify, so we skip ``/products.json``).
    2. Parse ``<loc>`` URLs from the sitemap; filter for product pages.
    3. For each product URL (up to ``MAX_PRODUCTS``), load the page with
       :meth:`~scraper.base.BaseScraper.get_raw_html` (Playwright).
    4. Extract product data using BeautifulSoup, prioritising:
           a. Schema.org ``Product`` JSON-LD blocks.
           b. KSP-specific CSS selectors (``.product-title``, ``.price``,
              ``[data-price]``, page ``<h1>``).
    5. Return ``[item.model_dump() for item in items]``.

Concurrency:
    Up to 5 product pages are fetched in parallel via
    ``asyncio.Semaphore(5)`` to avoid hammering ksp.co.il.

Usage::

    async with KSPScraper() as scraper:
        products = await scraper.scrape()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scraper.base import BaseScraper, ProductItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Root URL of the KSP online store.
KSP_BASE_URL = "https://ksp.co.il"

#: Maximum number of product pages to scrape in a single run.
MAX_PRODUCTS = 500

#: Sitemap paths to probe, in order.
_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_products_1.xml",
    "/sitemap_products.xml",
]

#: Maximum concurrent Playwright page loads.
_FETCH_CONCURRENCY = 5

# CSS selectors likely to exist on KSP product pages.
# TODO: verify and update after inspecting live ksp.co.il markup.
_TITLE_SELECTORS = [
    ".product-title",
    ".product_title",
    "[class*='product-title']",
    "[class*='productTitle']",
    "h1.title",
    "h1",
]

_PRICE_SELECTORS = [
    "[data-price]",
    ".price",
    ".product-price",
    "[class*='price']",
    "[itemprop='price']",
]

_AVAILABILITY_SELECTORS = [
    "[itemprop='availability']",
    ".availability",
    "[class*='availability']",
    "[class*='stock']",
    ".in-stock",
    ".out-of-stock",
]

_IMAGE_SELECTORS = [
    ".product-image img",
    ".product_image img",
    "[class*='product-img'] img",
    "img.primary-image",
    "[itemprop='image']",
]


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class KSPScraper(BaseScraper):
    """
    Product catalog scraper for KSP (ksp.co.il).

    KSP is a large Israeli electronics retailer that does NOT use Shopify;
    therefore :meth:`detect_shopify` always returns ``False`` and the scraper
    falls back to sitemap discovery + Playwright page rendering.

    Args:
        headless: Run Playwright in headless mode (default ``True``).
        max_products: Override the default :data:`MAX_PRODUCTS` cap per run.
        save_raw: If ``True`` (default), raw HTML snapshots are saved to disk
                  by :class:`~scraper.base.BaseScraper` helpers.

    Example::

        async with KSPScraper() as scraper:
            products = await scraper.scrape()
    """

    def __init__(
        self,
        headless: bool = True,
        max_products: int = MAX_PRODUCTS,
    ) -> None:
        super().__init__(store_url=KSP_BASE_URL, headless=headless)
        self.max_products = max_products

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    async def detect_shopify(self) -> bool:
        """
        KSP does not run on Shopify.

        Always returns ``False`` so callers know to use the sitemap path.

        Returns:
            ``False``
        """
        return False

    async def scrape(self) -> list[dict]:
        """
        Scrape the KSP product catalog and return normalised product dicts.

        Flow:
            1. Discover product URLs from the KSP sitemap.
            2. Fetch and parse each product page (up to ``max_products``).

        Returns:
            A list of :class:`~scraper.base.ProductItem` dicts
            (``ProductItem.model_dump()``), one entry per product.
        """
        logger.info("KSPScraper.scrape() starting for %s", self.store_url)

        product_urls = await self._discover_product_urls()
        if not product_urls:
            logger.warning("No product URLs found for KSP — returning empty list")
            return []

        product_urls = product_urls[: self.max_products]
        logger.info("KSP: scraping %d product pages", len(product_urls))

        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def scrape_one(url: str) -> Optional[ProductItem]:
            """Fetch and parse a single product page, respecting the semaphore."""
            async with sem:
                return await self._scrape_product_page(url)

        results = await asyncio.gather(*[scrape_one(u) for u in product_urls])
        items = [r for r in results if r is not None]

        logger.info("KSPScraper finished: %d products scraped", len(items))
        return [item.model_dump() for item in items]

    # ------------------------------------------------------------------
    # Sitemap discovery
    # ------------------------------------------------------------------

    async def _discover_product_urls(self) -> list[str]:
        """
        Probe known KSP sitemap paths and return a deduplicated list of
        product page URLs.

        Tries each path in :data:`_SITEMAP_PATHS` in order.  Returns the
        URLs from the first sitemap that parses successfully.

        Returns:
            Deduplicated list of absolute product page URLs.
        """
        for path in _SITEMAP_PATHS:
            sitemap_url = urljoin(KSP_BASE_URL + "/", path.lstrip("/"))
            logger.debug("KSP: probing sitemap at %s", sitemap_url)
            try:
                xml = await self.get_static_html(sitemap_url)
                urls = self._parse_sitemap(xml)
                if urls:
                    logger.info(
                        "KSP: found %d product URLs in %s", len(urls), sitemap_url
                    )
                    return urls
            except Exception as exc:
                logger.debug("KSP sitemap probe failed for %s: %s", sitemap_url, exc)
                continue

        logger.warning("KSP: all sitemap probes failed — no product URLs found")
        return []

    def _parse_sitemap(self, xml: str) -> list[str]:
        """
        Parse a sitemap XML string and extract URLs that look like KSP
        product pages.

        KSP product URLs typically contain ``/product/`` or match patterns
        like ``/p/<slug>``.

        Args:
            xml: Raw sitemap XML text.

        Returns:
            Deduplicated list of product URLs.
        """
        soup = BeautifulSoup(xml, "xml")
        locs = soup.find_all("loc")
        urls: list[str] = []
        seen: set[str] = set()

        for loc in locs:
            href = loc.get_text(strip=True)
            if not href:
                continue
            if self._is_product_url(href) and href not in seen:
                seen.add(href)
                urls.append(href)

        return urls

    @staticmethod
    def _is_product_url(url: str) -> bool:
        """
        Heuristic: return ``True`` if the URL looks like a KSP product page.

        Matches paths that contain ``/product``, ``/item``, or a numeric
        slug pattern common on ksp.co.il.

        Args:
            url: Absolute URL string to test.

        Returns:
            ``True`` if the URL likely points to a product page.

        Note:
            TODO: Inspect live ksp.co.il sitemap to confirm URL patterns
            and refine this heuristic if needed.
        """
        # TODO: verify against live ksp.co.il sitemap structure
        patterns = [
            r"/product",
            r"/item",
            r"/p/",
            r"/[a-z0-9\-]+-p-?\d+",  # slug-p-12345 pattern
        ]
        path = urlparse(url).path.lower()
        return any(re.search(p, path) for p in patterns)

    # ------------------------------------------------------------------
    # Product page extraction
    # ------------------------------------------------------------------

    async def _scrape_product_page(self, url: str) -> Optional[ProductItem]:
        """
        Load a KSP product page with Playwright and extract product data.

        Extraction priority:
            1. Schema.org ``Product`` JSON-LD (most reliable).
            2. KSP-specific CSS selectors.

        Args:
            url: Absolute URL of the product page.

        Returns:
            A :class:`~scraper.base.ProductItem` or ``None`` on failure.
        """
        try:
            html = await self.get_raw_html(url)
        except Exception as exc:
            logger.debug("KSP: failed to fetch %s: %s", url, exc)
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: JSON-LD
        item = self._extract_jsonld(soup, url)
        if item:
            return item

        # Strategy 2: KSP CSS selectors
        item = self._extract_css(soup, url)
        return item  # may be None

    def _extract_jsonld(
        self, soup: BeautifulSoup, page_url: str
    ) -> Optional[ProductItem]:
        """
        Extract product data from schema.org ``Product`` JSON-LD blocks.

        Args:
            soup:     Parsed BeautifulSoup tree.
            page_url: URL of the page (used to populate ``product_url``).

        Returns:
            :class:`~scraper.base.ProductItem` or ``None``.
        """
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            # Normalise: data can be a dict, a list, or contain @graph
            nodes: list[dict] = []
            if isinstance(data, list):
                nodes = data
            elif isinstance(data, dict):
                nodes = data.get("@graph", [data])

            for node in nodes:
                if not isinstance(node, dict):
                    continue
                schema_type = node.get("@type", "")
                is_product = (
                    schema_type == "Product"
                    if isinstance(schema_type, str)
                    else "Product" in schema_type
                )
                if not is_product:
                    continue

                name: str = node.get("name", "").strip()
                if not name:
                    continue

                price: Optional[float] = None
                currency: str = "ILS"
                availability: Optional[bool] = None
                image_url: Optional[str] = None
                raw_description: Optional[str] = node.get("description")
                category_hint: Optional[str] = (
                    node.get("category") or node.get("productType") or None
                )

                offers = node.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    price_str = offers.get("price") or offers.get("lowPrice")
                    if price_str is not None:
                        try:
                            price = float(str(price_str).replace(",", ""))
                        except (ValueError, TypeError):
                            pass
                    currency = offers.get("priceCurrency", "ILS") or "ILS"
                    avail_str = offers.get("availability", "")
                    if isinstance(avail_str, str):
                        availability = (
                            "InStock" in avail_str
                            or "instock" in avail_str.lower()
                        )

                img = node.get("image")
                if isinstance(img, str):
                    image_url = img
                elif isinstance(img, list) and img:
                    image_url = img[0] if isinstance(img[0], str) else None
                elif isinstance(img, dict):
                    image_url = img.get("url")

                return ProductItem(
                    name=name,
                    price=price,
                    currency=currency,
                    availability=availability,
                    product_url=page_url,
                    image_url=image_url,
                    raw_description=raw_description,
                    category_hint=category_hint,
                )

        return None

    def _extract_css(
        self, soup: BeautifulSoup, page_url: str
    ) -> Optional[ProductItem]:
        """
        Extract product data using KSP-specific CSS selectors as a fallback.

        Tries each selector in the known-KSP selector lists and returns the
        first matching value for name, price, and availability.

        Args:
            soup:     Parsed BeautifulSoup tree.
            page_url: URL of the page.

        Returns:
            :class:`~scraper.base.ProductItem` or ``None`` if no name found.

        Note:
            TODO: Validate selectors against live ksp.co.il pages and refine
            as needed — CSS classes may change with site redesigns.
        """
        # --- Name ---
        name: str = ""
        for selector in _TITLE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                name = el.get_text(separator=" ", strip=True)
                if name:
                    break
        if not name:
            logger.debug("KSP CSS: no name found on %s", page_url)
            return None

        # --- Price ---
        price: Optional[float] = None
        for selector in _PRICE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                # [data-price] attribute takes precedence
                raw = el.get("data-price") or el.get("content") or el.get_text(strip=True)
                if raw:
                    cleaned = re.sub(r"[^\d.,]", "", str(raw)).replace(",", "")
                    try:
                        price = float(cleaned)
                        break
                    except ValueError:
                        pass

        # --- Availability ---
        availability: Optional[bool] = None
        for selector in _AVAILABILITY_SELECTORS:
            el = soup.select_one(selector)
            if el:
                text = (
                    el.get("content", "")
                    or el.get("href", "")
                    or el.get_text(strip=True)
                )
                text_lower = text.lower()
                if "instock" in text_lower or "במלאי" in text_lower or "in stock" in text_lower:
                    availability = True
                    break
                if "outofstock" in text_lower or "אזל" in text_lower or "out of stock" in text_lower:
                    availability = False
                    break

        # --- Image ---
        image_url: Optional[str] = None
        for selector in _IMAGE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                image_url = (
                    el.get("src")
                    or el.get("data-src")
                    or el.get("content")
                )
                if image_url:
                    break

        # --- Category hint from breadcrumb ---
        # TODO: KSP uses a specific breadcrumb structure — refine selector
        category_hint: Optional[str] = None
        breadcrumb = soup.select_one(
            "[class*='breadcrumb'] span:last-child, nav[aria-label*='breadcrumb'] span:last-child"
        )
        if breadcrumb:
            category_hint = breadcrumb.get_text(strip=True) or None

        return ProductItem(
            name=name,
            price=price,
            currency="ILS",
            availability=availability,
            product_url=page_url,
            image_url=image_url,
            raw_description=None,
            category_hint=category_hint,
        )
