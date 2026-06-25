"""Seed a standalone tenant database (KFC or Kababjees web service)."""

import asyncio
import os

from sqlalchemy import select

from app.config.settings import settings
from app.core.security import hash_password
from app.core.tenant_ids import TENANT_IDS
from app.data.restaurants import RESTAURANTS
from app.db.models_tenant import MenuItem, RestaurantProfile, StaffUser
from app.db.standalone import get_standalone_session


async def seed_tenant() -> None:
    slug = settings.tenant_slug or os.environ.get("SERVICE_MODE", "")
    if slug not in RESTAURANTS:
        raise RuntimeError(f"Unknown tenant slug: {slug}")
    data = RESTAURANTS[slug]
    owner_email = f"owner@{slug}.local"

    session = await get_standalone_session()
    async with session:
        profile = (await session.execute(select(RestaurantProfile))).scalar_one_or_none()
        if not profile:
            session.add(
                RestaurantProfile(
                    name=data["name"],
                    owner_email=owner_email,
                    currency="PKR",
                )
            )
            print(f"Seeded profile for {slug}")

        staff = await session.execute(select(StaffUser).where(StaffUser.email == owner_email))
        if not staff.scalar_one_or_none():
            session.add(
                StaffUser(
                    email=owner_email,
                    password_hash=hash_password("owner123"),
                    role="owner",
                    is_active=True,
                )
            )
            print(f"Seeded staff user for {slug}")

        existing_items = (await session.execute(select(MenuItem).limit(1))).scalar_one_or_none()
        if not existing_items:
            for item in data["menu"]:
                session.add(
                    MenuItem(
                        name=item["item"],
                        price=item["price_pkr"],
                        is_available=True,
                        description=f"{data['name']} menu item",
                    )
                )
            print(f"Seeded menu for {slug}")

        await session.commit()

    tid = TENANT_IDS.get(slug)
    print(f"Tenant slug={slug} tenant_id={tid}")


if __name__ == "__main__":
    asyncio.run(seed_tenant())
