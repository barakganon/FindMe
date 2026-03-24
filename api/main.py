"""
api/main.py — FastAPI application factory for BuyMe Smart Search API.

Configures:
    - CORS middleware (origins from CORS_ORIGINS env var)
    - /health endpoint
    - /search router  (api/routes/search.py)
    - /stores router  (api/routes/stores.py)
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import get_settings
from api.routes import search, stores

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

app.include_router(search.router, tags=["Search"])
app.include_router(stores.router, tags=["Stores"])

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
