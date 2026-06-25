import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.central import get_central_session
from app.db.models_central import Tenant
from app.db.redis_client import get_redis
from app.db.tenant_router import provision_tenant_db

logger = logging.getLogger(__name__)

QUEUE_KEY = "platform:jobs"


async def enqueue_job(job_type: str, payload: dict) -> str:
    import asyncio

    r = get_redis()
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "type": job_type, "payload": payload}
    await r.lpush(QUEUE_KEY, json.dumps(job))
    logger.info("Enqueued job %s type=%s", job_id, job_type)
    if job_type == "sync_outboxes":
        tenant_id = uuid.UUID(payload["tenant_id"])
        asyncio.create_task(_sync_outboxes_safe(tenant_id))
    return job_id


async def _sync_outboxes_safe(tenant_id: uuid.UUID) -> None:
    from app.config.settings import settings

    if not settings.database_url_central:
        logger.warning(
            "Skipping inline outbox sync for %s: DATABASE_URL_CENTRAL not configured. "
            "A worker with central access must process the outbox.",
            tenant_id,
        )
        return
    try:
        await process_tenant_outboxes(tenant_id)
    except Exception:
        logger.exception("Inline outbox sync failed for tenant %s", tenant_id)


async def process_provision_tenant(payload: dict) -> None:
    tenant_id = uuid.UUID(payload["tenant_id"])
    slug = payload["slug"]
    name = payload["name"]
    owner_email = payload["owner_email"]
    await provision_tenant_db(tenant_id, slug, name, owner_email)


async def process_routing_outbox(payload: dict) -> None:
    from datetime import datetime

    from app.db.models_central import OrderRoutingIndex

    action = payload.get("action")
    data = payload.get("data", {})
    async for session in get_central_session():
        if action == "order_created":
            existing = await session.execute(
                select(OrderRoutingIndex).where(
                    OrderRoutingIndex.idempotency_key == data["idempotency_key"]
                )
            )
            if existing.scalar_one_or_none():
                return
            row = OrderRoutingIndex(
                id=uuid.UUID(data["order_id"]),
                tenant_id=uuid.UUID(data["tenant_id"]),
                status=data["status"],
                customer_phone_hash=data.get("customer_phone_hash"),
                idempotency_key=data["idempotency_key"],
            )
            session.add(row)
        elif action == "status_changed":
            row = await session.get(OrderRoutingIndex, uuid.UUID(data["order_id"]))
            if row:
                row.status = data["status"]
                row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def process_menu_outbox(payload: dict) -> None:
    from app.db.models_central import CatalogItem

    action = payload["action"]
    data = payload["data"]
    tenant_id = uuid.UUID(data["tenant_id"])
    async for session in get_central_session():
        if action in ("create", "update"):
            existing = await session.execute(
                select(CatalogItem).where(
                    CatalogItem.tenant_id == tenant_id,
                    CatalogItem.tenant_item_id == uuid.UUID(data["tenant_item_id"]),
                )
            )
            item = existing.scalar_one_or_none()
            if not item:
                item = CatalogItem(
                    tenant_id=tenant_id,
                    tenant_item_id=uuid.UUID(data["tenant_item_id"]),
                )
                session.add(item)
            item.name = data["name"]
            item.description = data.get("description")
            item.category = data.get("category")
            item.price = data["price"]
            item.is_available = data.get("is_available", True)
            item.sort_order = data.get("sort_order", 0)
        elif action == "delete":
            existing = await session.execute(
                select(CatalogItem).where(
                    CatalogItem.tenant_id == tenant_id,
                    CatalogItem.tenant_item_id == uuid.UUID(data["tenant_item_id"]),
                )
            )
            item = existing.scalar_one_or_none()
            if item:
                await session.delete(item)
        await session.commit()

    from app.services.catalog_service import invalidate_menu_caches

    await invalidate_menu_caches(tenant_id)


async def process_tenant_outboxes(tenant_id: uuid.UUID) -> None:
    from app.db.models_tenant import MenuOutbox, RoutingOutbox
    from app.db.tenant_router import get_tenant_session

    session = await get_tenant_session(tenant_id)
    async with session:
        menu_rows = (
            await session.execute(
                select(MenuOutbox).where(MenuOutbox.processed_at.is_(None)).limit(50)
            )
        ).scalars().all()
        for row in menu_rows:
            await process_menu_outbox({"action": row.action, "data": row.payload})
            row.processed_at = datetime.now(timezone.utc)

        routing_rows = (
            await session.execute(
                select(RoutingOutbox).where(RoutingOutbox.processed_at.is_(None)).limit(50)
            )
        ).scalars().all()
        for row in routing_rows:
            await process_routing_outbox({"action": row.action, "data": row.payload})
            row.processed_at = datetime.now(timezone.utc)
        await session.commit()


async def create_tenant_record(slug: str, name: str, owner_email: str, plan: str = "free") -> uuid.UUID:
    async for session in get_central_session():
        tenant = Tenant(slug=slug, name=name, owner_email=owner_email, status="provisioning", plan=plan)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        return tenant.id
    raise RuntimeError("Failed to create tenant")
