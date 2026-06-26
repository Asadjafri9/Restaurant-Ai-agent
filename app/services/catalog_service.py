import logging
import uuid

from sqlalchemy import select

from app.core.tenant_ids import TENANT_IDS
from app.data.restaurants import RESTAURANTS
from app.db.central import get_central_session
from app.db.models_central import CatalogItem, Tenant

logger = logging.getLogger(__name__)

MENU_CACHE_TTL = 15
MENUS_PROMPT_KEY = "menus_prompt:v9"


def _slug_for_tenant_id(tenant_id: uuid.UUID) -> str | None:
    from app.core.tenant_ids import TENANT_IDS

    for slug, tid in TENANT_IDS.items():
        if tid == tenant_id:
            return slug
    return None


def _tenant_menu_looks_isolated(slug: str | None, tenant_items: list[dict]) -> bool:
    """True when tenant DB menu is not polluted with the other restaurant's items."""
    if not slug or not tenant_items:
        return False
    from app.data.restaurants import RESTAURANTS

    names = {i["name"].lower() for i in tenant_items}
    for other_slug, data in RESTAURANTS.items():
        if other_slug == slug:
            continue
        other_names = {m["item"].lower() for m in data["menu"]}
        if names & other_names:
            return False
    return True


async def invalidate_menu_caches(tenant_id: uuid.UUID | None = None) -> None:
    from app.core.read_cache import cache_key, invalidate_prefix

    await invalidate_prefix(MENUS_PROMPT_KEY)
    if tenant_id:
        await invalidate_prefix(cache_key("menu", str(tenant_id)))
    try:
        from app.config.settings import settings
        from app.db.redis_client import get_redis

        if settings.use_read_cache:
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


async def _load_menu_from_tenant_db(tenant_id: uuid.UUID) -> list[dict]:
    """Read live menu from the tenant's own database (source of truth)."""
    from app.db.models_tenant import MenuCategory, MenuItem
    from app.db.tenant_router import get_tenant_session

    try:
        session = await get_tenant_session(tenant_id)
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
            return [
                {
                    "name": i.name,
                    "description": i.description,
                    "category": cat_names.get(i.category_id) if i.category_id else None,
                    "price": float(i.price),
                    "tenant_item_id": str(i.id),
                }
                for i in items
            ]
    except Exception:
        logger.warning("Tenant DB menu read failed for %s", tenant_id, exc_info=True)
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
    from app.config.settings import settings
    from app.core.read_cache import cache_key, cached_json

    async def load() -> list[dict]:
        slug = _slug_for_tenant_id(tenant_id)
        central_items = await _load_menu_from_central(tenant_id)
        tenant_items = await _load_menu_from_tenant_db(tenant_id)

        # Dedicated tenant DB (dashboard) wins when it is not mixed with the other restaurant.
        if tenant_items and _tenant_menu_looks_isolated(slug, tenant_items):
            return tenant_items

        if central_items:
            return central_items

        # Shared Postgres: menu_items has no tenant column — only central catalog is safe.
        if settings.database_url_central:
            return []
        return tenant_items

    if force_refresh:
        return await load()
    return await cached_json(cache_key("menu", str(tenant_id)), MENU_CACHE_TTL, load)


def _restaurant_fallback_items(slug: str) -> list[dict]:
    if slug not in RESTAURANTS:
        return []
    return [
        {
            "name": m["item"],
            "price": float(m["price_pkr"]),
            "tenant_item_id": None,
            "description": None,
            "category": None,
        }
        for m in RESTAURANTS[slug]["menu"]
    ]


async def get_menu_by_slug(slug: str, *, force_refresh: bool = False) -> tuple[uuid.UUID | None, list[dict]]:
    tenant_id = TENANT_IDS.get(slug)
    async for session in get_central_session():
        result = await session.execute(select(Tenant).where(Tenant.slug == slug, Tenant.status == "active"))
        tenant = result.scalar_one_or_none()
        if not tenant:
            items = _restaurant_fallback_items(slug)
            return (tenant_id, items) if items else (None, [])
        items = await get_menu_for_tenant(tenant.id, force_refresh=force_refresh)
        if not items:
            items = _restaurant_fallback_items(slug)
        return tenant.id, items
    items = _restaurant_fallback_items(slug)
    return (tenant_id, items) if items else (None, [])


async def get_menus_prompt_cached(*, force_refresh: bool = False) -> str:
    from app.core.read_cache import cached_json

    async def load() -> str:
        restaurants = await list_active_restaurants()
        lines = []
        for r in restaurants:
            tenant_id = uuid.UUID(r["tenant_id"])
            items = await get_menu_for_tenant(tenant_id, force_refresh=force_refresh)
            if items:
                lines.append(f"\n{r['name']} ({r['slug']}):\n{format_menu_text(items)}")
            else:
                lines.append(f"\n{r['name']} ({r['slug']}):\n  (menu empty)")
        return "\n".join(lines)

    if force_refresh:
        return await load()
    return await cached_json(MENUS_PROMPT_KEY, MENU_CACHE_TTL, load)


def format_menu_text(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item['name']} — Rs {item['price']:.0f}")
    return "\n".join(lines) if lines else "  (menu empty)"
