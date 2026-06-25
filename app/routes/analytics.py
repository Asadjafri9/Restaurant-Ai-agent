import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text

from app.db.models_tenant import MenuItem, Order, OrderItem
from app.deps.auth import TenantContext, get_tenant_ctx, require_role
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def analytics_summary(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    q = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total), 0),
        func.coalesce(func.avg(Order.total), 0),
    ).where(Order.status != "cancelled")
    if date_from:
        q = q.where(Order.placed_at >= date_from)
    if date_to:
        q = q.where(Order.placed_at < date_to)
    row = (await ctx.session.execute(q)).one()
    items_q = select(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order)
    if date_from:
        items_q = items_q.where(Order.placed_at >= date_from)
    if date_to:
        items_q = items_q.where(Order.placed_at < date_to)
    items_sold = (await ctx.session.execute(items_q)).scalar() or 0
    return {
        "orders_count": row[0] or 0,
        "revenue": float(row[1] or 0),
        "avg_order_value": float(row[2] or 0),
        "items_sold": int(items_sold),
    }


@router.get("/revenue-timeseries")
async def revenue_timeseries(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    granularity: str = Query("day"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    trunc = {"hour": "hour", "day": "day", "week": "week", "month": "month"}.get(granularity, "day")
    sql = text(f"""
        SELECT date_trunc(:trunc, placed_at) AS bucket,
               count(*) AS orders,
               coalesce(sum(total), 0) AS revenue,
               coalesce(avg(total), 0) AS aov
        FROM orders
        WHERE status != 'cancelled'
        {"AND placed_at >= :date_from" if date_from else ""}
        {"AND placed_at < :date_to" if date_to else ""}
        GROUP BY 1 ORDER BY 1
    """)
    params: dict = {"trunc": trunc}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    result = await ctx.session.execute(sql, params)
    return [
        {
            "bucket": r.bucket.isoformat() if r.bucket else None,
            "orders": r.orders,
            "revenue": float(r.revenue),
            "aov": float(r.aov),
        }
        for r in result
    ]


@router.get("/top-items")
async def top_items(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(10, le=50),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    q = (
        select(
            OrderItem.item_name_snapshot,
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(OrderItem.line_total).label("revenue"),
        )
        .join(Order)
        .where(Order.status != "cancelled")
        .group_by(OrderItem.item_name_snapshot)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
    )
    if date_from:
        q = q.where(Order.placed_at >= date_from)
    if date_to:
        q = q.where(Order.placed_at < date_to)
    rows = (await ctx.session.execute(q)).all()
    return [{"item": r[0], "quantity": int(r[1]), "revenue": float(r[2])} for r in rows]


@router.get("/orders-by-status")
async def orders_by_status(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    q = select(Order.status, func.count()).group_by(Order.status)
    if date_from:
        q = q.where(Order.placed_at >= date_from)
    if date_to:
        q = q.where(Order.placed_at < date_to)
    rows = (await ctx.session.execute(q)).all()
    return [{"status": r[0], "count": r[1]} for r in rows]


@router.get("/peak-hours")
async def peak_hours(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    sql = text("""
        SELECT extract(hour from placed_at)::int AS hour, count(*) AS count
        FROM orders
        WHERE status != 'cancelled'
        GROUP BY 1 ORDER BY 1
    """)
    rows = (await ctx.session.execute(sql)).all()
    return [{"hour": int(r.hour), "count": int(r.count)} for r in rows]
