"""
main.py — BuyMe Smart Search entry point.

Starts the FastAPI application with uvicorn.

Usage:
    python main.py                     # default: 0.0.0.0:8000
    APP_PORT=9000 python main.py       # custom port
    APP_ENV=production python main.py  # production (1 worker, no reload)

Or via uvicorn directly:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os

import uvicorn

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Start the uvicorn server with settings from environment variables."""
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    app_env = os.getenv("APP_ENV", "development")
    reload = app_env == "development"
    workers = 1 if reload else int(os.getenv("WEB_CONCURRENCY", "4"))

    logger.info(
        "Starting BuyMe Smart Search API — env=%s host=%s port=%d reload=%s workers=%d",
        app_env,
        host,
        port,
        reload,
        workers,
    )

    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
