"""
api/routes/search.py — POST /search endpoint for BuyMe Smart Search.

Flow:
    1. Detect if query is a URL or free text.
    2a. URL: fetch page, extract product name/brand with Gemini.
    2b. Free text: use as-is (optionally clean with Gemini).
    3. Embed the query text with Gemini text-embedding-004.
    4. pgvector cosine similarity search on products.embedding_vector.
       Falls back to ILIKE if no embeddings exist yet.
    5. Apply optional filters (online_only, city, max_price).
    6. Return SearchResponse.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Annotated, Any, Optional

import httpx
from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from api.dependencies import limiter

from pydantic import BaseModel

from api.cache import get_search_cache, set_search_cache
from api.dependencies import get_ai_client, get_db, get_redis, get_settings
from api.schemas import (
    ProductResult,
    QueryProduct,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    StoreInfo,
)


# ---------------------------------------------------------------------------
# Extended filter model (adds fields not yet in the READ-ONLY schemas.py)
# ---------------------------------------------------------------------------


class ExtendedSearchFilters(SearchFilters):
    """SearchFilters extended with data-quality-sprint fields.

    These fields are additive — they extend the base model without
    modifying the read-only api/schemas.py contract.
    """

    min_price: Optional[float] = None
    """Minimum product price in ILS (inclusive). Null-price products are excluded."""

    show_out_of_stock: bool = False
    """When False (default) out-of-stock products are hidden from results."""


class ExtendedSearchRequest(BaseModel):
    """SearchRequest that uses ExtendedSearchFilters instead of SearchFilters."""

    query: str
    filters: ExtendedSearchFilters = ExtendedSearchFilters()

logger = logging.getLogger(__name__)

router = APIRouter()

_GEMINI_MODEL = "gemini-2.5-flash"
_EMBEDDING_MODEL = "text-embedding-004"  # Gemini, 768 dims
_HTTP_TIMEOUT = 10.0
_MAX_CANDIDATES = 200  # max filter-passing results to collect before pagination
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_url(query: str) -> bool:
    return query.strip().startswith(("http://", "https://"))


async def _fetch_url(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": _USER_AGENT})
            r.raise_for_status()
            return r.text
    except Exception as exc:
        logger.warning("URL fetch failed for %r: %s", url, exc)
        return None


async def _extract_product_from_url(
    url: str, page_content: Optional[str], client: AsyncOpenAI
) -> tuple[str, Optional[str]]:
    """Return (product_name, brand) extracted from a URL using Gemini."""
    truncated = (page_content or "")[:8_000]
    prompt = (
        "Extract the product name and brand from this page. "
        "Respond ONLY with JSON: {\"product_name\": string, \"brand\": string or null}\n\n"
        f"URL: {url}\nPAGE: {truncated}"
    )
    try:
        msg = await client.chat.completions.create(
            model=_GEMINI_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        return data.get("product_name") or "", data.get("brand")
    except Exception as exc:
        logger.warning("Gemini extraction failed: %s", exc)
        return "", None


_GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-001:embedContent"
)
_EMBED_DIMS = 768


async def _embed(text_input: str, api_key: str) -> Optional[list[float]]:
    """Embed a string using Gemini gemini-embedding-001 (768 dims)."""
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text_input}]},
        "outputDimensionality": _EMBED_DIMS,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                _GEMINI_EMBED_URL,
                json=payload,
                params={"key": api_key},
            )
            r.raise_for_status()
            return r.json()["embedding"]["values"]
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return None


def _vec_literal(vec: list[float]) -> str:
    """Format a float list as a pgvector literal string."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat_km = (lat1 - lat2) * 111.0
    lng_km = (lng1 - lng2) * 111.0 * math.cos(math.radians(lat1))
    return math.sqrt(lat_km**2 + lng_km**2)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponse)
async def search_products(
    request: Request,
    body: ExtendedSearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> SearchResponse:
    start_time = time.time()
    query = body.query.strip()
    filters = body.filters

    # Check cache — skip embedding cost on repeated queries
    filters_dict = filters.model_dump()
    cached = await get_search_cache(redis, query, filters_dict)
    if cached is not None:
        return SearchResponse(**cached)

    # ------------------------------------------------------------------
    # Step 1 & 2: Resolve query → product name
    # ------------------------------------------------------------------
    brand: Optional[str] = None

    if _is_url(query):
        page = await _fetch_url(query)
        product_name, brand = await _extract_product_from_url(query, page, ai)
        if not product_name:
            return SearchResponse(
                results=[],
                query_product=QueryProduct(
                    raw_query=query,
                    extracted_name=None,
                    brand=None,
                    estimated_price=None,
                    extraction_success=False,
                ),
                total=0,
                total_available=0,
                page=filters.page,
                page_size=filters.page_size,
                exact_matches=0,
                similar_matches=0,
                search_time_ms=round((time.time() - start_time) * 1000, 2),
            )
        search_text = product_name
    else:
        # Free text — use directly
        search_text = query
        product_name = query

    # ------------------------------------------------------------------
    # Step 3: Embed the search text
    # ------------------------------------------------------------------
    api_key = get_settings().gemini_api_key
    embedding = await _embed(search_text, api_key)

    # ------------------------------------------------------------------
    # Step 4: Hybrid search — vector (for embedded products) + ILIKE (for all)
    # ------------------------------------------------------------------
    _ILIKE_SQL = text("""
        SELECT DISTINCT ON (sp.product_id, sp.store_id)
            sp.id            AS sp_id,
            sp.price,
            sp.currency,
            sp.availability,
            sp.product_url,
            p.id             AS product_id,
            p.canonical_name,
            p.brand          AS product_brand,
            p.category_path,
            s.id             AS store_id,
            s.name_he,
            s.name_en,
            s.buyme_url,
            s.is_online,
            s.city,
            s.lat,
            s.lng
        FROM store_products sp
        JOIN products p ON sp.product_id = p.id
        JOIN stores s ON sp.store_id = s.id
        WHERE p.canonical_name ILIKE :term
           OR p.brand ILIKE :term
           OR p.canonical_name ILIKE :word1
           OR p.canonical_name ILIKE :word2
        ORDER BY sp.product_id, sp.store_id
        LIMIT :limit
    """)

    def _word_overlap_similarity(search_words: set[str], row: Any) -> float:
        name_words = set((row["canonical_name"] or "").lower().split())
        brand_words = set((row["product_brand"] or "").lower().split())
        overlap = len(search_words & (name_words | brand_words))
        return min(0.9, 0.4 + (overlap / max(len(search_words), 1)) * 0.5)

    query_words_list = [w for w in search_text.split() if len(w) > 1]
    word1 = f"%{query_words_list[0]}%" if query_words_list else f"%{search_text}%"
    word2 = f"%{query_words_list[1]}%" if len(query_words_list) > 1 else word1
    query_words_set = set(search_text.lower().split())

    # Always run ILIKE to catch products not yet embedded
    ilike_result = await db.execute(
        _ILIKE_SQL,
        {"term": f"%{search_text}%", "word1": word1, "word2": word2, "limit": _MAX_CANDIDATES * 2}
    )
    ilike_raw = ilike_result.mappings().all()
    ilike_seen: set[str] = set()
    ilike_rows: list[dict] = []
    for r in ilike_raw:
        key = f"{r['product_id']}:{r['store_id']}"
        if key in ilike_seen:
            continue
        ilike_seen.add(key)
        sim = _word_overlap_similarity(query_words_set, r)
        ilike_rows.append({**r, "similarity": sim})
    ilike_rows.sort(key=lambda x: x["similarity"], reverse=True)

    # Run vector search if embedding is available
    vector_rows: list = []
    if embedding:
        vec_str = _vec_literal(embedding)
        vec_sql = text("""
            SELECT * FROM (
                SELECT DISTINCT ON (sp.product_id, sp.store_id)
                    sp.id            AS sp_id,
                    sp.price,
                    sp.currency,
                    sp.availability,
                    sp.product_url,
                    p.id             AS product_id,
                    p.canonical_name,
                    p.brand          AS product_brand,
                    p.category_path,
                    s.id             AS store_id,
                    s.name_he,
                    s.name_en,
                    s.buyme_url,
                    s.is_online,
                    s.city,
                    s.lat,
                    s.lng,
                    1 - (p.embedding_vector <=> CAST(:vec AS vector)) AS similarity
                FROM store_products sp
                JOIN products p ON sp.product_id = p.id
                JOIN stores s ON sp.store_id = s.id
                WHERE p.embedding_vector IS NOT NULL
                ORDER BY sp.product_id, sp.store_id, p.embedding_vector <=> CAST(:vec AS vector)
            ) deduped
            ORDER BY similarity DESC
            LIMIT :limit
        """)
        vec_result = await db.execute(vec_sql, {"vec": vec_str, "limit": _MAX_CANDIDATES * 2})
        vector_rows = list(vec_result.mappings().all())

    # Merge: start with ILIKE results (keyword matches), then add vector results not already seen
    # ILIKE results that have word overlap > 0.4 (i.e. at least 1 matching word) are high-confidence
    seen_merged: set[str] = set()
    merged: list[dict] = []

    # First: high-confidence ILIKE hits (overlap > base similarity 0.4)
    for r in ilike_rows:
        if float(r["similarity"]) > 0.4:
            key = f"{r['product_id']}:{r['store_id']}"
            seen_merged.add(key)
            merged.append(r)

    # Second: vector results with high similarity (> 0.5, to avoid noise)
    for r in vector_rows:
        key = f"{r['product_id']}:{r['store_id']}"
        if key not in seen_merged and float(r["similarity"]) > 0.5:
            seen_merged.add(key)
            merged.append(dict(r))

    # Third: remaining ILIKE results (base similarity = 0.4, no overlap)
    for r in ilike_rows:
        key = f"{r['product_id']}:{r['store_id']}"
        if key not in seen_merged:
            seen_merged.add(key)
            merged.append(r)

    # Fourth: remaining low-similarity vector results
    for r in vector_rows:
        key = f"{r['product_id']}:{r['store_id']}"
        if key not in seen_merged:
            seen_merged.add(key)
            merged.append(dict(r))

    # Sort the whole thing by similarity score
    merged.sort(key=lambda x: float(x["similarity"]), reverse=True)
    rows = merged

    # ------------------------------------------------------------------
    # Step 5: Apply filters and collect ALL passing results (up to _MAX_CANDIDATES)
    # ------------------------------------------------------------------
    all_results: list[ProductResult] = []
    all_exact = 0
    all_similar = 0

    for row in rows:
        if len(all_results) >= _MAX_CANDIDATES:
            break

        # online_only filter
        if filters.online_only and not row["is_online"]:
            continue

        # city filter
        if filters.city:
            city = row["city"] or ""
            if filters.city.lower() not in city.lower():
                continue

        # brand filter
        if filters.brand:
            product_brand = row["product_brand"] or ""
            if filters.brand.lower() not in product_brand.lower():
                continue

        # max_price filter
        if filters.max_price is not None and row["price"] is not None:
            if row["price"] > filters.max_price:
                continue

        # min_price filter — skip null-price rows when a min is set
        if filters.min_price is not None:
            if row["price"] is None or row["price"] < filters.min_price:
                continue

        # availability filter — hide out-of-stock by default unless show_out_of_stock=True
        if not filters.show_out_of_stock and not row["availability"]:
            continue

        # location radius filter
        distance_km: Optional[float] = None
        if filters.location is not None and row["lat"] is not None:
            distance_km = round(
                _distance_km(
                    filters.location.lat, filters.location.lng,
                    row["lat"], row["lng"]
                ), 2
            )
            if distance_km > filters.location.radius_km:
                continue

        similarity = float(row["similarity"])
        if similarity < filters.min_match_score:
            continue

        if similarity >= 0.9:
            all_exact += 1
        else:
            all_similar += 1

        store_info = StoreInfo(
            id=str(row["store_id"]),
            name_he=row["name_he"],
            name_en=row["name_en"],
            buyme_url=row["buyme_url"],
            is_online=row["is_online"],
            city=row["city"],
            lat=row["lat"],
            lng=row["lng"],
            distance_km=distance_km,
        )
        all_results.append(
            ProductResult(
                product_id=str(row["product_id"]),
                canonical_name=row["canonical_name"],
                brand=row["product_brand"],
                category_path=row["category_path"],
                store=store_info,
                price=row["price"],
                currency=row["currency"],
                availability=row["availability"],
                product_url=row["product_url"],
                match_score=round(similarity, 3),
            )
        )

    # ------------------------------------------------------------------
    # Step 6: Apply pagination slice
    # ------------------------------------------------------------------
    total_available = len(all_results)
    offset = (filters.page - 1) * filters.page_size
    page_results = all_results[offset: offset + filters.page_size]

    # Count exact/similar only for the current page
    exact_matches = sum(1 for r in page_results if r.match_score >= 0.9)
    similar_matches = sum(1 for r in page_results if r.match_score < 0.9)

    response = SearchResponse(
        results=page_results,
        query_product=QueryProduct(
            raw_query=query,
            extracted_name=product_name,
            brand=brand,
            estimated_price=None,
            extraction_success=True,
        ),
        total=len(page_results),
        total_available=total_available,
        page=filters.page,
        page_size=filters.page_size,
        exact_matches=exact_matches,
        similar_matches=similar_matches,
        search_time_ms=round((time.time() - start_time) * 1000, 2),
    )

    # Store in cache
    await set_search_cache(redis, query, filters_dict, response.model_dump())

    return response
