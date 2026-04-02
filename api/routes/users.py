"""
api/routes/users.py — User profile, locations, vouchers, preferences,
favorites, search history, and inferred attributes endpoints.

All routes require a valid JWT via get_current_user.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.dependencies import get_db

router = APIRouter(prefix="/users", tags=["Users"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None


class LocationCreateRequest(BaseModel):
    label: str
    lat: float
    lng: float
    address: Optional[str] = None
    is_default: bool = False


class LocationUpdateRequest(BaseModel):
    label: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    is_default: Optional[bool] = None


class VoucherCreateRequest(BaseModel):
    voucher_network: str
    nickname: Optional[str] = None
    balance: Optional[float] = None
    expiry_date: Optional[str] = None  # ISO date string "YYYY-MM-DD"


class VoucherUpdateRequest(BaseModel):
    nickname: Optional[str] = None
    balance: Optional[float] = None
    expiry_date: Optional[str] = None
    is_active: Optional[bool] = None


class FavoriteCreateRequest(BaseModel):
    store_id: str
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@router.get("/me")
async def get_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserLocation, UserVoucherCard
    from sqlalchemy import select as sa_select

    # Default location
    loc_result = await db.execute(
        sa_select(UserLocation)
        .where(UserLocation.user_id == current_user.id, UserLocation.is_default == True)
        .limit(1)
    )
    default_loc = loc_result.scalar_one_or_none()

    # Active vouchers count
    vc_result = await db.execute(
        sa_select(UserVoucherCard).where(
            UserVoucherCard.user_id == current_user.id,
            UserVoucherCard.is_active == True,
        )
    )
    active_vouchers = vc_result.scalars().all()

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "display_name": current_user.display_name,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "default_location": (
            {
                "id": str(default_loc.id),
                "label": default_loc.label,
                "lat": default_loc.lat,
                "lng": default_loc.lng,
                "address": default_loc.address,
            }
            if default_loc
            else None
        ),
        "active_vouchers": [
            {
                "id": str(v.id),
                "voucher_network": v.voucher_network,
                "nickname": v.nickname,
                "balance": float(v.balance) if v.balance is not None else None,
                "expiry_date": v.expiry_date.isoformat() if v.expiry_date else None,
            }
            for v in active_vouchers
        ],
    }


@router.put("/me")
async def update_profile(
    req: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.display_name is not None:
        current_user.display_name = req.display_name
        await db.commit()
    return {"id": str(current_user.id), "email": current_user.email, "display_name": current_user.display_name}


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


@router.get("/me/locations")
async def list_locations(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserLocation
    result = await db.execute(
        select(UserLocation).where(UserLocation.user_id == current_user.id)
    )
    locations = result.scalars().all()
    return [
        {
            "id": str(loc.id),
            "label": loc.label,
            "lat": loc.lat,
            "lng": loc.lng,
            "address": loc.address,
            "is_default": loc.is_default,
            "created_at": loc.created_at.isoformat(),
        }
        for loc in locations
    ]


@router.post("/me/locations", status_code=status.HTTP_201_CREATED)
async def add_location(
    req: LocationCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserLocation

    # If new location is default, clear existing defaults
    if req.is_default:
        existing = await db.execute(
            select(UserLocation).where(
                UserLocation.user_id == current_user.id,
                UserLocation.is_default == True,
            )
        )
        for old in existing.scalars().all():
            old.is_default = False

    loc = UserLocation(
        user_id=current_user.id,
        label=req.label,
        lat=req.lat,
        lng=req.lng,
        address=req.address,
        is_default=req.is_default,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return {"id": str(loc.id), "label": loc.label, "lat": loc.lat, "lng": loc.lng, "address": loc.address, "is_default": loc.is_default}


@router.put("/me/locations/{location_id}")
async def update_location(
    location_id: str,
    req: LocationUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserLocation
    result = await db.execute(
        select(UserLocation).where(
            UserLocation.id == UUID(location_id),
            UserLocation.user_id == current_user.id,
        )
    )
    loc = result.scalar_one_or_none()
    if not loc:
        raise HTTPException(status_code=404, detail="מיקום לא נמצא")

    if req.is_default:
        existing = await db.execute(
            select(UserLocation).where(
                UserLocation.user_id == current_user.id,
                UserLocation.is_default == True,
            )
        )
        for old in existing.scalars().all():
            old.is_default = False

    if req.label is not None:
        loc.label = req.label
    if req.lat is not None:
        loc.lat = req.lat
    if req.lng is not None:
        loc.lng = req.lng
    if req.address is not None:
        loc.address = req.address
    if req.is_default is not None:
        loc.is_default = req.is_default

    await db.commit()
    return {"id": str(loc.id), "label": loc.label, "lat": loc.lat, "lng": loc.lng, "is_default": loc.is_default}


@router.delete("/me/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
    location_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserLocation
    result = await db.execute(
        select(UserLocation).where(
            UserLocation.id == UUID(location_id),
            UserLocation.user_id == current_user.id,
        )
    )
    loc = result.scalar_one_or_none()
    if not loc:
        raise HTTPException(status_code=404, detail="מיקום לא נמצא")
    await db.delete(loc)
    await db.commit()


# ---------------------------------------------------------------------------
# Voucher cards
# ---------------------------------------------------------------------------


@router.get("/me/vouchers")
async def list_vouchers(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserVoucherCard
    result = await db.execute(
        select(UserVoucherCard).where(UserVoucherCard.user_id == current_user.id)
    )
    vouchers = result.scalars().all()
    return [
        {
            "id": str(v.id),
            "voucher_network": v.voucher_network,
            "nickname": v.nickname,
            "balance": float(v.balance) if v.balance is not None else None,
            "expiry_date": v.expiry_date.isoformat() if v.expiry_date else None,
            "is_active": v.is_active,
            "created_at": v.created_at.isoformat(),
        }
        for v in vouchers
    ]


@router.post("/me/vouchers", status_code=status.HTTP_201_CREATED)
async def add_voucher(
    req: VoucherCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserVoucherCard
    from datetime import date as date_type

    expiry = None
    if req.expiry_date:
        try:
            expiry = date_type.fromisoformat(req.expiry_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="תאריך פקיעה לא תקין — השתמש בפורמט YYYY-MM-DD")

    card = UserVoucherCard(
        user_id=current_user.id,
        voucher_network=req.voucher_network,
        nickname=req.nickname,
        balance=req.balance,
        expiry_date=expiry,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return {
        "id": str(card.id),
        "voucher_network": card.voucher_network,
        "nickname": card.nickname,
        "balance": float(card.balance) if card.balance is not None else None,
        "expiry_date": card.expiry_date.isoformat() if card.expiry_date else None,
        "is_active": card.is_active,
    }


@router.put("/me/vouchers/{voucher_id}")
async def update_voucher(
    voucher_id: str,
    req: VoucherUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserVoucherCard
    from datetime import date as date_type

    result = await db.execute(
        select(UserVoucherCard).where(
            UserVoucherCard.id == UUID(voucher_id),
            UserVoucherCard.user_id == current_user.id,
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="כרטיס לא נמצא")

    if req.nickname is not None:
        card.nickname = req.nickname
    if req.balance is not None:
        card.balance = req.balance
    if req.is_active is not None:
        card.is_active = req.is_active
    if req.expiry_date is not None:
        try:
            card.expiry_date = date_type.fromisoformat(req.expiry_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="תאריך פקיעה לא תקין")

    await db.commit()
    return {
        "id": str(card.id),
        "voucher_network": card.voucher_network,
        "nickname": card.nickname,
        "balance": float(card.balance) if card.balance is not None else None,
        "expiry_date": card.expiry_date.isoformat() if card.expiry_date else None,
        "is_active": card.is_active,
    }


@router.delete("/me/vouchers/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voucher(
    voucher_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserVoucherCard
    result = await db.execute(
        select(UserVoucherCard).where(
            UserVoucherCard.id == UUID(voucher_id),
            UserVoucherCard.user_id == current_user.id,
        )
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="כרטיס לא נמצא")
    await db.delete(card)
    await db.commit()


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


@router.get("/me/preferences")
async def get_preferences(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserPreference
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    prefs = result.scalars().all()
    return {p.key: p.value for p in prefs}


@router.put("/me/preferences")
async def update_preferences(
    updates: dict,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserPreference
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for key, value in updates.items():
        # Upsert each preference
        existing = await db.execute(
            select(UserPreference).where(
                UserPreference.user_id == current_user.id,
                UserPreference.key == key,
            )
        )
        pref = existing.scalar_one_or_none()
        if pref:
            pref.value = str(value)
        else:
            new_pref = UserPreference(
                user_id=current_user.id,
                key=key,
                value=str(value),
            )
            db.add(new_pref)

    await db.commit()
    return {"status": "ok", "updated": list(updates.keys())}


@router.delete("/me/preferences/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preference(
    key: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserPreference
    result = await db.execute(
        select(UserPreference).where(
            UserPreference.user_id == current_user.id,
            UserPreference.key == key,
        )
    )
    pref = result.scalar_one_or_none()
    if not pref:
        raise HTTPException(status_code=404, detail="העדפה לא נמצאה")
    await db.delete(pref)
    await db.commit()


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------


@router.get("/me/favorites")
async def list_favorites(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserFavoriteStore, Store
    result = await db.execute(
        select(UserFavoriteStore, Store)
        .join(Store, UserFavoriteStore.store_id == Store.id)
        .where(UserFavoriteStore.user_id == current_user.id)
    )
    rows = result.all()
    return [
        {
            "store_id": str(fav.store_id),
            "store_name": store.name_he,
            "buyme_url": store.buyme_url,
            "city": store.city,
            "note": fav.note,
            "saved_at": fav.saved_at.isoformat(),
        }
        for fav, store in rows
    ]


@router.post("/me/favorites", status_code=status.HTTP_201_CREATED)
async def add_favorite(
    req: FavoriteCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserFavoriteStore, Store

    # Verify store exists
    store_result = await db.execute(
        select(Store).where(Store.id == UUID(req.store_id))
    )
    if not store_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="חנות לא נמצאה")

    # Check if already favorited
    existing = await db.execute(
        select(UserFavoriteStore).where(
            UserFavoriteStore.user_id == current_user.id,
            UserFavoriteStore.store_id == UUID(req.store_id),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="חנות כבר נשמרה במועדפים")

    fav = UserFavoriteStore(
        user_id=current_user.id,
        store_id=UUID(req.store_id),
        note=req.note,
    )
    db.add(fav)
    await db.commit()
    return {"store_id": req.store_id, "note": req.note, "status": "נשמר"}


@router.delete("/me/favorites/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    store_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserFavoriteStore
    result = await db.execute(
        select(UserFavoriteStore).where(
            UserFavoriteStore.user_id == current_user.id,
            UserFavoriteStore.store_id == UUID(store_id),
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        raise HTTPException(status_code=404, detail="מועדף לא נמצא")
    await db.delete(fav)
    await db.commit()


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------


@router.get("/me/history")
async def get_history(
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserSearchHistory
    result = await db.execute(
        select(UserSearchHistory)
        .where(UserSearchHistory.user_id == current_user.id)
        .order_by(UserSearchHistory.searched_at.desc())
        .limit(limit)
    )
    history = result.scalars().all()
    return [
        {
            "id": str(h.id),
            "message": h.message,
            "intent": h.intent,
            "city_used": h.city_used,
            "result_count": h.result_count,
            "voucher_network": h.voucher_network,
            "searched_at": h.searched_at.isoformat(),
        }
        for h in history
    ]


@router.delete("/me/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserSearchHistory
    await db.execute(
        delete(UserSearchHistory).where(UserSearchHistory.user_id == current_user.id)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Inferred attributes (transparency endpoints — required by CLAUDE.md)
# ---------------------------------------------------------------------------


@router.get("/me/inferred")
async def get_inferred_attributes(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserInferredAttribute
    result = await db.execute(
        select(UserInferredAttribute)
        .where(UserInferredAttribute.user_id == current_user.id)
        .order_by(UserInferredAttribute.confidence.desc())
    )
    attrs = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "attribute": a.attribute,
            "value": a.value,
            "confidence": a.confidence,
            "source": a.source,
            "inferred_at": a.inferred_at.isoformat(),
            "last_updated": a.last_updated.isoformat(),
            "is_confirmed": a.is_confirmed,
        }
        for a in attrs
    ]


@router.delete("/me/inferred/{attribute_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inferred_attribute(
    attribute_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserInferredAttribute
    result = await db.execute(
        select(UserInferredAttribute).where(
            UserInferredAttribute.id == UUID(attribute_id),
            UserInferredAttribute.user_id == current_user.id,
        )
    )
    attr = result.scalar_one_or_none()
    if not attr:
        raise HTTPException(status_code=404, detail="מאפיין לא נמצא")
    await db.delete(attr)
    await db.commit()


@router.delete("/me/inferred", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_inferred_attributes(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserInferredAttribute
    await db.execute(
        delete(UserInferredAttribute).where(UserInferredAttribute.user_id == current_user.id)
    )
    await db.commit()


@router.put("/me/inferred/{attribute_id}/confirm")
async def confirm_inferred_attribute(
    attribute_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserInferredAttribute
    result = await db.execute(
        select(UserInferredAttribute).where(
            UserInferredAttribute.id == UUID(attribute_id),
            UserInferredAttribute.user_id == current_user.id,
        )
    )
    attr = result.scalar_one_or_none()
    if not attr:
        raise HTTPException(status_code=404, detail="מאפיין לא נמצא")
    attr.is_confirmed = True
    attr.confidence = 1.0
    await db.commit()
    return {
        "id": str(attr.id),
        "attribute": attr.attribute,
        "value": attr.value,
        "confidence": attr.confidence,
        "is_confirmed": attr.is_confirmed,
    }
