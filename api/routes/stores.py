"""
api/routes/stores.py — GET /stores endpoint for BuyMe Smart Search.

Returns a paginated list of BuyMe partner stores with optional filtering
by city, buyme_category, and online status.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas import StoreInfo, StoreListResponse

# Import ORM model — db/models.py is owned by the DB agent; we only read here.
from db.models import Store

logger = logging.getLogger(__name__)

router = APIRouter()


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
