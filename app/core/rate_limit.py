import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.db.redis_client import get_redis

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.rpm = requests_per_minute

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/webhook", "/health", "/"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        key = f"rl:{client}:{request.url.path}"
        try:
            r = get_redis()
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, 60)
            if count > self.rpm:
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=429, content={"error": "Rate limit exceeded"})
        except Exception:
            pass
        return await call_next(request)
