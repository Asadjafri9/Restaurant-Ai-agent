import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.models_tenant import Customer, Order, OrderItem
from app.deps.auth import TenantContext, get_tenant_ctx, require_role
from app.services.order_routing import order_routing
from app.services.realtime import publish_order_event
from app.services.whatsapp_service import send_text_message
from fastapi import APIRouter, Depends, HTTPException, Query

router = APIRouter(prefix="/orders", tags=["orders"])


class StatusUpdate(BaseModel):
    status: str
    cancellation_reason: str | None = None


ACTIVE_STATUSES = ("placed", "accepted", "preparing", "out_for_delivery")


@router.get("")
async def list_orders(
    status: str | None = None,
    limit: int = Query(default=50, le=100),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager", "staff")),
) -> list[dict]:
    q = select(Order).order_by(Order.placed_at.desc()).limit(limit)
    if status:
        q = q.where(Order.status == status)
    result = await ctx.session.execute(q)
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "status": o.status,
            "total": float(o.total),
            "placed_at": o.placed_at.isoformat(),
            "delivery_address": o.delivery_address[:80],
        }
        for o in orders
    ]


@router.get("/board")
async def order_board(
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager", "staff")),
) -> list[dict]:
    from app.core.read_cache import cache_key, cached_json

    key = cache_key("board", str(ctx.tenant_id))

    async def load() -> list[dict]:
        item_count_sq = (
            select(func.count(OrderItem.id))
            .where(OrderItem.order_id == Order.id)
            .correlate(Order)
            .scalar_subquery()
        )
        result = await ctx.session.execute(
            select(
                Order.id,
                Order.status,
                Order.total,
                Order.placed_at,
                Order.delivery_address,
                item_count_sq.label("item_count"),
            )
            .where(Order.status.in_(ACTIVE_STATUSES))
            .order_by(Order.placed_at.desc())
            .limit(100)
        )
        return [
            {
                "id": str(r.id),
                "status": r.status,
                "total": float(r.total),
                "placed_at": r.placed_at.isoformat(),
                "item_count": int(r.item_count or 0),
                "delivery_address": r.delivery_address,
            }
            for r in result.all()
        ]

    return await cached_json(key, 5, load)


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager", "staff")),
) -> dict:
    data = await order_routing.get_order(ctx.tenant_id, order_id)
    if not data:
        raise HTTPException(status_code=404, detail="Order not found")
    cust = (
        await ctx.session.execute(
            select(Customer).join(Order).where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if cust:
        data["customer_name"] = cust.name
        data["customer_phone"] = cust.phone
    return data


@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    body: StatusUpdate,
    ctx: TenantContext = Depends(get_tenant_ctx),
    user=Depends(require_role("owner", "manager", "staff")),
) -> dict:
    try:
        result = await order_routing.update_status(
            ctx.tenant_id,
            order_id,
            body.status,
            changed_by=user.id,
            source="dashboard",
            cancellation_reason=body.cancellation_reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    from app.core.read_cache import invalidate_prefix

    await invalidate_prefix(f"api:board:{ctx.tenant_id}")
    await publish_order_event(
        ctx.tenant_id,
        {"type": "order_status_changed", "order_id": str(order_id), "status": body.status},
    )
    from app.services.provisioning import enqueue_job

    await enqueue_job("sync_outboxes", {"tenant_id": str(ctx.tenant_id)})
    cust = (
        await ctx.session.execute(
            select(Customer).join(Order).where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if cust:
        msg = f"Your order #{str(order_id)[:8]} is now: {body.status.replace('_', ' ')}."
        await send_text_message(cust.phone, msg)
    return result
