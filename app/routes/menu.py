import uuid
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select

from app.config.settings import settings
from app.db.models_tenant import MenuCategory, MenuItem, MenuOutbox
from app.deps.auth import TenantContext, get_tenant_ctx, require_role
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/menu", tags=["menu"])


def _uses_central_menu() -> bool:
    """Standalone portals store menus in central catalog when tenant DB may be shared."""
    return settings.is_standalone_tenant and bool(settings.database_url_central)


class CategoryCreate(BaseModel):
    name: str
    sort_order: int = 0


class ItemCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal
    category_id: uuid.UUID | None = None
    is_available: bool = True
    sort_order: int = 0


class ItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    category_id: uuid.UUID | None = None
    is_available: bool | None = None
    sort_order: int | None = None


@router.get("/categories")
async def list_categories(ctx: TenantContext = Depends(get_tenant_ctx)) -> list[dict]:
    result = await ctx.session.execute(
        select(MenuCategory).where(MenuCategory.is_active.is_(True)).order_by(MenuCategory.sort_order)
    )
    return [{"id": str(c.id), "name": c.name, "sort_order": c.sort_order} for c in result.scalars()]


@router.post("/categories")
async def create_category(
    body: CategoryCreate,
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    cat = MenuCategory(name=body.name, sort_order=body.sort_order)
    ctx.session.add(cat)
    await ctx.session.commit()
    await ctx.session.refresh(cat)
    return {"id": str(cat.id), "name": cat.name}


@router.get("/items")
async def list_items(ctx: TenantContext = Depends(get_tenant_ctx)) -> list[dict]:
    from app.core.read_cache import cache_key, cached_json

    key = cache_key("menu", str(ctx.tenant_id))

    async def load() -> list[dict]:
        if _uses_central_menu():
            from app.services.catalog_portal import list_catalog_items

            return await list_catalog_items(ctx.tenant_id)
        result = await ctx.session.execute(
            select(MenuItem).where(MenuItem.deleted_at.is_(None)).order_by(MenuItem.sort_order)
        )
        return [
            {
                "id": str(i.id),
                "name": i.name,
                "description": i.description,
                "price": float(i.price),
                "category_id": str(i.category_id) if i.category_id else None,
                "is_available": i.is_available,
                "sort_order": i.sort_order,
            }
            for i in result.scalars()
        ]

    return await cached_json(key, 30, load)


async def _publish_outbox(ctx: TenantContext, action: str, item: MenuItem, category_name: str | None) -> None:
    from app.core.read_cache import invalidate_prefix

    await invalidate_prefix(f"api:menu:{ctx.tenant_id}")
    payload = {
        "tenant_id": str(ctx.tenant_id),
        "tenant_item_id": str(item.id),
        "name": item.name,
        "description": item.description,
        "category": category_name,
        "price": float(item.price),
        "is_available": item.is_available,
        "sort_order": item.sort_order,
    }
    ctx.session.add(MenuOutbox(action=action, payload=payload))


@router.post("/items")
async def create_item(
    body: ItemCreate,
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    if _uses_central_menu():
        from app.core.read_cache import invalidate_prefix
        from app.services.catalog_portal import create_catalog_item

        result = await create_catalog_item(
            ctx.tenant_id,
            name=body.name,
            description=body.description,
            price=body.price,
            is_available=body.is_available,
            sort_order=body.sort_order,
        )
        await invalidate_prefix(f"api:menu:{ctx.tenant_id}")
        return result

    item = MenuItem(
        name=body.name,
        description=body.description,
        price=body.price,
        category_id=body.category_id,
        is_available=body.is_available,
        sort_order=body.sort_order,
    )
    ctx.session.add(item)
    await ctx.session.flush()
    cat_name = None
    if body.category_id:
        cat = await ctx.session.get(MenuCategory, body.category_id)
        cat_name = cat.name if cat else None
    await _publish_outbox(ctx, "create", item, cat_name)
    await ctx.session.commit()
    from app.services.menu_sync import sync_menu_after_mutation

    await sync_menu_after_mutation(ctx.tenant_id)
    return {"id": str(item.id), "name": item.name, "price": float(item.price)}


@router.patch("/items/{item_id}")
async def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    if _uses_central_menu():
        from app.core.read_cache import invalidate_prefix
        from app.services.catalog_portal import update_catalog_item

        try:
            result = await update_catalog_item(
                ctx.tenant_id,
                item_id,
                name=body.name,
                description=body.description,
                price=body.price,
                is_available=body.is_available,
                sort_order=body.sort_order,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="Item not found") from None
        await invalidate_prefix(f"api:menu:{ctx.tenant_id}")
        return result

    item = await ctx.session.get(MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if body.name is not None:
        item.name = body.name
    if body.description is not None:
        item.description = body.description
    if body.price is not None:
        item.price = body.price
    if body.category_id is not None:
        item.category_id = body.category_id
    if body.is_available is not None:
        item.is_available = body.is_available
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    cat_name = None
    if item.category_id:
        cat = await ctx.session.get(MenuCategory, item.category_id)
        cat_name = cat.name if cat else None
    await _publish_outbox(ctx, "update", item, cat_name)
    await ctx.session.commit()
    from app.services.menu_sync import sync_menu_after_mutation

    await sync_menu_after_mutation(ctx.tenant_id)
    return {"id": str(item.id), "name": item.name}


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    if _uses_central_menu():
        from app.core.read_cache import invalidate_prefix
        from app.services.catalog_portal import delete_catalog_item

        try:
            await delete_catalog_item(ctx.tenant_id, item_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="Item not found") from None
        await invalidate_prefix(f"api:menu:{ctx.tenant_id}")
        return {"status": "deleted"}

    item = await ctx.session.get(MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    from datetime import datetime, timezone

    item.deleted_at = datetime.now(timezone.utc)
    item.is_available = False
    await _publish_outbox(ctx, "delete", item, None)
    await ctx.session.commit()
    from app.services.menu_sync import sync_menu_after_mutation

    await sync_menu_after_mutation(ctx.tenant_id)
    return {"status": "deleted"}
