import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from starlette.middleware.gzip import GZipMiddleware

from app.config.settings import settings
from app.core.errors import AppError, error_response
from app.core.logging import RequestIdFilter, new_request_id
from app.db.central import check_central_db, close_central_db
from app.db.redis_client import check_redis, close_redis
from app.core.rate_limit import RateLimitMiddleware
from app.routes.webhook import router as webhook_router

logger = logging.getLogger(__name__)

try:
    from app.routes.auth import router as auth_router
except ImportError:
    auth_router = None
try:
    from app.routes.admin import router as admin_router
except ImportError:
    admin_router = None
try:
    from app.routes.menu import router as menu_router
except ImportError:
    menu_router = None
try:
    from app.routes.orders import router as orders_router
except ImportError:
    orders_router = None
try:
    from app.routes.analytics import router as analytics_router
except ImportError:
    analytics_router = None
try:
    from app.routes.ws import router as ws_router
except ImportError:
    ws_router = None


async def check_whatsapp_token() -> bool:
    if not settings.whatsapp_access_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/me",
                params={"access_token": settings.whatsapp_access_token},
            )
            return response.is_success
    except Exception:
        logger.exception("WhatsApp token check failed")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    logging.getLogger().addFilter(RequestIdFilter())
    logger.info("Starting service_mode=%s", settings.service_mode)
    # Warm DB/Redis pools so first dashboard request is not slow
    try:
        if settings.is_admin_service or settings.is_agent_service:
            await check_central_db()
        if settings.is_standalone_tenant:
            from app.db.standalone import check_standalone_db

            await check_standalone_db()
        if settings.redis_url:
            await check_redis()
    except Exception:
        logger.debug("Pool warmup skipped", exc_info=True)
    yield
    if settings.is_admin_service or settings.is_agent_service:
        await close_central_db()
    if settings.is_standalone_tenant:
        from app.db.standalone import close_standalone_db

        await close_standalone_db()
    await close_redis()


app = FastAPI(title=f"Restaurant OS ({settings.service_mode})", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
PORTALS_DIR = STATIC_DIR / "portals"
if STATIC_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(STATIC_DIR)), name="static")

# --- API routers by service mode ---
if auth_router:
    app.include_router(auth_router, prefix="/api/v1")

if settings.is_agent_service:
    app.include_router(webhook_router)

if settings.is_admin_service and admin_router:
    app.include_router(admin_router, prefix="/api/v1")

if settings.is_tenant_service:
    if menu_router:
        app.include_router(menu_router, prefix="/api/v1")
    if orders_router:
        app.include_router(orders_router, prefix="/api/v1")
    if analytics_router:
        app.include_router(analytics_router, prefix="/api/v1")
    if ws_router:
        app.include_router(ws_router)


@app.middleware("http")
async def static_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or new_request_id()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    except Exception:
        logger.exception("Unhandled error [%s]", rid)
        return JSONResponse(
            status_code=500,
            content=error_response("internal_error", "Internal server error", rid),
        )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    rid = request.headers.get("X-Request-ID", "")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.code, exc.message, rid),
    )


# --- UI routes by service mode ---
if settings.service_mode == "admin":

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(str(PORTALS_DIR / "admin.html"))

elif settings.service_mode == "kfc":

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(str(PORTALS_DIR / "kfc.html"))

elif settings.service_mode == "kababjees":

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(str(PORTALS_DIR / "kababjees.html"))

elif settings.service_mode == "agent":

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "agent.html"))

else:

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "landing.html"))

    @app.get("/admin")
    async def admin_portal() -> FileResponse:
        return FileResponse(str(PORTALS_DIR / "admin.html"))

    @app.get("/kfc")
    async def kfc_portal() -> FileResponse:
        return FileResponse(str(PORTALS_DIR / "kfc.html"))

    @app.get("/kababjees")
    async def kababjees_portal() -> FileResponse:
        return FileResponse(str(PORTALS_DIR / "kababjees.html"))

    @app.get("/dashboard")
    async def dashboard_redirect():
        return RedirectResponse(url="/", status_code=302)


@app.get("/api/status")
async def api_status() -> dict:
    return {"status": "running", "service_mode": settings.service_mode}


@app.get("/health")
async def health() -> dict:
    if settings.is_standalone_tenant:
        from app.db.standalone import check_standalone_db

        db_ok = await check_standalone_db()
    elif settings.is_admin_service or settings.is_agent_service:
        db_ok = await check_central_db() if settings.database_url_central else False
    else:
        db_ok = False
    redis_ok = await check_redis() if settings.redis_url else False
    wa_ok = await check_whatsapp_token() if settings.is_agent_service else None
    healthy = db_ok and (redis_ok if settings.redis_url else True)
    out = {
        "status": "healthy" if healthy else "degraded",
        "service_mode": settings.service_mode,
        "database": db_ok,
        "redis": redis_ok,
    }
    if wa_ok is not None:
        out["whatsapp_token_valid"] = wa_ok
    return out
