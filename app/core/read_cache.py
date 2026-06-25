"""Short-lived Redis cache for read-heavy API endpoints."""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.config.settings import settings
from app.db.redis_client import redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

DEFAULT_TTL = 15


async def cached_json(key: str, ttl: int, loader: Callable[[], Awaitable[Any]]) -> Any:
    if not settings.redis_url:
        return await loader()
    try:
        hit = await redis_get_json(key)
        if hit is not None and "data" in hit:
            return hit["data"]
    except Exception:
        logger.debug("cache read miss for %s", key)
    data = await loader()
    try:
        await redis_set_json(key, {"data": data}, ttl_seconds=ttl)
    except Exception:
        logger.debug("cache write failed for %s", key)
    return data


async def invalidate_prefix(prefix: str) -> None:
    if not settings.redis_url:
        return
    try:
        from app.db.redis_client import get_redis

        r = get_redis()
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=f"{prefix}*", count=50)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        logger.debug("cache invalidate failed for %s", prefix)


def cache_key(*parts: str) -> str:
    raw = ":".join(parts)
    if len(raw) > 120:
        return "api:" + hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"api:{raw}"
