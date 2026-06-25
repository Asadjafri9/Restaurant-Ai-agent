"""Compare tenant menu_items vs central catalog_items for a slug."""

import asyncio
import os
import sys

from sqlalchemy import select

from app.core.tenant_ids import TENANT_IDS
from app.db.central import get_central_session
from app.db.models_central import CatalogItem, Tenant
from app.db.models_tenant import MenuItem
from app.db.standalone import get_standalone_session


async def main(slug: str) -> None:
    tenant_id = TENANT_IDS[slug]
    os.environ.setdefault("SERVICE_MODE", slug)
    os.environ["TENANT_ID"] = str(tenant_id)

    session = await get_standalone_session()
    async with session:
        tenant_items = (
            await session.execute(
                select(MenuItem)
                .where(MenuItem.deleted_at.is_(None), MenuItem.is_available.is_(True))
                .order_by(MenuItem.sort_order)
            )
        ).scalars().all()

    print(f"\n=== {slug} tenant DB ({len(tenant_items)} items) ===")
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

    print(f"\n=== central catalog ({len(central_items)} items) ===")
    for i in central_items:
        print(f"  {i.name} — Rs {i.price}  tenant_item_id={i.tenant_item_id}")

    tenant_names = {i.name for i in tenant_items}
    central_names = {i.name for i in central_items}
    missing = tenant_names - central_names
    stale = central_names - tenant_names
    if missing:
        print(f"\nMISSING from central: {missing}")
    if stale:
        print(f"STALE in central (not in tenant): {stale}")
    if not missing and not stale:
        print("\nNames match.")


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "kababjees"
    asyncio.run(main(slug))
