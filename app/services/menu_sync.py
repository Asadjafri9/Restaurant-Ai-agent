"""Rebuild the central catalog mirror from a tenant's live menu_items table."""

import logging
import uuid

from sqlalchemy import delete, select

from app.db.central import get_central_session
from app.db.models_central import CatalogItem
from app.db.models_tenant import MenuCategory, MenuItem
from app.services.catalog_service import invalidate_menu_caches

logger = logging.getLogger(__name__)


async def _tenant_menu_session(tenant_id: uuid.UUID):
    from app.config.settings import get_settings

    settings = get_settings()

    if settings.is_standalone_tenant:
        from app.db.standalone import get_standalone_session

        return await get_standalone_session()
    from app.db.tenant_router import get_tenant_session

    return await get_tenant_session(tenant_id)


async def sync_tenant_menu_to_central(tenant_id: uuid.UUID) -> int:
    """Full mirror rebuild: tenant menu_items -> central catalog_items.

    Returns the number of items synced. Removes stale central rows that no
    longer exist in the tenant database.
    """
    from app.config.settings import get_settings

    settings = get_settings()

    if not settings.database_url_central:
        logger.warning("Cannot sync menu for %s: DATABASE_URL_CENTRAL not set", tenant_id)
        return 0

    session = await _tenant_menu_session(tenant_id)
    async with session:
        result = await session.execute(
            select(MenuItem)
            .where(MenuItem.deleted_at.is_(None), MenuItem.is_available.is_(True))
            .order_by(MenuItem.sort_order)
        )
        items = list(result.scalars())
        cat_names: dict[uuid.UUID, str] = {}
        cat_ids = {i.category_id for i in items if i.category_id}
        if cat_ids:
            cats = await session.execute(select(MenuCategory).where(MenuCategory.id.in_(cat_ids)))
            cat_names = {c.id: c.name for c in cats.scalars()}

    synced = 0
    removed = 0
    async for central in get_central_session():
        existing = await central.execute(select(CatalogItem).where(CatalogItem.tenant_id == tenant_id))
        by_item_id = {row.tenant_item_id: row for row in existing.scalars()}

        live_ids: set[uuid.UUID] = set()
        for item in items:
            live_ids.add(item.id)
            row = by_item_id.get(item.id)
            if not row:
                row = CatalogItem(tenant_id=tenant_id, tenant_item_id=item.id)
                central.add(row)
            row.name = item.name
            row.description = item.description
            row.category = cat_names.get(item.category_id) if item.category_id else None
            row.price = item.price
            row.is_available = item.is_available
            row.sort_order = item.sort_order
            synced += 1

        stale_ids = [tid for tid in by_item_id if tid not in live_ids]
        removed = len(stale_ids)
        if stale_ids:
            await central.execute(
                delete(CatalogItem).where(
                    CatalogItem.tenant_id == tenant_id,
                    CatalogItem.tenant_item_id.in_(stale_ids),
                )
            )

        await central.commit()

    await invalidate_menu_caches(tenant_id)
    logger.info("Synced %d menu items for tenant %s (removed %d stale)", synced, tenant_id, removed)
    return synced


async def sync_menu_after_mutation(tenant_id: uuid.UUID) -> None:
    """Process pending outbox rows then rebuild the full mirror."""
    from app.services.provisioning import process_tenant_outboxes

    try:
        await process_tenant_outboxes(tenant_id)
    except Exception:
        logger.exception("Outbox processing failed for %s, rebuilding mirror anyway", tenant_id)
    await sync_tenant_menu_to_central(tenant_id)
