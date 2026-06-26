"""Short-lived cache for read-heavy API endpoints.

In production this is backed by Redis. In local dev (DB/Redis behind a
high-latency proxy) it uses a zero-latency in-process memory cache instead,
since a Redis round trip costs ~160ms but the data is tiny.
"""

import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config.settings import settings
from app.db.redis_client import redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

DEFAULT_TTL = 15

# In-process cache: key -> (expires_at_epoch, data)
_mem: dict[str, tuple[float, Any]] = {}


def _mem_get(key: str) -> Any | None:
    entry = _mem.get(key)
    if not entry:
        return None
    expires_at, data = entry
    if expires_at < time.monotonic():
        _mem.pop(key, None)
        return None
    return data


def _mem_set(key: str, data: Any, ttl: int) -> None:
    _mem[key] = (time.monotonic() + ttl, data)


def _mem_invalidate(prefix: str) -> None:
    for k in [k for k in _mem if k.startswith(prefix)]:
        _mem.pop(k, None)


async def cached_json(key: str, ttl: int, loader: Callable[[], Awaitable[Any]]) -> Any:
    if settings.use_read_cache:
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

    # Dev / no-Redis: in-process memory cache (no network round trip).
    if ttl > 0:
        cached = _mem_get(key)
        if cached is not None:
            return cached
    data = await loader()
    if ttl > 0:
        _mem_set(key, data, ttl)
    return data


async def invalidate_prefix(prefix: str) -> None:
    _mem_invalidate(prefix)
    if not settings.use_read_cache:
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
