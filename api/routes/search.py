"""
api/routes/search.py — POST /search endpoint for BuyMe Smart Search.

Flow:
    1. Fetch URL content with httpx (async, 10 s timeout).
    2. Extract product name / brand / price using Claude API.
    3. Text-search store_products joined to products + stores (ilike).
    4. Apply optional filters (online_only, city, max_price).
    5. Map DB rows → ProductResult objects with match_score.
    6. Return SearchResponse.

TODO: Replace text search with pgvector cosine similarity in Week 7-8
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated, Optional

import anthropic
import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import get_anthropic_client, get_db
from api.schemas import (
    ProductResult,
    QueryProduct,
    SearchRequest,
    SearchResponse,
    StoreInfo,
)

# Import ORM models — db/models.py is owned by the DB agent; we only read here.
from db.models import Product, Store, StoreProduct

logger = logging.getLogger(__name__)

router = APIRouter()

# Claude model to use for product extraction
_CLAUDE_MODEL = "claude-sonnet-4-20250514"

# HTTP client settings
_HTTP_TIMEOUT = 10.0  # seconds
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Maximum results before filtering
_MAX_RAW_RESULTS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_url_content(url: str) -> Optional[str]:
    """
    Fetch the HTML/text content of *url* with a realistic browser-like request.

    Returns the response text on success, or None if the request fails.
    A 10-second timeout is enforced to avoid blocking the event loop.
    """
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.text
    except Exception as exc:
        logger.warning("URL fetch failed for %r: %s", url, exc)
        return None


async def _extract_product_with_claude(
    url: str,
    page_content: Optional[str],
    client: anthropic.AsyncAnthropic,
) -> QueryProduct:
    """
    Use Claude to extract structured product information from a page.

    If *page_content* is None (fetch failed), Claude uses only the URL
    heuristics. Returns QueryProduct with extraction_success=False on any error.
    """
    # Truncate page content to avoid hitting token limits; keep first 8 000 chars.
    truncated_content = (page_content or "")[:8_000]

    prompt = (
        "You are a product information extractor. "
        "Given the following product page URL and its HTML content, "
        "extract the product name, brand, and estimated price.\n\n"
        f"URL: {url}\n\n"
        f"PAGE CONTENT (first 8000 chars):\n{truncated_content}\n\n"
        "Respond ONLY with a JSON object containing these fields:\n"
        '  "product_name": string or null\n'
        '  "brand": string or null\n'
        '  "estimated_price": number or null (numeric value only, no currency symbol)\n\n'
        "If the information is not available or unclear, use null for that field."
    )

    try:
        message = await client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()

        # Parse the JSON response from Claude
        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = json.loads(raw_text)
        return QueryProduct(
            raw_url=url,
            extracted_name=data.get("product_name"),
            brand=data.get("brand"),
            estimated_price=data.get("estimated_price"),
            extraction_success=True,
        )
    except Exception as exc:
        logger.warning("Claude extraction failed for %r: %s", url, exc)
        return QueryProduct(
            raw_url=url,
            extracted_name=None,
            brand=None,
            estimated_price=None,
            extraction_success=False,
        )


def _compute_match_score(canonical_name: str, query_name: str) -> float:
    """
    Compute a simple text-based match score between a DB product name and the query.

    Returns:
        1.0  — names are identical (case-insensitive)
        0.7  — query name is a substring of the canonical name (or vice-versa)
        0.5  — default for any other match (e.g. individual word overlap from ilike)
    """
    if not query_name:
        return 0.5
    cn_lower = canonical_name.lower()
    q_lower = query_name.lower()
    if cn_lower == q_lower:
        return 1.0
    if q_lower in cn_lower or cn_lower in q_lower:
        return 0.7
    return 0.5


def _build_store_info(store: Store, location_filter=None) -> StoreInfo:
    """Map a Store ORM object to a StoreInfo schema object."""
    distance_km: Optional[float] = None
    if location_filter is not None and store.lat is not None and store.lng is not None:
        # Basic Euclidean approximation — good enough for display purposes.
        # PostGIS ST_Distance will replace this in Week 7-8.
        import math

        lat_diff = store.lat - location_filter.lat
        lng_diff = store.lng - location_filter.lng
        # 1 degree latitude ≈ 111 km; longitude varies with latitude
        lat_km = lat_diff * 111.0
        lng_km = lng_diff * 111.0 * math.cos(math.radians(location_filter.lat))
        distance_km = round(math.sqrt(lat_km**2 + lng_km**2), 2)

    return StoreInfo(
        id=str(store.id),
        name_he=store.name_he,
        name_en=store.name_en,
        buyme_url=store.buyme_url,
        is_online=store.is_online,
        city=store.city,
        distance_km=distance_km,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponse)
async def search_products(
    request: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    claude: Annotated[anthropic.AsyncAnthropic, Depends(get_anthropic_client)],
) -> SearchResponse:
    """
    Search for BuyMe partner store products matching the item at the given URL.

    Steps:
      1. Fetch URL content.
      2. Extract product info via Claude.
      3. Text-search DB (ilike on canonical_name).
      4. Apply filters.
      5. Build and return SearchResponse.

    Errors during URL fetch or Claude extraction are handled gracefully —
    an empty result set is returned rather than raising HTTP 500.
    """
    start_time = time.time()

    # ------------------------------------------------------------------
    # Step 1: Fetch URL content
    # ------------------------------------------------------------------
    page_content = await _fetch_url_content(request.url)

    # ------------------------------------------------------------------
    # Step 2: Extract product from URL using Claude
    # ------------------------------------------------------------------
    query_product = await _extract_product_with_claude(request.url, page_content, claude)

    # If extraction failed and we have no product name, return empty results.
    if not query_product.extraction_success or not query_product.extracted_name:
        search_time_ms = (time.time() - start_time) * 1000
        return SearchResponse(
            results=[],
            query_product=query_product,
            total=0,
            exact_matches=0,
            similar_matches=0,
            search_time_ms=round(search_time_ms, 2),
        )

    # ------------------------------------------------------------------
    # Step 3: Text search — ilike on canonical_name
    # TODO: Replace text search with pgvector cosine similarity in Week 7-8
    # ------------------------------------------------------------------
    search_term = f"%{query_product.extracted_name}%"

    stmt = (
        select(StoreProduct)
        .join(StoreProduct.product)
        .join(StoreProduct.store)
        .where(Product.canonical_name.ilike(search_term))
        .options(
            selectinload(StoreProduct.product),
            selectinload(StoreProduct.store),
        )
        .limit(_MAX_RAW_RESULTS)
    )

    result = await db.execute(stmt)
    store_products: list[StoreProduct] = list(result.scalars().all())

    # ------------------------------------------------------------------
    # Step 4: Apply filters
    # ------------------------------------------------------------------
    filters = request.filters

    filtered: list[StoreProduct] = []
    for sp in store_products:
        store = sp.store
        product = sp.product

        # online_only filter
        if filters.online_only and not store.is_online:
            continue

        # city filter (case-insensitive substring match)
        if filters.city and store.city:
            if filters.city.lower() not in store.city.lower():
                continue
        elif filters.city and not store.city:
            continue

        # max_price filter
        if filters.max_price is not None and sp.price is not None:
            if sp.price > filters.max_price:
                continue

        # location radius filter — exclude stores outside radius
        if filters.location is not None and store.lat is not None and store.lng is not None:
            import math

            lat_diff = store.lat - filters.location.lat
            lng_diff = store.lng - filters.location.lng
            lat_km = lat_diff * 111.0
            lng_km = lng_diff * 111.0 * math.cos(math.radians(filters.location.lat))
            distance_km = math.sqrt(lat_km**2 + lng_km**2)
            if distance_km > filters.location.radius_km:
                continue

        filtered.append(sp)

    # ------------------------------------------------------------------
    # Step 5: Build response
    # ------------------------------------------------------------------
    product_results: list[ProductResult] = []
    exact_matches = 0
    similar_matches = 0

    for sp in filtered:
        store = sp.store
        product = sp.product

        score = _compute_match_score(product.canonical_name, query_product.extracted_name or "")

        # Apply min_match_score filter
        if score < filters.min_match_score:
            continue

        if score == 1.0:
            exact_matches += 1
        else:
            similar_matches += 1

        store_info = _build_store_info(store, filters.location)

        product_results.append(
            ProductResult(
                product_id=str(product.id),
                canonical_name=product.canonical_name,
                brand=product.brand,
                category_path=product.category_path,
                store=store_info,
                price=sp.price,
                currency=sp.currency,
                availability=sp.availability,
                product_url=sp.product_url,
                match_score=score,
            )
        )

    search_time_ms = (time.time() - start_time) * 1000

    return SearchResponse(
        results=product_results,
        query_product=query_product,
        total=len(product_results),
        exact_matches=exact_matches,
        similar_matches=similar_matches,
        search_time_ms=round(search_time_ms, 2),
    )
