"""
scraper/per_store_scraper.py — Generic per-store product catalog scraper.

This is the fallback scraper used when a store does NOT run on Shopify.

Strategy:
    1. Call :meth:`detect_shopify`.  If True, delegate entirely to
       :class:`~scraper.shopify_detector.ShopifyDetector`.
    2. Otherwise, load the store's root page with Playwright and look for
       a sitemap (``/sitemap.xml`` or ``/sitemap_products_1.xml``).
    3. Parse the sitemap with BeautifulSoup4 to collect product page URLs.
    4. For each product URL (up to 500), fetch the HTML with Playwright and
       extract product data via:
           - Schema.org ``Product`` JSON-LD blocks.
           - ``[itemprop="name"]`` / ``[itemprop="price"]`` microdata.
           - ``[itemprop="availability"]`` microdata.
    5. Save per-product raw HTML snapshots to
       ``data/raw/{store_slug}/`` for reprocessing.
    6. Return ``[item.model_dump() for item in items]``.

Usage::

    async with PerStoreScraper("https://example.co.il") as scraper:
        products = await scraper.scrape()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseScraper, ProductItem
from scraper.shopify_detector import ShopifyDetector

logger = logging.getLogger(__name__)

# Maximum product pages scraped per store run (safety valve)
MAX_PRODUCTS = 500

# Concurrency limit for parallel product-page fetches
_FETCH_CONCURRENCY = 5

# Known sitemap paths to probe, in order
_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_products_1.xml",
    "/sitemap_products.xml",
]

# Raw HTML snapshot base directory
_RAW_DATA_DIR = Path("data/raw")


class PerStoreScraper(BaseScraper):
    """
    Generic per-store product catalog scraper.

    For Shopify stores: delegates to :class:`~scraper.shopify_detector.ShopifyDetector`.
    For non-Shopify stores: uses sitemap discovery + Playwright page rendering.

    Args:
        store_url: Root URL of the store (e.g. ``https://ksp.co.il``).
        headless:  Run Playwright in headless mode (default True).
        max_products: Override the default 500-product cap per run.
        save_raw:    If True (default), save raw HTML snapshots to disk.
    """

    def __init__(
        self,
        store_url: str,
        headless: bool = True,
        max_products: int = MAX_PRODUCTS,
        save_raw: bool = True,
    ) -> None:
        super().__init__(store_url=store_url, headless=headless)
        self.max_products = max_products
        self.save_raw = save_raw
        self._store_slug: str = self._slug_from_url(store_url)

    # ------------------------------------------------------------------
    # detect_shopify — delegate to ShopifyDetector
    # ------------------------------------------------------------------

    async def detect_shopify(self) -> bool:
        """
        Delegate Shopify detection to :class:`~scraper.shopify_detector.ShopifyDetector`.

        Returns:
            ``True`` if the store exposes a valid Shopify ``/products.json``.
        """
        detector = ShopifyDetector(store_url=self.store_url, headless=self.headless)
        return await detector.detect_shopify()

    # ------------------------------------------------------------------
    # scrape — main entry point
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Full product catalog scrape for a single store.

        Flow:
            1. Check for Shopify; if detected, use the fast-path.
            2. Otherwise, discover product URLs via sitemaps.
            3. Fetch + parse each product page (up to ``max_products``).

        Returns:
            A list of :class:`~scraper.base.ProductItem` dicts.
        """
        logger.info("PerStoreScraper.scrape() → %s", self.store_url)

        # Step 1 — Shopify fast-path
        if await self.detect_shopify():
            logger.info("Shopify detected — using ShopifyDetector for %s", self.store_url)
            async with ShopifyDetector(
                store_url=self.store_url, headless=self.headless
            ) as detector:
                return await detector.scrape()

        # Step 2 — sitemap discovery
        product_urls = await self._discover_product_urls()

        if not product_urls:
            logger.warning(
                "No product URLs found via sitemaps for %s — returning empty list",
                self.store_url,
            )
            return []

        # Cap at max_products
        product_urls = product_urls[: self.max_products]
        logger.info(
            "Scraping %d product pages for %s", len(product_urls), self.store_url
        )

        # Step 3 — parallel product-page scraping (bounded concurrency)
        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def scrape_one(url: str) -> Optional[ProductItem]:
            async with sem:
                return await self._scrape_product_page(url)

        results = await asyncio.gather(*[scrape_one(u) for u in product_urls])
        items = [r for r in results if r is not None]

        logger.info(
            "PerStoreScraper finished: %d products scraped from %s",
            len(items),
            self.store_url,
        )
        return [item.model_dump() for item in items]

    # ------------------------------------------------------------------
    # Sitemap discovery
    # ------------------------------------------------------------------

    async def _discover_product_urls(self) -> list[str]:
        """
        Probe known sitemap paths and extract product URLs.

        Tries each path in :data:`_SITEMAP_PATHS` in order.  Returns the
        URLs found in the first sitemap that parses successfully.

        Returns:
            Deduplicated list of absolute product page URLs.
        """
        for path in _SITEMAP_PATHS:
            sitemap_url = urljoin(self.store_url + "/", path.lstrip("/"))
            logger.debug("Probing sitemap at %s", sitemap_url)
            try:
                xml = await self._fetch_sitemap(sitemap_url)
                urls = self._parse_sitemap(xml)
                if urls:
                    logger.info(
                        "Found %d product URLs in sitemap %s", len(urls), sitemap_url
                    )
                    return urls
            except Exception as exc:
                logger.debug("Sitemap probe failed for %s: %s", sitemap_url, exc)
                continue

        # Fallback: try to find a sitemap link in the homepage HTML
        return await self._discover_sitemap_from_html()

    async def _fetch_sitemap(self, url: str) -> str:
        """
        Fetch a sitemap URL using httpx (no JavaScript needed).

        Args:
            url: Sitemap URL to fetch.

        Returns:
            Raw XML/HTML string.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
        """
        return await self.get_static_html(url)

    def _parse_sitemap(self, xml: str) -> list[str]:
        """
        Parse a sitemap XML string and extract ``<loc>`` URLs.

        Filters for URLs that look like product pages using heuristics:
        contains ``/product``, ``/p/``, ``/item``, or ``/products/``.

        Args:
            xml: Raw sitemap XML text.

        Returns:
            Deduplicated list of product URLs.
        """
        soup = BeautifulSoup(xml, "xml")  # lxml-xml parser via bs4
        locs = soup.find_all("loc")
        urls: list[str] = []
        seen: set[str] = set()

        for loc in locs:
            href = loc.get_text(strip=True)
            if not href:
                continue
            # TODO: store-specific tuning — adjust URL patterns per retailer
            if self._looks_like_product_url(href) and href not in seen:
                seen.add(href)
                urls.append(href)

        return urls

    @staticmethod
    def _looks_like_product_url(url: str) -> bool:
        """
        Heuristic: return True if the URL looks like a product page.

        Matches paths containing ``/product``, ``/item``, ``/p/``,
        or Shopify-style ``/products/``.

        Args:
            url: Absolute URL string to test.

        Returns:
            True if the URL likely points to a product page.
        """
        # TODO: store-specific tuning — extend or replace this heuristic
        patterns = [
            r"/products?/",
            r"/item/",
            r"/p/",
            r"[_-]p[_-]?\d",    # common pattern: slug-p-12345
        ]
        path = urlparse(url).path.lower()
        return any(re.search(p, path) for p in patterns)

    async def _discover_sitemap_from_html(self) -> list[str]:
        """
        Fallback: load the store homepage with Playwright, look for a
        ``<link rel="sitemap">`` element, then fetch and parse it.

        Returns:
            List of product URLs, or empty list on failure.
        """
        logger.debug("Trying HTML-based sitemap discovery for %s", self.store_url)
        try:
            html = await self.get_raw_html(self.store_url)
        except Exception as exc:
            logger.warning(
                "Could not load store homepage for sitemap discovery: %s", exc
            )
            return []

        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("link", rel="sitemap")
        if not link:
            logger.debug("No <link rel='sitemap'> found on %s", self.store_url)
            return []

        href = link.get("href", "")
        if not href:
            return []

        sitemap_url = href if href.startswith("http") else urljoin(self.store_url + "/", href)
        logger.info("Found sitemap via HTML link: %s", sitemap_url)
        try:
            xml = await self._fetch_sitemap(sitemap_url)
            return self._parse_sitemap(xml)
        except Exception as exc:
            logger.warning("Failed to parse discovered sitemap %s: %s", sitemap_url, exc)
            return []

    # ------------------------------------------------------------------
    # Product page extraction
    # ------------------------------------------------------------------

    async def _scrape_product_page(self, url: str) -> Optional[ProductItem]:
        """
        Fetch and parse a single product page.

        Extraction priority:
            1. Schema.org ``Product`` JSON-LD.
            2. ``[itemprop]`` microdata attributes.
            3. Returns None if neither name nor price can be found.

        Also saves raw HTML to ``data/raw/{store_slug}/`` if
        ``save_raw`` is True.

        Args:
            url: Absolute URL of the product page.

        Returns:
            A :class:`~scraper.base.ProductItem` or None on failure.
        """
        try:
            html = await self.get_raw_html(url)
        except Exception as exc:
            logger.debug("Failed to fetch %s: %s", url, exc)
            return None

        if self.save_raw:
            await self._save_raw_snapshot(url, html)

        soup = BeautifulSoup(html, "html.parser")

        # --- Strategy 1: JSON-LD schema.org Product ---
        item = self._extract_from_jsonld(soup, url)
        if item:
            return item

        # --- Strategy 2: itemprop microdata ---
        item = self._extract_from_itemprop(soup, url)
        return item  # may be None if extraction failed entirely

    def _extract_from_jsonld(
        self, soup: BeautifulSoup, page_url: str
    ) -> Optional[ProductItem]:
        """
        Extract product data from schema.org ``Product`` JSON-LD blocks.

        Iterates all ``<script type="application/ld+json">`` tags and
        returns the first valid Product-typed block found.

        Args:
            soup:     Parsed BeautifulSoup tree.
            page_url: URL of the page (used to populate ``product_url``).

        Returns:
            :class:`~scraper.base.ProductItem` or None.
        """
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            # Normalise: data can be a dict or a list of dicts
            if isinstance(data, list):
                nodes = data
            elif isinstance(data, dict):
                # Handle @graph
                nodes = data.get("@graph", [data])
            else:
                continue

            for node in nodes:
                if not isinstance(node, dict):
                    continue
                schema_type = node.get("@type", "")
                if isinstance(schema_type, list):
                    is_product = "Product" in schema_type
                else:
                    is_product = schema_type == "Product"

                if not is_product:
                    continue

                name: str = node.get("name", "").strip()
                if not name:
                    continue

                # Price — can be in 'offers' or directly on the node
                price: Optional[float] = None
                currency: str = "ILS"
                availability: Optional[bool] = None
                image_url: Optional[str] = None

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
                        availability = "InStock" in avail_str or "instock" in avail_str.lower()

                # Image
                img = node.get("image")
                if isinstance(img, str):
                    image_url = img
                elif isinstance(img, list) and img:
                    image_url = img[0] if isinstance(img[0], str) else None
                elif isinstance(img, dict):
                    image_url = img.get("url")

                # Description
                raw_description: Optional[str] = node.get("description")

                # Category hint from breadcrumb or category field
                # TODO: store-specific tuning — some stores embed richer taxonomy
                category_hint: Optional[str] = (
                    node.get("category")
                    or node.get("productType")
                    or None
                )

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

    def _extract_from_itemprop(
        self, soup: BeautifulSoup, page_url: str
    ) -> Optional[ProductItem]:
        """
        Extract product data from HTML ``itemprop`` microdata attributes.

        Looks for the first element with ``[itemprop="name"]``,
        ``[itemprop="price"]``, and ``[itemprop="availability"]``.

        Args:
            soup:     Parsed BeautifulSoup tree.
            page_url: URL of the page.

        Returns:
            :class:`~scraper.base.ProductItem` or None if name is missing.
        """
        # Name
        name_el = soup.select_one('[itemprop="name"]')
        name = name_el.get_text(strip=True) if name_el else ""
        if not name:
            logger.debug("itemprop extraction: no name found on %s", page_url)
            return None

        # Price
        price: Optional[float] = None
        price_el = soup.select_one('[itemprop="price"]')
        if price_el:
            # Price can be in 'content' attribute or text content
            price_str = price_el.get("content") or price_el.get_text(strip=True)
            if price_str:
                # Strip currency symbols and whitespace
                # TODO: store-specific tuning — Hebrew ₪ and other symbols
                cleaned = re.sub(r"[^\d.,]", "", price_str).replace(",", "")
                try:
                    price = float(cleaned)
                except ValueError:
                    pass

        # Availability
        availability: Optional[bool] = None
        avail_el = soup.select_one('[itemprop="availability"]')
        if avail_el:
            avail_str = (
                avail_el.get("content", "")
                or avail_el.get("href", "")
                or avail_el.get_text(strip=True)
            )
            if avail_str:
                availability = "InStock" in avail_str or "instock" in avail_str.lower()

        # Image
        image_url: Optional[str] = None
        img_el = soup.select_one('[itemprop="image"]')
        if img_el:
            image_url = (
                img_el.get("content")
                or img_el.get("src")
                or img_el.get("href")
            )

        # Category hint
        # TODO: store-specific tuning — breadcrumb selectors vary per store
        category_hint: Optional[str] = None
        cat_el = soup.select_one('[itemprop="category"]')
        if cat_el:
            category_hint = cat_el.get("content") or cat_el.get_text(strip=True)

        return ProductItem(
            name=name,
            price=price,
            currency="ILS",
            availability=availability,
            product_url=page_url,
            image_url=image_url,
            raw_description=None,  # not extracted in microdata path
            category_hint=category_hint,
        )

    # ------------------------------------------------------------------
    # Raw snapshot persistence
    # ------------------------------------------------------------------

    async def _save_raw_snapshot(self, url: str, html: str) -> None:
        """
        Save raw HTML for a product page to ``data/raw/{store_slug}/``.

        The filename is derived from the URL path to avoid collisions.
        Long paths are truncated and sanitised for filesystem safety.

        Args:
            url:  The product page URL (used to derive a filename).
            html: The raw HTML string to save.
        """
        store_dir = _RAW_DATA_DIR / self._store_slug
        store_dir.mkdir(parents=True, exist_ok=True)

        # Sanitise URL path into a filename
        parsed = urlparse(url)
        safe_path = re.sub(r"[^a-zA-Z0-9_\-]", "_", parsed.path)[:200]
        filename = f"{safe_path or 'index'}.html"
        filepath = store_dir / filename

        try:
            filepath.write_text(html, encoding="utf-8")
            logger.debug("Saved raw snapshot → %s", filepath)
        except OSError as exc:
            logger.warning("Could not save raw snapshot for %s: %s", url, exc)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _slug_from_url(url: str) -> str:
        """
        Convert a store URL to a filesystem-safe slug.

        Example:
            ``https://www.ksp.co.il`` → ``ksp_co_il``

        Args:
            url: Store root URL.

        Returns:
            Filesystem-safe slug string.
        """
        hostname = urlparse(url).hostname or url
        # Strip common prefixes
        hostname = re.sub(r"^www\.", "", hostname)
        # Replace non-alphanumeric chars with underscores
        return re.sub(r"[^a-zA-Z0-9]", "_", hostname)
