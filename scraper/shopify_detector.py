"""
scraper/shopify_detector.py — Shopify fast-path scraper.

Many Israeli online stores run on Shopify and expose a free structured-data
endpoint at ``/products.json``.  This module checks for that endpoint and,
if present, paginates through it to harvest the full product catalog without
any HTML parsing.

Strategy:
    1. GET ``{store_url}/products.json`` — if the JSON has a ``products`` key
       the store is Shopify.
    2. Paginate through ``/products.json?page=N&limit=250`` until the response
       returns an empty ``products`` list.
    3. Map every Shopify product + variant to a :class:`~scraper.base.ProductItem`.
    4. Return ``[item.model_dump() for item in items]``.

Retry policy:
    - 3 attempts per request.
    - 2-second fixed wait between attempts (tenacity).
    - Raises on persistent failure.

Usage::

    async with ShopifyDetector("https://example.myshopify.com") as detector:
        if await detector.detect_shopify():
            products = await detector.scrape()
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from scraper.base import BaseScraper, ProductItem

logger = logging.getLogger(__name__)

# Maximum number of products per page Shopify allows
_SHOPIFY_PAGE_LIMIT = 250


class ShopifyDetector(BaseScraper):
    """
    Scraper that uses the Shopify ``/products.json`` API when available.

    Inherits shared Playwright / httpx helpers from :class:`~scraper.base.BaseScraper`
    but primarily uses async HTTP (no Playwright) for all Shopify requests.

    Args:
        store_url: Root URL of the Shopify store (e.g. ``https://store.co.il``).
        headless:  Passed to BaseScraper; Playwright is only used as a fallback.
    """

    def __init__(self, store_url: str, headless: bool = True) -> None:
        super().__init__(store_url=store_url, headless=headless)

    # ------------------------------------------------------------------
    # detect_shopify
    # ------------------------------------------------------------------

    async def detect_shopify(self) -> bool:
        """
        Check whether the store exposes a Shopify ``/products.json`` endpoint.

        GETs ``{store_url}/products.json`` and returns ``True`` if the
        response is valid JSON containing a top-level ``products`` key.

        Returns:
            ``True`` if the store is Shopify; ``False`` otherwise.
        """
        url = urljoin(self.store_url + "/", "products.json")
        try:
            text = await self._fetch_with_retry(url)
            import json

            data = json.loads(text)
            is_shopify = isinstance(data, dict) and "products" in data
            logger.info(
                "detect_shopify(%s) → %s", self.store_url, is_shopify
            )
            return is_shopify
        except Exception as exc:
            logger.debug(
                "detect_shopify(%s) returned False — %s: %s",
                self.store_url,
                type(exc).__name__,
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        """
        Scrape the full Shopify product catalog.

        If the store is not Shopify (i.e. :meth:`detect_shopify` returns
        ``False``) this method returns an empty list and logs a warning.

        Paginates through ``/products.json?page=N&limit=250`` until
        Shopify returns an empty ``products`` list.

        Returns:
            A list of :class:`~scraper.base.ProductItem` dicts
            (``ProductItem.model_dump()``), one entry per product variant.
        """
        if not await self.detect_shopify():
            logger.warning(
                "scrape() called on non-Shopify store: %s — returning empty list",
                self.store_url,
            )
            return []

        items: list[ProductItem] = []
        page = 1

        while True:
            url = (
                f"{self.store_url}/products.json"
                f"?page={page}&limit={_SHOPIFY_PAGE_LIMIT}"
            )
            logger.debug("Fetching Shopify products page %d → %s", page, url)

            try:
                text = await self._fetch_with_retry(url)
            except Exception as exc:
                logger.error(
                    "Failed to fetch Shopify page %d for %s: %s",
                    page,
                    self.store_url,
                    exc,
                )
                break

            import json

            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                logger.error("Invalid JSON on page %d: %s", page, exc)
                break

            products: list[dict] = data.get("products", [])
            if not products:
                logger.info(
                    "Shopify pagination done after %d page(s) — %d variants collected",
                    page - 1,
                    len(items),
                )
                break

            for product in products:
                items.extend(self._map_shopify_product(product))

            logger.debug(
                "Page %d: %d raw products → %d total variants so far",
                page,
                len(products),
                len(items),
            )
            page += 1

        return [item.model_dump() for item in items]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str) -> str:
        """
        GET ``url`` with a 3-attempt / 2 s-wait tenacity retry policy.

        Args:
            url: The URL to fetch.

        Returns:
            Response body as a string.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response after all retries.
            httpx.RequestError:    On network errors after all retries.
        """
        return await self.get_static_html(url)

    def _map_shopify_product(self, product: dict[str, Any]) -> list[ProductItem]:
        """
        Map a single Shopify product dict (from ``/products.json``) to a
        list of :class:`~scraper.base.ProductItem` objects — one per variant.

        A product with N variants produces N ProductItem entries, each
        carrying the variant-specific price and the shared product metadata.

        Args:
            product: A raw Shopify product dict.

        Returns:
            List of :class:`~scraper.base.ProductItem` objects.
        """
        product_title: str = product.get("title", "")
        product_type: str = product.get("product_type", "") or ""
        handle: str = product.get("handle", "")
        body_html: Optional[str] = product.get("body_html")
        vendor: str = product.get("vendor", "")

        # Product page URL — constructed from the store URL + handle
        product_url: Optional[str] = (
            f"{self.store_url}/products/{handle}" if handle else None
        )

        # Primary image URL (first image in the images array)
        images: list[dict] = product.get("images", [])
        image_url: Optional[str] = images[0].get("src") if images else None

        # Category hint: prefer product_type, fall back to tags
        tags: list[str] = product.get("tags", [])
        category_hint: Optional[str] = (
            product_type
            or (", ".join(tags[:3]) if tags else None)
        ) or None

        variants: list[dict] = product.get("variants", [])
        if not variants:
            # Product with no variants — synthesise one entry
            variants = [{}]

        items: list[ProductItem] = []
        for variant in variants:
            variant_title: str = variant.get("title", "")
            price_str: Optional[str] = variant.get("price")
            available: Optional[bool] = variant.get("available")

            # Parse price string → float
            price: Optional[float] = None
            if price_str:
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    logger.debug(
                        "Could not parse price %r for product %r",
                        price_str,
                        product_title,
                    )

            # Build display name: "Product Title - Variant Title"
            # Skip appending variant title if it's the default Shopify placeholder
            if variant_title and variant_title.lower() != "default title":
                name = f"{product_title} - {variant_title}"
            else:
                name = product_title

            # Add vendor as a prefix hint when available
            # TODO: store-specific tuning — some stores use vendor inconsistently
            if vendor and vendor.lower() not in name.lower():
                pass  # vendor available via raw_description if needed

            # Availability: Shopify can report at variant level
            # TODO: store-specific tuning — some stores use inventory_policy
            if available is None:
                # Fall back to inventory_quantity if available field is missing
                qty = variant.get("inventory_quantity")
                if qty is not None:
                    available = int(qty) > 0

            items.append(
                ProductItem(
                    name=name,
                    price=price,
                    currency="ILS",  # TODO: read from store settings if multi-currency
                    availability=available,
                    product_url=product_url,
                    image_url=image_url,
                    raw_description=body_html,
                    category_hint=category_hint,
                )
            )

        return items
