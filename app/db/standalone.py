"""Direct connection to a single tenant database (standalone tenant web service)."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        url = settings.async_database_url_tenant
        if not url:
            raise RuntimeError("DATABASE_URL / TENANT_DATABASE_URL not configured")
        _engine = create_async_engine(
            url,
            pool_pre_ping=settings.db_pool_pre_ping,
            pool_size=10,
            max_overflow=10,
            pool_recycle=300,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def get_standalone_session() -> AsyncSession:
    if _session_factory is None:
        _get_engine()
    assert _session_factory is not None
    return _session_factory()


async def standalone_session() -> AsyncGenerator[AsyncSession, None]:
    session = await get_standalone_session()
    try:
        yield session
    finally:
        await session.close()


async def check_standalone_db() -> bool:
    try:
        from sqlalchemy import text

        session = await get_standalone_session()
        async with session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_standalone_db() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None
