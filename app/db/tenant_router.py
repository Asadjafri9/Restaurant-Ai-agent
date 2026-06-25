import logging
import secrets
import subprocess
import uuid
from collections import OrderedDict
from urllib.parse import quote_plus

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.db.central import get_central_session
from app.db.models_central import Tenant, TenantConnection
from app.db.models_tenant import RestaurantProfile

logger = logging.getLogger(__name__)

MAX_ENGINES = 50
POOL_SIZE = 3


class LRUEngineCache:
    def __init__(self, max_size: int = MAX_ENGINES) -> None:
        self._cache: OrderedDict[uuid.UUID, AsyncEngine] = OrderedDict()
        self._max_size = max_size

    def get(self, tenant_id: uuid.UUID) -> AsyncEngine | None:
        if tenant_id in self._cache:
            self._cache.move_to_end(tenant_id)
            return self._cache[tenant_id]
        return None

    def put(self, tenant_id: uuid.UUID, engine: AsyncEngine) -> None:
        if tenant_id in self._cache:
            self._cache.move_to_end(tenant_id)
        self._cache[tenant_id] = engine
        while len(self._cache) > self._max_size:
            old_id, old_engine = self._cache.popitem(last=False)
            logger.info("Evicting tenant engine cache for %s", old_id)

    async def dispose_all(self) -> None:
        for engine in self._cache.values():
            await engine.dispose()
        self._cache.clear()


_engine_cache = LRUEngineCache()


def _build_tenant_url(conn: TenantConnection, password: str) -> str:
    user = quote_plus(conn.db_role)
    pwd = quote_plus(password)
    host = conn.db_host
    port = conn.db_port
    db = conn.db_name
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"


async def get_tenant_engine(tenant_id: uuid.UUID) -> AsyncEngine:
    cached = _engine_cache.get(tenant_id)
    if cached:
        return cached

    async for session in get_central_session():
        result = await session.execute(
            select(TenantConnection).where(TenantConnection.tenant_id == tenant_id)
        )
        conn = result.scalar_one_or_none()
        if not conn:
            raise ValueError(f"No connection for tenant {tenant_id}")
        password = decrypt_secret(conn.db_password_enc)
        url = _build_tenant_url(conn, password)
        engine = create_async_engine(url, pool_pre_ping=True, pool_size=POOL_SIZE, max_overflow=2)
        _engine_cache.put(tenant_id, engine)
        return engine
    raise ValueError(f"Tenant {tenant_id} not found")


async def get_tenant_session(tenant_id: uuid.UUID) -> AsyncSession:
    from app.config.settings import settings

    if settings.is_standalone_tenant:
        from app.db.standalone import get_standalone_session

        return await get_standalone_session()

    engine = await get_tenant_engine(tenant_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory()


async def get_connection_for_tenant(tenant_id: uuid.UUID) -> TenantConnection:
    async for session in get_central_session():
        result = await session.execute(
            select(TenantConnection).where(TenantConnection.tenant_id == tenant_id)
        )
        conn = result.scalar_one_or_none()
        if not conn:
            raise ValueError(f"No connection for tenant {tenant_id}")
        return conn
    raise ValueError(f"Tenant {tenant_id} not found")


def _safe_slug(slug: str) -> str:
    import re

    if not re.match(r"^[a-z0-9-]+$", slug):
        raise ValueError("Invalid slug")
    return slug


async def provision_tenant_db(
    tenant_id: uuid.UUID,
    slug: str,
    name: str,
    owner_email: str,
) -> None:
    slug = _safe_slug(slug)
    role_name = f"tenant_{slug.replace('-', '_')}"
    db_name = f"tdb_{slug.replace('-', '_')}"
    password = secrets.token_urlsafe(32)

    admin_url = settings.tenant_db_admin_url
    if not admin_url:
        raise RuntimeError("TENANT_DB_ADMIN_URL not configured")

    sync_url = admin_url.replace("postgresql+asyncpg://", "postgresql://")

    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = psycopg2.connect(sync_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    try:
        cur.execute(f'CREATE ROLE "{role_name}" LOGIN PASSWORD %s', (password,))
    except Exception as e:
        if "already exists" not in str(e):
            raise
    try:
        cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{role_name}"')
    except Exception as e:
        if "already exists" not in str(e):
            raise
    cur.execute(f'REVOKE CONNECT ON DATABASE "{db_name}" FROM PUBLIC')
    cur.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO "{role_name}"')
    cur.close()
    conn.close()

    tenant_url = (
        f"postgresql://{quote_plus(role_name)}:{quote_plus(password)}"
        f"@{settings.tenant_db_host}:{settings.tenant_db_port}/{db_name}"
    )
    import os

    env = os.environ.copy()
    env["TENANT_DATABASE_URL"] = tenant_url
    subprocess.run(
        ["alembic", "-c", "migrations/tenant/alembic.ini", "upgrade", "head"],
        check=True,
        env=env,
    )

    engine = create_async_engine(
        tenant_url.replace("postgresql://", "postgresql+asyncpg://"),
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        profile = RestaurantProfile(name=name, owner_email=owner_email, currency="PKR")
        session.add(profile)
        await session.commit()
    await engine.dispose()

    async for session in get_central_session():
        enc = encrypt_secret(password)
        tc = TenantConnection(
            tenant_id=tenant_id,
            db_host=settings.tenant_db_host,
            db_port=settings.tenant_db_port,
            db_name=db_name,
            db_role=role_name,
            db_password_enc=enc,
        )
        session.add(tc)
        tenant = await session.get(Tenant, tenant_id)
        if tenant:
            tenant.status = "active"
        await session.commit()

    logger.info("Provisioned tenant %s db %s", slug, db_name)
