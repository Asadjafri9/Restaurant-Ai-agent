"""Seed central catalog_items for each tenant from RESTAURANTS defaults.

Use when tenant Postgres databases are shared (same physical server) so menu_items
cannot hold per-tenant menus. Safe to run repeatedly — rebuilds each tenant mirror.
"""

import asyncio
import uuid

from sqlalchemy import delete, select

from app.core.tenant_ids import TENANT_IDS
from app.data.restaurants import RESTAURANTS
from app.db.central import get_central_session
from app.db.models_central import CatalogItem
from app.services.catalog_service import invalidate_menu_caches


async def seed_central_for_slug(slug: str) -> int:
    if slug not in RESTAURANTS:
        raise RuntimeError(f"Unknown slug: {slug}")
    data = RESTAURANTS[slug]
    tenant_id = TENANT_IDS[slug]
    count = 0

    async for session in get_central_session():
        await session.execute(delete(CatalogItem).where(CatalogItem.tenant_id == tenant_id))
        for i, entry in enumerate(data["menu"], start=1):
            item_id = uuid.uuid4()
            session.add(
                CatalogItem(
                    tenant_id=tenant_id,
                    tenant_item_id=item_id,
                    name=entry["item"],
                    description=f"{data['name']} menu item",
                    price=entry["price_pkr"],
                    is_available=True,
                    sort_order=i,
                )
            )
            count += 1
        await session.commit()

    await invalidate_menu_caches(tenant_id)
    print(f"Seeded central catalog for {slug}: {count} items")
    return count


async def seed_all() -> None:
    for slug in RESTAURANTS:
        await seed_central_for_slug(slug)
    await invalidate_menu_caches()


async def verify() -> None:
    async for session in get_central_session():
        for slug in RESTAURANTS:
            tenant_id = TENANT_IDS[slug]
            result = await session.execute(
                select(CatalogItem.name)
                .where(CatalogItem.tenant_id == tenant_id, CatalogItem.is_available.is_(True))
                .order_by(CatalogItem.sort_order)
            )
            names = list(result.scalars())
            expected = [m["item"] for m in RESTAURANTS[slug]["menu"]]
            ok = names == expected
            print(f"{slug}: {'OK' if ok else 'MISMATCH'} — {names}")


async def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        await verify()
    elif len(sys.argv) > 1:
        await seed_central_for_slug(sys.argv[1])
    else:
        await seed_all()
        await verify()


if __name__ == "__main__":
    asyncio.run(main())
