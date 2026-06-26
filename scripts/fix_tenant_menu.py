"""Reset a tenant's menu to the correct default for its slug and sync central catalog."""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config.settings import get_settings
from app.core.tenant_ids import TENANT_IDS
from app.data.restaurants import RESTAURANTS
from app.db.models_tenant import MenuItem, RestaurantProfile
from app.db.standalone import close_standalone_db, get_standalone_session


def _load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        key, _, val = line.partition("=")
        os.environ[key.strip()] = val.strip()


async def reset_menu(slug: str) -> None:
    if slug not in RESTAURANTS:
        raise RuntimeError(f"Unknown slug: {slug}")

    data = RESTAURANTS[slug]

    # Always rebuild central catalog
    from scripts.seed_central_catalog import seed_central_for_slug

    await seed_central_for_slug(slug)

    # Only touch tenant menu_items when this slug has its own Postgres instance.
    root = Path(__file__).resolve().parent.parent
    other = "kfc" if slug == "kababjees" else "kababjees"
    other_env = root / "local" / f"{other}.env"
    shared = False
    if other_env.exists():
        from sqlalchemy import text

        session = await get_standalone_session()
        async with session:
            mine = (
                await session.execute(
                    text("SELECT inet_server_addr()::text, pg_postmaster_start_time()::text")
                )
            ).one()
        await close_standalone_db()
        _load_env_file(other_env)
        os.environ["SERVICE_MODE"] = other
        get_settings.cache_clear()
        session = await get_standalone_session()
        async with session:
            theirs = (
                await session.execute(
                    text("SELECT inet_server_addr()::text, pg_postmaster_start_time()::text")
                )
            ).one()
        shared = mine == theirs
        await close_standalone_db()
        _load_env_file(root / "local" / f"{slug}.env")
        os.environ["SERVICE_MODE"] = slug
        os.environ["TENANT_DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
        get_settings.cache_clear()

    if shared:
        print(
            f"Reset {slug} central catalog ({len(data['menu'])} items). "
            "Skipped tenant DB — shared Postgres with other restaurant."
        )
        return

    session = await get_standalone_session()
    async with session:
        profile = (await session.execute(select(RestaurantProfile))).scalar_one_or_none()
        if profile:
            profile.name = data["name"]
        else:
            session.add(
                RestaurantProfile(
                    name=data["name"],
                    owner_email=f"owner@{slug}.local",
                    currency="PKR",
                )
            )

        existing = (await session.execute(select(MenuItem).where(MenuItem.deleted_at.is_(None)))).scalars().all()
        now = datetime.now(timezone.utc)
        for item in existing:
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
        await session.commit()

    print(f"Reset {slug} menu ({len(data['menu'])} items) in tenant DB and central catalog.")


async def main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else "kababjees"
    root = Path(__file__).resolve().parent.parent
    env_file = root / "local" / f"{slug}.env"
    if not env_file.exists():
        print(f"Missing {env_file}")
        sys.exit(1)
    await close_standalone_db()
    _load_env_file(env_file)
    os.environ["SERVICE_MODE"] = slug
    os.environ["TENANT_ID"] = str(TENANT_IDS[slug])
    os.environ["TENANT_DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    get_settings.cache_clear()
    await reset_menu(slug)


if __name__ == "__main__":
    asyncio.run(main())
