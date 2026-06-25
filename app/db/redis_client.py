import logging
from typing import Any

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL not configured")
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def check_redis() -> bool:
    try:
        if not settings.redis_url:
            return False
        r = get_redis()
        await r.ping()
        return True
    except Exception:
        logger.exception("Redis health check failed")
        return False


async def close_redis() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def redis_set_json(key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
    import json

    r = get_redis()
    data = json.dumps(value, default=str)
    if ttl_seconds:
        await r.setex(key, ttl_seconds, data)
    else:
        await r.set(key, data)


async def redis_get_json(key: str) -> dict[str, Any] | None:
    import json

    r = get_redis()
    data = await r.get(key)
    if not data:
        return None
    return json.loads(data)


async def redis_dedupe(key: str, ttl_seconds: int) -> bool:
    """Return True if key is new (not duplicate), False if already seen."""
    r = get_redis()
    was_set = await r.set(key, "1", nx=True, ex=ttl_seconds)
    return bool(was_set)
