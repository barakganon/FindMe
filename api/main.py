"""
api/main.py — FastAPI application factory for BuyMe Smart Search API.

Configures:
    - CORS middleware (origins from CORS_ORIGINS env var)
    - Rate limiting via slowapi
    - Security headers middleware
    - /health endpoint
    - /search router  (api/routes/search.py)
    - /stores router  (api/routes/stores.py)
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.dependencies import get_settings, limiter
from api.middleware import BodySizeLimitMiddleware
from api.routes import admin, auth as auth_module, chat, chat_v2, chat_v2_stream, search, stores
from api.routes import users as users_module

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

_VERSION = "0.1.0"

app = FastAPI(
    title="BuyMe Smart Search API",
    version=_VERSION,
    description=(
        "Find products available at BuyMe partner stores in Israel. "
        "Submit any product URL and receive matching store listings with prices."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# Attach limiter state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# Request body-size limit (abuse-surface guard — rejects oversized bodies 413)
# ---------------------------------------------------------------------------

app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=get_settings().max_request_body_bytes,
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

settings = get_settings()

# Parse CORS_ORIGINS: comma-separated string → list.
# Default "*" (allow all) is fine for local development.
_cors_origins_raw: str = settings.cors_origins
if _cors_origins_raw.strip() == "*":
    _allowed_origins: list[str] = ["*"]
else:
    _allowed_origins = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(search.router, prefix="/api", tags=["Search"])
app.include_router(stores.router, prefix="/api", tags=["Stores"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(chat_v2.router, prefix="/api", tags=["Chat v2 (agentic)"])
app.include_router(chat_v2_stream.router, prefix="/api", tags=["Chat v2 (streaming)"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])
app.include_router(auth_module.router, prefix="/api", tags=["Auth"])
app.include_router(users_module.router, prefix="/api", tags=["Users"])

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """
    Lightweight liveness probe.

    Returns ``{"status": "ok", "version": "<version>"}`` with HTTP 200.
    No database round-trip — purely for load balancer / Kubernetes probes.
    """
    return {"status": "ok", "version": _VERSION}
