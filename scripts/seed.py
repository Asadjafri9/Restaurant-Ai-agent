"""Seed agent central registry — links to external tenant DBs when configured."""

import asyncio
import os
import uuid
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.crypto import encrypt_secret
from app.core.security import hash_password
from app.core.tenant_ids import TENANT_IDS
from app.data.restaurants import RESTAURANTS
from app.db.central import get_central_session
from app.db.models_central import Tenant, TenantConnection, User
from app.db.tenant_router import provision_tenant_db


def _external_db_url(slug: str) -> str | None:
    key = f"DATABASE_URL_{slug.upper()}"
    return os.environ.get(key) or os.environ.get(f"DATABASE_URL_{slug}")


async def _register_external_db(tenant_id: uuid.UUID, slug: str, db_url: str) -> None:
    parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://"))
    password = parsed.password or ""
    role = parsed.username or ""
    db_name = (parsed.path or "").lstrip("/")
    host = parsed.hostname or ""
    port = parsed.port or 5432

    async for session in get_central_session():
        existing = await session.execute(
            select(TenantConnection).where(TenantConnection.tenant_id == tenant_id)
        )
        if existing.scalar_one_or_none():
            return
        session.add(
            TenantConnection(
                tenant_id=tenant_id,
                db_host=host,
                db_port=port,
                db_name=db_name,
                db_role=role,
                db_password_enc=encrypt_secret(password),
            )
        )
        tenant = await session.get(Tenant, tenant_id)
        if tenant:
            tenant.status = "active"
        await session.commit()
        print(f"Registered external DB for {slug} -> {host}/{db_name}")


async def seed() -> None:
    async for session in get_central_session():
        admin = await session.execute(select(User).where(User.email == "admin@platform.local"))
        if not admin.scalar_one_or_none():
            session.add(
                User(
                    email="admin@platform.local",
                    password_hash=hash_password("admin123"),
                    role="platform_admin",
                    tenant_id=None,
                )
            )
        await session.commit()

    for slug, data in RESTAURANTS.items():
        tenant_id = TENANT_IDS[slug]
        external_url = _external_db_url(slug)

        async for session in get_central_session():
            existing = await session.execute(select(Tenant).where(Tenant.slug == slug))
            tenant = existing.scalar_one_or_none()
            if not tenant:
                tenant = Tenant(
                    id=tenant_id,
                    slug=slug,
                    name=data["name"],
                    owner_email=f"owner@{slug}.local",
                    status="active" if external_url else "provisioning",
                    plan="pro",
                )
                session.add(tenant)
                await session.commit()
                await session.refresh(tenant)
            elif tenant.id != tenant_id:
                pass  # keep existing id if already created

            owner_email = f"owner@{slug}.local"
            user = await session.execute(select(User).where(User.email == owner_email))
            if not user.scalar_one_or_none():
                session.add(
                    User(
                        email=owner_email,
                        password_hash=hash_password("owner123"),
                        role="owner",
                        tenant_id=tenant.id,
                    )
                )

            await session.commit()

        if external_url:
            await _register_external_db(tenant_id, slug, external_url)
            continue

        conn = None
        async for session in get_central_session():
            conn = await session.execute(
                select(TenantConnection).where(TenantConnection.tenant_id == tenant_id)
            )
            conn = conn.scalar_one_or_none()
        if not conn:
            await provision_tenant_db(
                tenant_id,
                slug,
                data["name"],
                f"owner@{slug}.local",
            )
        print(f"Seeded tenant: {slug}")


if __name__ == "__main__":
    asyncio.run(seed())
