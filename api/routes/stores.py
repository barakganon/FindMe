"""
api/routes/stores.py — Store endpoints for BuyMe Smart Search.

Endpoints:
    GET  /stores          — Paginated list with simple query-param filters
    POST /stores/search   — Rich store search with geo proximity + product count
    GET  /geocode         — Free-text address → lat/lng via Nominatim
"""

from __future__ import annotations

import logging
import math
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas import (
    StoreInfo,
    StoreListResponse,
    StoreResult,
    StoreSearchRequest,
    StoreSearchResponse,
)

# Import ORM models — db/models.py is owned by the DB agent; we only read here.
from db.models import Store, StoreProduct

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Internal helper: haversine approximation (matches search.py convention)
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return approximate great-circle distance in km using flat-earth formula."""
    lat_km = (lat1 - lat2) * 111.0
    lng_km = (lng1 - lng2) * 111.0 * math.cos(math.radians(lat1))
    return math.sqrt(lat_km**2 + lng_km**2)


@router.get("/stores", response_model=StoreListResponse)
async def list_stores(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
    page_size: int = 50,
    city: Optional[str] = None,
    category: Optional[str] = None,
    online_only: bool = False,
) -> StoreListResponse:
    """
    Return a paginated list of BuyMe partner stores.

    Query parameters:
        page        — 1-indexed page number (default: 1)
        page_size   — results per page (default: 50)
        city        — filter by city name (case-insensitive substring match)
        category    — filter by BuyMe category (e.g. "retail", "restaurant", "online")
        online_only — when true, return only online stores
    """
    # ------------------------------------------------------------------
    # Build base query with optional filters
    # ------------------------------------------------------------------
    base_stmt = select(Store)

    if online_only:
        base_stmt = base_stmt.where(Store.is_online.is_(True))

    if city:
        base_stmt = base_stmt.where(Store.city.ilike(f"%{city}%"))

    if category:
        base_stmt = base_stmt.where(Store.buyme_category.ilike(f"%{category}%"))

    # ------------------------------------------------------------------
    # Count total matching stores (before pagination)
    # ------------------------------------------------------------------
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar_one()

    # ------------------------------------------------------------------
    # Paginate
    # ------------------------------------------------------------------
    offset = (page - 1) * page_size
    paginated_stmt = (
        base_stmt
        .order_by(Store.name_he)
        .offset(offset)
        .limit(page_size)
    )

    rows_result = await db.execute(paginated_stmt)
    stores: list[Store] = list(rows_result.scalars().all())

    # ------------------------------------------------------------------
    # Map ORM rows → StoreInfo schema objects
    # ------------------------------------------------------------------
    store_infos: list[StoreInfo] = [
        StoreInfo(
            id=str(store.id),
            name_he=store.name_he,
            name_en=store.name_en,
            buyme_url=store.buyme_url,
            is_online=store.is_online,
            city=store.city,
            distance_km=None,  # No location context in this endpoint
        )
        for store in stores
    ]

    return StoreListResponse(
        stores=store_infos,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# POST /stores/search — rich store search with geo filter + product count
# ---------------------------------------------------------------------------


@router.post("/stores/search", response_model=StoreSearchResponse)
async def search_stores(
    body: StoreSearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StoreSearchResponse:
    """
    Search BuyMe partner stores with optional filters:
      - ``query``      — ILIKE match on name_he OR name_en
      - ``store_type`` — exact match on buyme_category ('restaurant', 'retail', …)
      - ``location``   — lat/lng + radius_km proximity filter (haversine approximation)

    Results are sorted by distance ASC when a location is supplied, otherwise
    by product_count DESC.
    """
    # ------------------------------------------------------------------
    # Build base query: stores LEFT JOIN product count
    # ------------------------------------------------------------------
    product_count_subq = (
        select(
            StoreProduct.store_id,
            func.count(StoreProduct.id).label("product_count"),
        )
        .group_by(StoreProduct.store_id)
        .subquery("product_counts")
    )

    base_stmt = select(
        Store,
        func.coalesce(product_count_subq.c.product_count, 0).label("product_count"),
    ).outerjoin(product_count_subq, Store.id == product_count_subq.c.store_id)

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    if body.store_type is not None:
        base_stmt = base_stmt.where(
            Store.buyme_category.ilike(body.store_type)
        )

    if body.query:
        pattern = f"%{body.query}%"
        base_stmt = base_stmt.where(
            Store.name_he.ilike(pattern) | Store.name_en.ilike(pattern)
        )

    if body.location is not None:
        # Only include stores that have coordinates
        base_stmt = base_stmt.where(
            Store.lat.is_not(None),
            Store.lng.is_not(None),
        )

    # ------------------------------------------------------------------
    # Fetch ALL matching rows so we can apply the haversine filter and
    # compute distance in Python (avoids raw SQL math differences across
    # PostgreSQL versions and keeps logic consistent with search.py).
    # ------------------------------------------------------------------
    rows_result = await db.execute(base_stmt)
    all_rows: list[tuple[Store, int]] = list(rows_result.all())

    # ------------------------------------------------------------------
    # Geo filter + distance annotation
    # ------------------------------------------------------------------
    annotated: list[tuple[Store, int, Optional[float]]] = []

    if body.location is not None:
        center_lat = body.location.lat
        center_lng = body.location.lng
        radius_km = body.location.radius_km

        for store, product_count in all_rows:
            if store.lat is None or store.lng is None:
                continue  # already filtered above, but be safe
            dist = _haversine_km(center_lat, center_lng, store.lat, store.lng)
            if dist <= radius_km:
                annotated.append((store, product_count, round(dist, 2)))
    else:
        for store, product_count in all_rows:
            annotated.append((store, product_count, None))

    # ------------------------------------------------------------------
    # Sort
    # ------------------------------------------------------------------
    if body.location is not None:
        # Sort by distance ascending (nearest first)
        annotated.sort(key=lambda t: t[2] if t[2] is not None else float("inf"))
    else:
        # Sort by product_count descending (richest catalogs first)
        annotated.sort(key=lambda t: t[1], reverse=True)

    total_available = len(annotated)

    # ------------------------------------------------------------------
    # Paginate
    # ------------------------------------------------------------------
    offset = (body.page - 1) * body.page_size
    page_rows = annotated[offset : offset + body.page_size]

    # ------------------------------------------------------------------
    # Map → StoreResult
    # ------------------------------------------------------------------
    store_results: list[StoreResult] = [
        StoreResult(
            id=str(store.id),
            name_he=store.name_he,
            name_en=store.name_en,
            buyme_url=store.buyme_url,
            buyme_category=store.buyme_category,
            address=store.address,
            city=store.city,
            lat=store.lat,
            lng=store.lng,
            distance_km=distance_km,
            is_online=store.is_online,
            product_count=product_count,
        )
        for store, product_count, distance_km in page_rows
    ]

    return StoreSearchResponse(
        stores=store_results,
        total=len(store_results),
        total_available=total_available,
        page=body.page,
        page_size=body.page_size,
    )


# ---------------------------------------------------------------------------
# GET /geocode — free-text address → lat/lng via Nominatim
# ---------------------------------------------------------------------------

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {"User-Agent": "FindMe/1.0"}


@router.get("/geocode")
async def geocode_address(address: str) -> dict:
    """
    Geocode a free-text address using Nominatim (OpenStreetMap).

    Returns ``{lat, lng, display_name}`` on success, or HTTP 404 if no
    results were found for the given address.

    Query parameters:
        address — Free-text address string (Hebrew or English), e.g. "יקב כרמל, זכרון יעקב"
    """
    params = {
        "q": address,
        "format": "json",
        "limit": "1",
        "countrycodes": "il",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            _NOMINATIM_URL,
            params=params,
            headers=_NOMINATIM_HEADERS,
        )
        response.raise_for_status()
        results: list[dict] = response.json()

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No geocoding results found for address: {address!r}",
        )

    hit = results[0]
    return {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "display_name": hit.get("display_name", ""),
    }
