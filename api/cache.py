"""
api/cache.py — Redis caching for search results and parsed intents.
Cache miss always returns None — never raises.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from redis.asyncio import Redis


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
    redis: Redis, query: str, filters: dict, result: dict, ttl: int = 300
) -> None:
    try:
        await redis.setex(
            _search_key(query, filters), ttl, json.dumps(result, ensure_ascii=False)
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
    redis: Redis, message: str, result: dict, ttl: int = 120
) -> None:
    try:
        await redis.setex(
            _intent_key(message), ttl, json.dumps(result, ensure_ascii=False)
        )
    except Exception:
        pass
