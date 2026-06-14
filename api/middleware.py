"""
api/middleware.py — custom Starlette middleware for FindMe.

BodySizeLimitMiddleware
    Rejects requests whose body exceeds a byte ceiling before the route handler
    (and any LLM/DB work) runs. Guards the "can a stranger break it?" surface:
    an attacker POSTing a multi-megabyte JSON body can no longer expand the LLM
    context, blow up memory, or run up cost. Returns HTTP 413.

    Enforcement is via the Content-Length header, checked before the body is
    read or the route handler runs. Real clients (browsers, httpx, curl, the
    React frontend) always send Content-Length on a JSON POST, so this rejects
    the realistic attack — a multi-megabyte JSON body — at near-zero cost.

    NOTE: we deliberately do NOT buffer the request stream to count bytes for
    chunked/header-less requests. Reassigning ``request._receive`` under
    Starlette's BaseHTTPMiddleware does not propagate the buffered body to the
    downstream handler, which breaks body parsing (every route 422s). uvicorn's
    own framing limits backstop the chunked edge case; the header check is the
    practical guard.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than ``max_bytes`` via Content-Length."""

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
            except ValueError:
                # Malformed header — let it through; downstream parsing handles it.
                pass
        return await call_next(request)
