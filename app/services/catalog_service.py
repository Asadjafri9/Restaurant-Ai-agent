import logging
import uuid

from sqlalchemy import select

from app.db.central import get_central_session
from app.db.models_central import CatalogItem, Tenant
from app.db.redis_client import get_redis, redis_get_json, redis_set_json

logger = logging.getLogger(__name__)

MENU_CACHE_TTL = 30
MENUS_PROMPT_CACHE_TTL = 30
MENUS_PROMPT_KEY = "menus_prompt:v3"


async def invalidate_menu_caches(tenant_id: uuid.UUID | None = None) -> None:
    """Drop agent menu caches so the next read reflects portal edits."""
    try:
        r = get_redis()
        await r.delete(MENUS_PROMPT_KEY)
        if tenant_id:
            await r.delete(f"menu:{tenant_id}")
    except Exception:
        logger.warning("Menu cache invalidation failed", exc_info=True)


async def list_active_restaurants() -> list[dict]:
    async for session in get_central_session():
        result = await session.execute(
            select(Tenant).where(Tenant.status == "active", Tenant.deleted_at.is_(None))
        )
        return [{"slug": t.slug, "name": t.name, "tenant_id": str(t.id)} for t in result.scalars()]
    return []


async def _load_menu_from_central(tenant_id: uuid.UUID) -> list[dict]:
    async for session in get_central_session():
        result = await session.execute(
            select(CatalogItem)
            .where(CatalogItem.tenant_id == tenant_id, CatalogItem.is_available.is_(True))
            .order_by(CatalogItem.sort_order)
        )
        return [
            {
                "name": i.name,
                "description": i.description,
                "category": i.category,
                "price": float(i.price),
                "tenant_item_id": str(i.tenant_item_id),
            }
            for i in result.scalars()
        ]
    return []


async def get_menu_for_tenant(tenant_id: uuid.UUID, *, force_refresh: bool = False) -> list[dict]:
    """Read the tenant menu from the central catalog mirror.

    The mirror is kept current by the menu outbox (portal edit -> outbox ->
    sync_outboxes -> catalog_items + cache invalidation), so this stays in sync
    in near real time without the agent needing direct credentials to each
    tenant database.
    """
    cache_key = f"menu:{tenant_id}"
    if not force_refresh:
        cached = await redis_get_json(cache_key)
        if cached:
            return cached.get("items", [])

    items = await _load_menu_from_central(tenant_id)
    await redis_set_json(cache_key, {"items": items}, ttl_seconds=MENU_CACHE_TTL)
    return items


async def get_menu_by_slug(slug: str, *, force_refresh: bool = False) -> tuple[uuid.UUID | None, list[dict]]:
    async for session in get_central_session():
        result = await session.execute(select(Tenant).where(Tenant.slug == slug, Tenant.status == "active"))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None, []
        items = await get_menu_for_tenant(tenant.id, force_refresh=force_refresh)
        return tenant.id, items
    return None, []


async def get_menus_prompt_cached(*, force_refresh: bool = False) -> str:
    """Live menu block for the agent system prompt."""
    if not force_refresh:
        cached = await redis_get_json(MENUS_PROMPT_KEY)
        if cached and cached.get("text") is not None:
            return cached["text"]

    restaurants = await list_active_restaurants()
    if not restaurants:
        text = ""
    else:
        lines = []
        for r in restaurants:
            tenant_id = uuid.UUID(r["tenant_id"])
            items = await get_menu_for_tenant(tenant_id, force_refresh=force_refresh)
            if items:
                lines.append(f"\n{r['name']} ({r['slug']}):\n{format_menu_text(items)}")
            else:
                lines.append(f"\n{r['name']} ({r['slug']}):\n  (menu empty — check portal)")
        text = "\n".join(lines)

    await redis_set_json(MENUS_PROMPT_KEY, {"text": text}, ttl_seconds=MENUS_PROMPT_CACHE_TTL)
    return text


def format_menu_text(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item['name']} — Rs {item['price']:.0f}")
    return "\n".join(lines) if lines else "  (menu empty)"
