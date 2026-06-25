"""Seed platform admin (admin web service only)."""

import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.central import get_central_session
from app.db.models_central import User


async def seed_admin() -> None:
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
            print("Seeded platform admin")
        else:
            print("Platform admin already exists")


if __name__ == "__main__":
    asyncio.run(seed_admin())
