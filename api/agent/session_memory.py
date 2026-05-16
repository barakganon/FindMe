"""api/agent/session_memory.py — Redis-backed per-session state for v2 chat.

W3 deliverable. Stores the last turn's tray (products + stores) and metadata
so the agent's `recall_history` tool can resolve references like "the first
one" / "like last week" without the client passing full history.

Session ID derivation:
  - Logged-in users: `user.id` (canonical, overrides X-Session-ID header)
  - Anonymous users: `X-Session-ID` header (frontend generates a UUID per
    device and persists in localStorage)
  - No header on anonymous: memory is disabled for that turn (single-turn
    fallback — degraded but functional, no crash)

Graceful degradation: any Redis error is logged and treated as "no memory" —
chat never fails because Redis is unavailable.

TTL: 2 hours, refreshed on every write (per W3 spec).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "findme:agent:session:"
_TTL_SECONDS = 60 * 60 * 2  # 2 hours per W3 spec
_MAX_TRAY_ITEMS = 20  # cap per turn — never accumulates across turns


@dataclass
class SessionState:
    """Per-session state persisted in Redis between agent turns."""

    last_product_results: list[dict] = field(default_factory=list)
    last_store_results: list[dict] = field(default_factory=list)
    last_user_message: str = ""
    last_assistant_message: str = ""
    updated_at: str = ""  # ISO 8601 UTC

    @classmethod
    def empty(cls) -> "SessionState":
        return cls()

    def is_empty(self) -> bool:
        return not (self.last_product_results or self.last_store_results)


def derive_session_id(
    current_user: Optional[Any], session_header: Optional[str]
) -> Optional[str]:
    """Pick the session key: user.id for logged-in, else the header UUID, else None."""
    if current_user is not None and getattr(current_user, "id", None):
        return f"user:{current_user.id}"
    if session_header:
        return f"anon:{session_header}"
    return None


def _redis_key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


async def load_session_state(
    redis: Optional[Redis], session_id: Optional[str]
) -> SessionState:
    """Fetch session state. Returns empty state if no session or Redis errors."""
    if not session_id or redis is None:
        return SessionState.empty()
    try:
        raw = await redis.get(_redis_key(session_id))
    except Exception as exc:  # noqa: BLE001 — Redis-down must never break chat
        logger.warning("session_memory: load failed (%s) — degrading to empty state", exc)
        return SessionState.empty()
    if not raw:
        return SessionState.empty()
    try:
        data = json.loads(raw)
        return SessionState(
            last_product_results=data.get("last_product_results") or [],
            last_store_results=data.get("last_store_results") or [],
            last_user_message=data.get("last_user_message") or "",
            last_assistant_message=data.get("last_assistant_message") or "",
            updated_at=data.get("updated_at") or "",
        )
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("session_memory: corrupt state for %s (%s) — resetting", session_id, exc)
        return SessionState.empty()


async def save_session_state(
    redis: Optional[Redis],
    session_id: Optional[str],
    *,
    product_results: list[Any],
    store_results: list[Any],
    user_message: str,
    assistant_message: str,
) -> None:
    """Persist this turn's tray + messages. No-op if no session or Redis errors."""
    if not session_id or redis is None:
        return
    state = {
        "last_product_results": [_serialize_item(r) for r in (product_results or [])][:_MAX_TRAY_ITEMS],
        "last_store_results": [_serialize_item(r) for r in (store_results or [])][:_MAX_TRAY_ITEMS],
        "last_user_message": user_message or "",
        "last_assistant_message": assistant_message or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = json.dumps(state, ensure_ascii=False, default=str)
    try:
        await redis.setex(_redis_key(session_id), _TTL_SECONDS, payload)
    except Exception as exc:  # noqa: BLE001 — never let memory failure surface
        logger.warning("session_memory: save failed (%s) — turn proceeds without persistence", exc)


async def clear_session_state(redis: Optional[Redis], session_id: Optional[str]) -> None:
    """Delete a session's stored state. Used by tests + a future explicit reset."""
    if not session_id or redis is None:
        return
    try:
        await redis.delete(_redis_key(session_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("session_memory: delete failed (%s)", exc)


def _serialize_item(item: Any) -> dict:
    """Coerce a Pydantic ProductResult/StoreResult (or raw dict) to a JSON-safe dict."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    # Last-ditch: best-effort field extraction
    return {k: getattr(item, k, None) for k in ("id", "name_he", "canonical_name", "price", "brand")}
