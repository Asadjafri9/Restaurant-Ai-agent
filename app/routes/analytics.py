from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.db.models_tenant import Order, OrderItem
from app.deps.auth import TenantContext, get_tenant_ctx, require_role
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/analytics", tags=["analytics"])

BUSINESS_TZ = ZoneInfo("Asia/Karachi")


def resolve_date_range(
    range_key: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime | None, datetime | None, str]:
    """Resolve preset range keys to timezone-aware [from, to) bounds in business TZ."""
    if not range_key:
        return date_from, date_to, "day"
    now = datetime.now(BUSINESS_TZ)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "today":
        end = start_of_today + timedelta(days=1)
        return start_of_today, end, "hour"
    if range_key == "7d":
        return start_of_today - timedelta(days=6), start_of_today + timedelta(days=1), "day"
    if range_key == "30d":
        return start_of_today - timedelta(days=29), start_of_today + timedelta(days=1), "day"
    return date_from, date_to, "day"


async def _summary(ctx: TenantContext, date_from: datetime | None, date_to: datetime | None) -> dict:
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


async def _revenue_timeseries(
    ctx: TenantContext,
    date_from: datetime | None,
    date_to: datetime | None,
    granularity: str = "day",
) -> list[dict]:
    trunc = {"hour": "hour", "day": "day", "week": "week", "month": "month"}.get(granularity, "day")
    tz_name = "Asia/Karachi"
    sql = text(f"""
        SELECT date_trunc(:trunc, placed_at AT TIME ZONE :tz) AS bucket,
               count(*) AS orders,
               coalesce(sum(total), 0) AS revenue,
               coalesce(avg(total), 0) AS aov
        FROM orders
        WHERE status != 'cancelled'
        {"AND placed_at >= :date_from" if date_from else ""}
        {"AND placed_at < :date_to" if date_to else ""}
        GROUP BY 1 ORDER BY 1
    """)
    params: dict = {"trunc": trunc, "tz": tz_name}
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


async def _top_items(
    ctx: TenantContext,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int = 10,
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


async def _orders_by_status(
    ctx: TenantContext, date_from: datetime | None, date_to: datetime | None
) -> list[dict]:
    q = select(Order.status, func.count()).group_by(Order.status)
    if date_from:
        q = q.where(Order.placed_at >= date_from)
    if date_to:
        q = q.where(Order.placed_at < date_to)
    rows = (await ctx.session.execute(q)).all()
    return [{"status": r[0], "count": r[1]} for r in rows]


async def _peak_hours(
    ctx: TenantContext,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict]:
    clauses = ["status != 'cancelled'"]
    params: dict = {}
    if date_from:
        clauses.append("placed_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        clauses.append("placed_at < :date_to")
        params["date_to"] = date_to
    tz_name = "Asia/Karachi"
    sql = text(f"""
        SELECT extract(hour from (placed_at AT TIME ZONE :tz))::int AS hour, count(*) AS count
        FROM orders
        WHERE {" AND ".join(clauses)}
        GROUP BY 1 ORDER BY 1
    """)
    params["tz"] = tz_name
    rows = (await ctx.session.execute(sql, params)).all()
    return [{"hour": int(r.hour), "count": int(r.count)} for r in rows]


@router.get("/summary")
async def analytics_summary(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    return await _summary(ctx, date_from, date_to)


@router.get("/revenue-timeseries")
async def revenue_timeseries(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    granularity: str = Query("day"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    return await _revenue_timeseries(ctx, date_from, date_to, granularity)


@router.get("/top-items")
async def top_items(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(10, le=50),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    return await _top_items(ctx, date_from, date_to, limit)


@router.get("/orders-by-status")
async def orders_by_status(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    return await _orders_by_status(ctx, date_from, date_to)


@router.get("/peak-hours")
async def peak_hours(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> list[dict]:
    return await _peak_hours(ctx, date_from, date_to)


@router.get("/dashboard")
async def analytics_dashboard(
    range_key: str | None = Query(None, alias="range"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    ctx: TenantContext = Depends(get_tenant_ctx),
    _: object = Depends(require_role("owner", "manager")),
) -> dict:
    """All analytics charts in one DB session / one HTTP request."""
    import asyncio

    from app.core.read_cache import cache_key, cached_json

    date_from, date_to, granularity = resolve_date_range(range_key, date_from, date_to)

    key = cache_key(
        "analytics",
        str(ctx.tenant_id),
        range_key or "",
        date_from.isoformat() if date_from else "",
        date_to.isoformat() if date_to else "",
    )

    async def load() -> dict:
        summary, ts, top, by_status, hours = await asyncio.gather(
            _summary(ctx, date_from, date_to),
            _revenue_timeseries(ctx, date_from, date_to, granularity),
            _top_items(ctx, date_from, date_to),
            _orders_by_status(ctx, date_from, date_to),
            _peak_hours(ctx, date_from, date_to),
        )
        return {
            "summary": summary,
            "revenue_timeseries": ts,
            "top_items": top,
            "orders_by_status": by_status,
            "peak_hours": hours,
            "range": range_key,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        }

    ttl = 5 if range_key == "today" else 20
    return await cached_json(key, ttl, load)
