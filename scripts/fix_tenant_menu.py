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
from app.services.menu_sync import sync_tenant_menu_to_central


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
    tenant_id = TENANT_IDS[slug]
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

    count = await sync_tenant_menu_to_central(tenant_id)
    print(f"Reset {slug} menu ({len(data['menu'])} items) and synced {count} to central catalog.")


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
