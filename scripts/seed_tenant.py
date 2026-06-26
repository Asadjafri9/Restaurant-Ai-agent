"""Seed a standalone tenant database (KFC or Kababjees web service)."""

import asyncio
import os

from sqlalchemy import select, text

from app.config.settings import settings
from app.core.security import hash_password
from app.core.tenant_ids import TENANT_IDS
from app.data.restaurants import RESTAURANTS
from app.db.models_tenant import MenuItem, RestaurantProfile, StaffUser
from app.db.standalone import close_standalone_db, get_standalone_session


def _expected_names(slug: str) -> set[str]:
    return {m["item"] for m in RESTAURANTS[slug]["menu"]}


async def _menu_is_correct(slug: str, session) -> bool:
    result = await session.execute(
        select(MenuItem).where(MenuItem.deleted_at.is_(None), MenuItem.is_available.is_(True))
    )
    actual = {i.name for i in result.scalars()}
    return actual == _expected_names(slug)


async def _tenant_db_shared_with_other(slug: str) -> bool:
    """Detect when KFC and Kababjees env URLs point at the same Postgres instance."""
    root = os.path.dirname(os.path.dirname(__file__))
    other = "kfc" if slug == "kababjees" else "kababjees"
    env_path = os.path.join(root, "local", f"{other}.env")
    if not os.path.isfile(env_path):
        return False

    await close_standalone_db()
    session = await get_standalone_session()
    async with session:
        mine = (
            await session.execute(
                text(
                    "SELECT inet_server_addr()::text, pg_postmaster_start_time()::text"
                )
            )
        ).one()

    for line in open(env_path, encoding="utf-8"):
        if line.startswith("DATABASE_URL=") and "CENTRAL" not in line:
            os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip()
            os.environ["TENANT_DATABASE_URL"] = os.environ["DATABASE_URL"]
            break
    from app.config.settings import get_settings

    get_settings.cache_clear()
    await close_standalone_db()
    other_session = await get_standalone_session()
    async with other_session:
        theirs = (
            await other_session.execute(
                text(
                    "SELECT inet_server_addr()::text, pg_postmaster_start_time()::text"
                )
            )
        ).one()

    return mine == theirs


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
        elif profile.name != data["name"]:
            profile.name = data["name"]
            print(f"Fixed profile name for {slug} -> {data['name']}")

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

        shared_db = await _tenant_db_shared_with_other(slug)
        if shared_db:
            print(
                f"WARN: {slug} shares the same Postgres server as the other tenant — "
                "skipping menu_items seed (central catalog is source of truth)."
            )
        else:
            has_items = (
                await session.execute(select(MenuItem).where(MenuItem.deleted_at.is_(None)).limit(1))
            ).scalar_one_or_none()

            if not has_items or not await _menu_is_correct(slug, session):
                if has_items:
                    print(f"Wrong menu detected for {slug} — resetting to correct items")
                    from datetime import datetime, timezone

                    now = datetime.now(timezone.utc)
                    for item in (
                        await session.execute(select(MenuItem).where(MenuItem.deleted_at.is_(None)))
                    ).scalars():
                        item.deleted_at = now
                        item.is_available = False
                for i, entry in enumerate(data["menu"], start=1):
                    session.add(
                        MenuItem(
                            name=entry["item"],
                            price=entry["price_pkr"],
                            is_available=True,
                            description=f"{data['name']} menu item",
                            sort_order=i,
                        )
                    )
                print(f"Seeded menu for {slug}")

        await session.commit()

    tid = TENANT_IDS.get(slug)
    print(f"Tenant slug={slug} tenant_id={tid}")

    if settings.database_url_central:
        from scripts.seed_central_catalog import seed_central_for_slug

        await seed_central_for_slug(slug)


if __name__ == "__main__":
    asyncio.run(seed_tenant())
