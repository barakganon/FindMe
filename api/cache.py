"""
api/cache.py — Redis caching for search results and parsed intents.
Cache miss always returns None — never raises.

TTL defaults are resolved from Settings (env-driven) when the caller
does not supply an explicit value.  Callers may still pass a ttl kwarg
to override — useful for tests and one-off overrides.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from redis.asyncio import Redis

from api.dependencies import get_settings


def _search_key(query: str, filters: dict) -> str:
    raw = query + json.dumps(filters, sort_keys=True, ensure_ascii=False)
    return "search:" + hashlib.sha256(raw.encode()).hexdigest()


def _intent_key(message: str) -> str:
    return "intent:" + hashlib.sha256(message.encode()).hexdigest()


async def get_search_cache(redis: Redis, query: str, filters: dict) -> dict | None:
    try:
        val = await redis.get(_search_key(query, filters))
        return json.loads(val) if val else None
    except Exception:
        return None


async def set_search_cache(
    redis: Redis,
    query: str,
    filters: dict,
    result: dict,
    ttl: int | None = None,
) -> None:
    resolved_ttl = ttl if ttl is not None else get_settings().search_cache_ttl
    try:
        await redis.setex(
            _search_key(query, filters), resolved_ttl, json.dumps(result, ensure_ascii=False)
        )
    except Exception:
        pass


async def get_intent_cache(redis: Redis, message: str) -> dict | None:
    try:
        val = await redis.get(_intent_key(message))
        return json.loads(val) if val else None
    except Exception:
        return None


async def set_intent_cache(
    redis: Redis,
    message: str,
    result: dict,
    ttl: int | None = None,
) -> None:
    resolved_ttl = ttl if ttl is not None else get_settings().intent_cache_ttl
    try:
        await redis.setex(
            _intent_key(message), resolved_ttl, json.dumps(result, ensure_ascii=False)
        )
    except Exception:
        pass
