import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db.models_tenant import (
    Customer,
    Order,
    OrderItem,
    OrderStatusHistory,
    RoutingOutbox,
)
from app.db.tenant_router import get_tenant_session
from app.services.session_service import phone_hash

logger = logging.getLogger(__name__)

ORDER_STATUSES = {
    "placed": ["accepted", "cancelled"],
    "accepted": ["preparing", "cancelled"],
    "preparing": ["out_for_delivery", "cancelled"],
    "out_for_delivery": ["delivered", "cancelled"],
    "delivered": [],
    "cancelled": [],
}


class OrderRoutingService:
    async def create_order(
        self,
        tenant_id: uuid.UUID,
        *,
        customer_phone: str,
        customer_name: str,
        delivery_address: str,
        items: list[dict],
        idempotency_key: str,
        notes: str | None = None,
        delivery_fee: Decimal = Decimal("0"),
        tax: Decimal = Decimal("0"),
    ) -> dict:
        session = await get_tenant_session(tenant_id)
        async with session:
            existing = await session.execute(
                select(Order).where(Order.idempotency_key == idempotency_key)
            )
            if order := existing.scalar_one_or_none():
                return {"order_id": str(order.id), "total": float(order.total), "status": order.status}

            cust_result = await session.execute(
                select(Customer).where(Customer.phone == customer_phone)
            )
            customer = cust_result.scalar_one_or_none()
            if not customer:
                customer = Customer(phone=customer_phone, name=customer_name)
                session.add(customer)
                await session.flush()
            else:
                customer.name = customer_name or customer.name

            subtotal = Decimal("0")
            order_items: list[OrderItem] = []
            for item in items:
                qty = int(item["quantity"])
                unit_price = Decimal(str(item["unit_price"]))
                line_total = unit_price * qty
                subtotal += line_total
                mid = item.get("menu_item_id")
                menu_uuid = None
                if mid:
                    menu_uuid = uuid.UUID(mid) if isinstance(mid, str) else mid
                order_items.append(
                    OrderItem(
                        menu_item_id=menu_uuid,
                        item_name_snapshot=item["name"],
                        unit_price_snapshot=unit_price,
                        quantity=qty,
                        line_total=line_total,
                    )
                )

            total = subtotal + delivery_fee + tax
            order_id = uuid.uuid4()
            order = Order(
                id=order_id,
                customer_id=customer.id,
                status="placed",
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                tax=tax,
                total=total,
                delivery_address=delivery_address,
                notes=notes,
                idempotency_key=idempotency_key,
                source_agent="whatsapp-agent",
            )
            session.add(order)
            for oi in order_items:
                oi.order_id = order.id
                session.add(oi)
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    from_status=None,
                    to_status="placed",
                    source="agent",
                )
            )
            customer.orders_count += 1
            customer.last_order_at = datetime.now(timezone.utc)

            outbox_payload = {
                "order_id": str(order_id),
                "tenant_id": str(tenant_id),
                "status": "placed",
                "customer_phone_hash": phone_hash(customer_phone),
                "idempotency_key": idempotency_key,
                "placed_at": datetime.now(timezone.utc).isoformat(),
            }
            session.add(RoutingOutbox(action="order_created", payload=outbox_payload))
            await session.commit()

            from app.core.read_cache import invalidate_prefix

            await invalidate_prefix(f"api:board:{tenant_id}")

            return {"order_id": str(order_id), "total": float(total), "status": "placed"}

    async def update_status(
        self,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID,
        new_status: str,
        *,
        changed_by: uuid.UUID | None = None,
        source: str = "dashboard",
        cancellation_reason: str | None = None,
    ) -> dict:
        session = await get_tenant_session(tenant_id)
        async with session:
            order = await session.get(Order, order_id)
            if not order:
                raise ValueError("Order not found")
            allowed = ORDER_STATUSES.get(order.status, [])
            if new_status not in allowed:
                raise ValueError(f"Cannot transition from {order.status} to {new_status}")

            old_status = order.status
            order.status = new_status
            if new_status == "accepted":
                order.accepted_at = datetime.now(timezone.utc)
            elif new_status == "delivered":
                order.delivered_at = datetime.now(timezone.utc)
            if new_status == "cancelled" and cancellation_reason:
                order.cancellation_reason = cancellation_reason

            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    from_status=old_status,
                    to_status=new_status,
                    changed_by=changed_by,
                    source=source,
                )
            )
            session.add(
                RoutingOutbox(
                    action="status_changed",
                    payload={
                        "order_id": str(order_id),
                        "tenant_id": str(tenant_id),
                        "status": new_status,
                        "idempotency_key": order.idempotency_key,
                    },
                )
            )
            await session.commit()
            return {"order_id": str(order_id), "status": new_status}

    async def get_order(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> dict | None:
        session = await get_tenant_session(tenant_id)
        async with session:
            order = await session.get(Order, order_id)
            if not order:
                return None
            items_result = await session.execute(
                select(OrderItem).where(OrderItem.order_id == order_id)
            )
            items = items_result.scalars().all()
            return {
                "id": str(order.id),
                "status": order.status,
                "total": float(order.total),
                "subtotal": float(order.subtotal),
                "delivery_address": order.delivery_address,
                "placed_at": order.placed_at.isoformat(),
                "items": [
                    {
                        "name": i.item_name_snapshot,
                        "quantity": i.quantity,
                        "unit_price": float(i.unit_price_snapshot),
                        "line_total": float(i.line_total),
                    }
                    for i in items
                ],
            }


order_routing = OrderRoutingService()
