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
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_ai_client, get_db, get_settings
from api.schemas import (
    ProductResult,
    QueryProduct,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    StoreInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_GEMINI_MODEL = "gemini-2.0-flash"
_EMBEDDING_MODEL = "text-embedding-004"  # Gemini, 768 dims
_HTTP_TIMEOUT = 10.0
_MAX_RESULTS = 20
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
    request: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    ai: Annotated[AsyncOpenAI, Depends(get_ai_client)],
) -> SearchResponse:
    start_time = time.time()
    query = request.query.strip()
    filters = request.filters

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
                total=0, exact_matches=0, similar_matches=0,
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
    # Step 4: pgvector cosine search (falls back to ILIKE if no embeddings)
    # ------------------------------------------------------------------
    if embedding:
        vec_str = _vec_literal(embedding)
        sql = text("""
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
        result = await db.execute(sql, {"vec": vec_str, "limit": _MAX_RESULTS * 3})
        rows = result.mappings().all()

        # If no embeddings exist yet, fall back to ILIKE
        if not rows:
            embedding = None

    if not embedding:
        # ILIKE fallback
        sql = text("""
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
            ORDER BY sp.product_id, sp.store_id
            LIMIT :limit
        """)
        result = await db.execute(
            sql, {"term": f"%{search_text}%", "limit": _MAX_RESULTS}
        )
        raw_rows = result.mappings().all()

        # Compute word-overlap similarity instead of a static 0.5
        query_words = set(search_text.lower().split())
        enriched: list[dict] = []
        for r in raw_rows:
            name_words = set((r["canonical_name"] or "").lower().split())
            overlap = len(query_words & name_words)
            similarity = min(0.9, 0.4 + (overlap / max(len(query_words), 1)) * 0.5)
            enriched.append({**r, "similarity": similarity})
        rows = enriched

    # ------------------------------------------------------------------
    # Step 5: Apply filters and build results
    # ------------------------------------------------------------------
    product_results: list[ProductResult] = []
    exact_matches = 0
    similar_matches = 0

    for row in rows:
        # online_only filter
        if filters.online_only and not row["is_online"]:
            continue

        # city filter
        if filters.city:
            city = row["city"] or ""
            if filters.city.lower() not in city.lower():
                continue

        # max_price filter
        if filters.max_price is not None and row["price"] is not None:
            if row["price"] > filters.max_price:
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
            exact_matches += 1
        else:
            similar_matches += 1

        store_info = StoreInfo(
            id=str(row["store_id"]),
            name_he=row["name_he"],
            name_en=row["name_en"],
            buyme_url=row["buyme_url"],
            is_online=row["is_online"],
            city=row["city"],
            distance_km=distance_km,
        )
        product_results.append(
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

        if len(product_results) >= _MAX_RESULTS:
            break

    return SearchResponse(
        results=product_results,
        query_product=QueryProduct(
            raw_query=query,
            extracted_name=product_name,
            brand=brand,
            estimated_price=None,
            extraction_success=True,
        ),
        total=len(product_results),
        exact_matches=exact_matches,
        similar_matches=similar_matches,
        search_time_ms=round((time.time() - start_time) * 1000, 2),
    )
