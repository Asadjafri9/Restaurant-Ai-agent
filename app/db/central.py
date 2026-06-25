from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine():
    global _engine, _session_factory
    if _engine is None:
        if not settings.async_database_url_central:
            raise RuntimeError("DATABASE_URL_CENTRAL not configured")
        _engine = create_async_engine(
            settings.async_database_url_central,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _session_factory


async def get_central_session() -> AsyncGenerator[AsyncSession, None]:
    _, factory = _get_engine()
    async with factory() as session:
        yield session


async def check_central_db() -> bool:
    try:
        from sqlalchemy import text

        engine, _ = _get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_central_db() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
