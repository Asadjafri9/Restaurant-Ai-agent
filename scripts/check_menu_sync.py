"""Compare tenant menu_items vs central catalog_items for a slug."""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.tenant_ids import TENANT_IDS
from app.db.central import get_central_session
from app.db.models_central import CatalogItem
from app.db.models_tenant import MenuItem
from app.db.standalone import close_standalone_db, get_standalone_session


def _load_env(slug: str) -> None:
    root = Path(__file__).resolve().parent.parent
    env_file = root / "local" / f"{slug}.env"
    if not env_file.exists():
        raise RuntimeError(f"Missing {env_file}")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        key, _, val = line.partition("=")
        os.environ[key.strip()] = val.strip()
    os.environ["SERVICE_MODE"] = slug
    os.environ["TENANT_ID"] = str(TENANT_IDS[slug])
    os.environ["TENANT_DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    from app.config.settings import get_settings

    get_settings.cache_clear()


async def main(slug: str) -> None:
    await close_standalone_db()
    _load_env(slug)
    tenant_id = TENANT_IDS[slug]

    session = await get_standalone_session()
    async with session:
        tenant_items = (
            await session.execute(
                select(MenuItem)
                .where(MenuItem.deleted_at.is_(None), MenuItem.is_available.is_(True))
                .order_by(MenuItem.sort_order)
            )
        ).scalars().all()

    print(f"\n=== {slug} tenant DB ({len(tenant_items)} items) @ {os.environ.get('DATABASE_URL', '')[:50]}... ===")
    for i in tenant_items:
        print(f"  {i.name} — Rs {i.price}  id={i.id}")

    async for cs in get_central_session():
        central_items = (
            await cs.execute(
                select(CatalogItem)
                .where(CatalogItem.tenant_id == tenant_id, CatalogItem.is_available.is_(True))
                .order_by(CatalogItem.sort_order)
            )
        ).scalars().all()

    print(f"\n=== central catalog for {slug} ({len(central_items)} items) ===")
    for i in central_items:
        print(f"  {i.name} — Rs {i.price}  tenant_item_id={i.tenant_item_id}")

    tenant_names = {i.name for i in tenant_items}
    central_names = {i.name for i in central_items}
    missing = tenant_names - central_names
    stale = central_names - tenant_names
    if missing:
        print(f"\nMISSING from central: {missing}")
    if stale:
        print(f"STALE in central: {stale}")
    if not missing and not stale:
        print("\nNames match.")


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "kababjees"
    asyncio.run(main(slug))
