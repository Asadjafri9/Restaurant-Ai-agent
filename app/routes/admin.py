import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select

from app.db.central import get_central_session
from app.db.models_central import AgentConversation, OrderRoutingIndex, Tenant
from app.deps.auth import require_role
from app.services.provisioning import create_tenant_record, enqueue_job
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/admin", tags=["admin"])


class ProvisionTenantRequest(BaseModel):
    name: str
    slug: str
    owner_email: EmailStr
    plan: str = "free"


@router.get("/overview")
async def admin_overview(_: object = Depends(require_role("platform_admin"))) -> dict:
    import asyncio

    from app.core.read_cache import cache_key, cached_json

    async def load() -> dict:
        async for session in get_central_session():
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            active, orders_today, convos = await asyncio.gather(
                session.scalar(select(func.count()).select_from(Tenant).where(Tenant.status == "active")),
                session.scalar(
                    select(func.count())
                    .select_from(OrderRoutingIndex)
                    .where(OrderRoutingIndex.placed_at >= today)
                ),
                session.scalar(select(func.count()).select_from(AgentConversation)),
            )
            return {
                "active_tenants": active or 0,
                "orders_today": orders_today or 0,
                "agent_sessions": convos or 0,
            }
        return {}

    return await cached_json(cache_key("admin", "overview"), 15, load)


@router.get("/tenants")
async def list_tenants(_: object = Depends(require_role("platform_admin"))) -> list[dict]:
    from app.core.read_cache import cache_key, cached_json

    async def load() -> list[dict]:
        async for session in get_central_session():
            result = await session.execute(select(Tenant).order_by(Tenant.created_at.desc()))
            tenants = result.scalars().all()
            return [
                {
                    "id": str(t.id),
                    "slug": t.slug,
                    "name": t.name,
                    "owner_email": t.owner_email,
                    "status": t.status,
                    "plan": t.plan,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tenants
            ]
        return []

    return await cached_json(cache_key("admin", "tenants"), 15, load)


@router.get("/dashboard")
async def admin_dashboard(_: object = Depends(require_role("platform_admin"))) -> dict:
    """Overview + tenants in one request."""
    import asyncio

    from app.core.read_cache import cache_key, cached_json

    async def load() -> dict:
        async for session in get_central_session():
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            active, orders_today, convos, tenants_result = await asyncio.gather(
                session.scalar(select(func.count()).select_from(Tenant).where(Tenant.status == "active")),
                session.scalar(
                    select(func.count())
                    .select_from(OrderRoutingIndex)
                    .where(OrderRoutingIndex.placed_at >= today)
                ),
                session.scalar(select(func.count()).select_from(AgentConversation)),
                session.execute(select(Tenant).order_by(Tenant.created_at.desc())),
            )
            tenants = tenants_result.scalars().all()
            return {
                "overview": {
                    "active_tenants": active or 0,
                    "orders_today": orders_today or 0,
                    "agent_sessions": convos or 0,
                },
                "tenants": [
                    {
                        "id": str(t.id),
                        "slug": t.slug,
                        "name": t.name,
                        "owner_email": t.owner_email,
                        "status": t.status,
                        "plan": t.plan,
                        "created_at": t.created_at.isoformat(),
                    }
                    for t in tenants
                ],
            }
        return {"overview": {}, "tenants": []}

    return await cached_json(cache_key("admin", "dashboard"), 15, load)


@router.post("/tenants")
async def provision_tenant(
    body: ProvisionTenantRequest,
    _: object = Depends(require_role("platform_admin")),
) -> dict:
    tenant_id = await create_tenant_record(body.slug, body.name, body.owner_email, body.plan)
    job_id = await enqueue_job(
        "provision_tenant",
        {
            "tenant_id": str(tenant_id),
            "slug": body.slug,
            "name": body.name,
            "owner_email": body.owner_email,
        },
    )
    return {"tenant_id": str(tenant_id), "job_id": job_id, "status": "provisioning"}


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: uuid.UUID,
    _: object = Depends(require_role("platform_admin")),
) -> dict:
    async for session in get_central_session():
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            return {}
        order_count = await session.scalar(
            select(func.count())
            .select_from(OrderRoutingIndex)
            .where(OrderRoutingIndex.tenant_id == tenant_id)
        )
        return {
            "id": str(tenant.id),
            "slug": tenant.slug,
            "name": tenant.name,
            "status": tenant.status,
            "order_count": order_count or 0,
        }
    return {}
