import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings
from app.db.redis_client import get_redis

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({"/webhook", "/health", "/"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.rpm = requests_per_minute
        # Disable entirely in dev / when no Redis — avoids per-request work.
        self.enabled = settings.environment != "development" and bool(settings.redis_url)

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        path = request.url.path
        if path in _SKIP_PATHS or path.startswith("/app/"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        key = f"rl:{client}:{path}"
        try:
            r = get_redis()
            # incr + expire in a single round trip
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, 60)
            count, _ = await pipe.execute()
            if count > self.rpm:
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=429, content={"error": "Rate limit exceeded"})
        except Exception:
            pass
        return await call_next(request)
