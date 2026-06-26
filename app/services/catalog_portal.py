"""Central-catalog menu CRUD for standalone tenant portals.

When KFC and Kababjees Railway Postgres services point at the same physical database,
menu_items is shared. Each tenant's menu lives in central catalog_items (keyed by tenant_id).
"""

import uuid
from decimal import Decimal

from sqlalchemy import delete, select

from app.db.central import get_central_session
from app.db.models_central import CatalogItem
from app.services.catalog_service import invalidate_menu_caches


async def list_catalog_items(tenant_id: uuid.UUID) -> list[dict]:
    async for session in get_central_session():
        result = await session.execute(
            select(CatalogItem)
            .where(CatalogItem.tenant_id == tenant_id, CatalogItem.is_available.is_(True))
            .order_by(CatalogItem.sort_order)
        )
        return [
            {
                "id": str(i.id),
                "name": i.name,
                "description": i.description,
                "price": float(i.price),
                "category_id": None,
                "is_available": i.is_available,
                "sort_order": i.sort_order,
            }
            for i in result.scalars()
        ]
    return []


async def create_catalog_item(
    tenant_id: uuid.UUID,
    *,
    name: str,
    description: str | None,
    price: Decimal,
    is_available: bool,
    sort_order: int,
) -> dict:
    item_id = uuid.uuid4()
    async for session in get_central_session():
        row = CatalogItem(
            tenant_id=tenant_id,
            tenant_item_id=item_id,
            name=name,
            description=description,
            price=price,
            is_available=is_available,
            sort_order=sort_order,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        await invalidate_menu_caches(tenant_id)
        return {
            "id": str(row.id),
            "name": row.name,
            "price": float(row.price),
        }
    raise RuntimeError("Central DB unavailable")


async def update_catalog_item(
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    price: Decimal | None = None,
    is_available: bool | None = None,
    sort_order: int | None = None,
) -> dict:
    async for session in get_central_session():
        row = await session.get(CatalogItem, item_id)
        if not row or row.tenant_id != tenant_id:
            raise LookupError("Item not found")
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if price is not None:
            row.price = price
        if is_available is not None:
            row.is_available = is_available
        if sort_order is not None:
            row.sort_order = sort_order
        await session.commit()
        await invalidate_menu_caches(tenant_id)
        return {"id": str(row.id), "name": row.name}
    raise RuntimeError("Central DB unavailable")


async def delete_catalog_item(tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
    async for session in get_central_session():
        row = await session.get(CatalogItem, item_id)
        if not row or row.tenant_id != tenant_id:
            raise LookupError("Item not found")
        await session.execute(delete(CatalogItem).where(CatalogItem.id == item_id))
        await session.commit()
        await invalidate_menu_caches(tenant_id)
