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

from openai import AsyncOpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict
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

    # Runtime environment
    app_env: str = "development"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


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
