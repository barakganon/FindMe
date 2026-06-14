"""
api/dependencies.py — FastAPI dependency providers and application settings.

Provides:
    Settings       — Pydantic BaseSettings loaded from environment variables
    get_db()       — Async SQLAlchemy session dependency
    get_ai_client() — OpenAI-compatible async client pointed at Gemini
"""

from __future__ import annotations

from functools import lru_cache
from typing import AsyncGenerator

import re

from openai import AsyncOpenAI
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables (and .env file).

    Never hardcode secrets — all sensitive values must come from the environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://localhost/findme"

    # Gemini API
    gemini_api_key: str = ""

    # CORS — comma-separated list of allowed origins, e.g. "http://localhost:3000,https://app.example.com"
    cors_origins: str = "*"

    # Redis
    redis_url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")

    # Runtime environment
    app_env: str = "development"
    log_level: str = "INFO"

    # --- 5.9 cost + deploy hardening -------------------------------------
    # Cost guard. Per-turn cap lives in run_agent(); these are the higher-level
    # session and daily ceilings enforced in the v2 chat route / cost_guard.
    per_session_cost_budget_usd: float = 0.50
    daily_cost_budget_usd: float = 20.0

    # Cache TTLs (seconds). Previously hardcoded in api/cache.py; now env-driven.
    search_cache_ttl: int = 300
    intent_cache_ttl: int = 120

    # Rate limits (slowapi syntax, e.g. "20/minute"). Applied per-route.
    chat_rate_limit: str = "20/minute"
    search_rate_limit: str = "60/minute"

    # Abuse surface caps. Enforced via Pydantic field constraints + middleware.
    max_message_length: int = 2000
    max_history_items: int = 50
    # 512 KiB. A legitimate max payload (50 history msgs × 2000 Hebrew chars, up
    # to ~3 bytes/char UTF-8, + JSON overhead) can approach ~300 KB, so 256 KiB
    # was too tight and would 413 valid requests.
    max_request_body_bytes: int = 524_288  # 512 KiB

    # Port — Render injects PORT dynamically; default 8000 for local/dev.
    port: int = 8000

    @field_validator("chat_rate_limit", "search_rate_limit")
    @classmethod
    def _validate_rate_limit(cls, v: str) -> str:
        """Fail fast at startup on a malformed slowapi limit string.

        Without this, a typo'd CHAT_RATE_LIMIT/SEARCH_RATE_LIMIT passes startup
        and raises ValueError on every request once slowapi tries to parse it.
        Accepts e.g. "20/minute" or "20 per minute" for second|minute|hour|day.
        """
        pattern = r"^\d+\s*(?:/|\s+per\s+)\s*(second|minute|hour|day)s?$"
        if not re.match(pattern, v.strip(), re.IGNORECASE):
            raise ValueError(
                f"invalid rate-limit string {v!r}; expected e.g. '20/minute'"
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# ---------------------------------------------------------------------------
# Rate limiter (shared instance — imported by route modules and main.py)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ---------------------------------------------------------------------------
# Database session factory
# ---------------------------------------------------------------------------

# The engine and session factory are created lazily on first use so that
# importing this module at test time does not require a live database.
_engine = None
_async_session_factory = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily initialise the async engine and session factory."""
    global _engine, _async_session_factory
    if _async_session_factory is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=(settings.app_env == "development"),
            pool_pre_ping=True,
        )
        _async_session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async SQLAlchemy session.

    Usage:
        async def my_route(db: Annotated[AsyncSession, Depends(get_db)]) -> ...:
            ...
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# AI client (Gemini via OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_ai_client() -> AsyncOpenAI:
    """
    FastAPI dependency that returns an AsyncOpenAI client pointed at Gemini.

    Usage:
        async def my_route(
            client: Annotated[AsyncOpenAI, Depends(get_ai_client)]
        ) -> ...:
            ...
    """
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.gemini_api_key, base_url=_GEMINI_BASE_URL)


# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------

_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """
    FastAPI dependency that returns a shared async Redis client.

    The client is created lazily on first call and reused for all subsequent
    requests. Errors during Redis operations should be caught by callers —
    Redis being unavailable must never break the main search flow.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_from_url(get_settings().redis_url, decode_responses=True)
    return _redis_client
