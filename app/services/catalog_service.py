import json
import logging
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.db.central import get_central_session
from app.db.models_central import CatalogItem, Tenant
from app.db.redis_client import get_redis, redis_get_json, redis_set_json

logger = logging.getLogger(__name__)


async def list_active_restaurants() -> list[dict]:
    async for session in get_central_session():
        result = await session.execute(
            select(Tenant).where(Tenant.status == "active", Tenant.deleted_at.is_(None))
        )
        return [{"slug": t.slug, "name": t.name, "tenant_id": str(t.id)} for t in result.scalars()]
    return []


async def get_menu_for_tenant(tenant_id: uuid.UUID) -> list[dict]:
    cache_key = f"menu:{tenant_id}"
    cached = await redis_get_json(cache_key)
    if cached:
        return cached.get("items", [])

    async for session in get_central_session():
        result = await session.execute(
            select(CatalogItem)
            .where(CatalogItem.tenant_id == tenant_id, CatalogItem.is_available.is_(True))
            .order_by(CatalogItem.sort_order)
        )
        items = [
            {
                "name": i.name,
                "description": i.description,
                "category": i.category,
                "price": float(i.price),
                "tenant_item_id": str(i.tenant_item_id),
            }
            for i in result.scalars()
        ]
        await redis_set_json(cache_key, {"items": items}, ttl_seconds=300)
        return items
    return []


async def get_menu_by_slug(slug: str) -> tuple[uuid.UUID | None, list[dict]]:
    async for session in get_central_session():
        result = await session.execute(select(Tenant).where(Tenant.slug == slug, Tenant.status == "active"))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None, []
        items = await get_menu_for_tenant(tenant.id)
        return tenant.id, items
    return None, []


async def get_menus_prompt_cached() -> str:
    """Full menu block for agent system prompt — cached 5 min."""
    cache_key = "menus_prompt:v1"
    cached = await redis_get_json(cache_key)
    if cached and cached.get("text"):
        return cached["text"]

    restaurants = await list_active_restaurants()
    if not restaurants:
        from app.data.restaurants import format_menus_for_prompt

        return format_menus_for_prompt()

    lines = []
    for r in restaurants:
        _, items = await get_menu_by_slug(r["slug"])
        if items:
            lines.append(f"\n{r['name']} ({r['slug']}):\n{format_menu_text(items)}")
    text = "\n".join(lines) if lines else ""
    await redis_set_json(cache_key, {"text": text}, ttl_seconds=300)
    return text


def format_menu_text(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item['name']} — Rs {item['price']:.0f}")
    return "\n".join(lines) if lines else "  (menu empty)"
