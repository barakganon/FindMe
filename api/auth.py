"""
api/auth.py — JWT authentication utilities for FindMe.
get_optional_user NEVER blocks anonymous requests — critical invariant.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db

logger = logging.getLogger(__name__)

_DEV_SECRET_DEFAULT = "dev-secret-key-change-in-production"

_APP_ENV = os.getenv("APP_ENV", "development")
_JWT_SECRET_ENV = os.getenv("JWT_SECRET")

if _APP_ENV == "production" and (not _JWT_SECRET_ENV or _JWT_SECRET_ENV == _DEV_SECRET_DEFAULT):
    raise RuntimeError(
        "JWT_SECRET must be set to a strong, unique value when APP_ENV=production "
        "(missing or using the dev default is a trivial JWT-forgery vulnerability)."
    )

if not _JWT_SECRET_ENV:
    logger.warning(
        "JWT_SECRET not set — falling back to insecure dev default. "
        "This is only acceptable outside production (APP_ENV=production)."
    )

SECRET_KEY = _JWT_SECRET_ENV or _DEV_SECRET_DEFAULT
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(user_id: UUID, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "email": email, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Requires valid JWT. Raises 401 if missing or invalid."""
    from db.models import User  # late import to avoid circular
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_optional_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Returns User if valid JWT present, None for anonymous. NEVER raises."""
    from db.models import User  # late import to avoid circular
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == UUID(user_id)))
        user = result.scalar_one_or_none()
        return user if (user and user.is_active) else None
    except Exception:
        return None
