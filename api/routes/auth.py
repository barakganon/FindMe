"""
api/routes/auth.py — Registration, login, Google OAuth, session import.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import create_access_token, hash_password, verify_password, get_current_user
from api.dependencies import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    google_token: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class ImportSessionRequest(BaseModel):
    session_history: list[dict] = []
    session_context: Optional[dict] = None


@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    from db.models import User
    # Check duplicate
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="אימייל כבר קיים במערכת")

    user = User(
        email=req.email,
        display_name=req.display_name,
        password_hash=hash_password(req.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user={"id": str(user.id), "email": user.email, "display_name": user.display_name},
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    from db.models import User
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="אימייל או סיסמה שגויים")

    token = create_access_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user={"id": str(user.id), "email": user.email, "display_name": user.display_name},
    )


@router.post("/google", response_model=AuthResponse)
async def google_auth(req: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    """Verify Google token and find/create user."""
    from db.models import User
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={req.google_token}"
            )
            data = resp.json()
            if "error" in data:
                raise HTTPException(status_code=401, detail="Invalid Google token")

            google_id = data.get("sub")
            email = data.get("email")
            name = data.get("name")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="שגיאה באימות Google")

    # Find or create
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if not user:
        user = User(email=email, display_name=name, google_id=google_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif not user.google_id:
        user.google_id = google_id
        await db.commit()

    token = create_access_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user={"id": str(user.id), "email": user.email, "display_name": user.display_name},
    )


@router.get("/me")
async def get_me(current_user=Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "display_name": current_user.display_name,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.post("/import-session")
async def import_session(
    req: ImportSessionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import UserSearchHistory, UserLocation

    # Import session history
    for turn in req.session_history:
        if turn.get("role") == "user" and turn.get("content"):
            history_row = UserSearchHistory(
                user_id=current_user.id,
                message=turn["content"],
                voucher_network="buyme",
            )
            db.add(history_row)

    # Save GPS as default location if provided
    ctx = req.session_context or {}
    if ctx.get("user_lat") and ctx.get("user_lng"):
        loc = UserLocation(
            user_id=current_user.id,
            label=ctx.get("location_label") or "מיקום שמור",
            lat=ctx["user_lat"],
            lng=ctx["user_lng"],
            is_default=True,
        )
        db.add(loc)

    await db.commit()
    return {"status": "ok", "imported": len(req.session_history)}
