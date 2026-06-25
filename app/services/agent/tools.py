import json
import logging
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.services.catalog_service import get_menu_by_slug, list_active_restaurants
from app.services.order_routing import order_routing

logger = logging.getLogger(__name__)


class OrderItemInput(BaseModel):
    name: str
    quantity: int = Field(ge=1, le=50)
    unit_price: Decimal


class CreateOrderInput(BaseModel):
    restaurant_slug: str
    items: list[OrderItemInput]
    customer_name: str
    delivery_address: str
    customer_phone: str
    notes: str | None = None
    idempotency_key: str


async def tool_list_restaurants() -> list[dict]:
    return await list_active_restaurants()


async def tool_get_menu(restaurant_slug: str) -> dict:
    tenant_id, items = await get_menu_by_slug(restaurant_slug)
    if not tenant_id:
        return {"error": "Restaurant not found", "items": []}
    return {"restaurant_slug": restaurant_slug, "items": items}


async def tool_create_order(data: CreateOrderInput, active_tenant_id: uuid.UUID | None) -> dict:
    tenant_id, catalog = await get_menu_by_slug(data.restaurant_slug)
    if not tenant_id:
        return {"error": "Restaurant not found"}
    if active_tenant_id and tenant_id != active_tenant_id:
        return {"error": "Cannot order from a different restaurant in this conversation"}

    catalog_by_name = {i["name"].lower(): i for i in catalog}
    validated_items = []
    for item in data.items:
        cat_item = catalog_by_name.get(item.name.lower())
        if not cat_item:
            return {"error": f"Item not available: {item.name}"}
        price = Decimal(str(cat_item["price"]))
        validated_items.append(
            {
                "name": cat_item["name"],
                "quantity": item.quantity,
                "unit_price": price,
                "menu_item_id": cat_item.get("tenant_item_id"),
            }
        )

    result = await order_routing.create_order(
        tenant_id,
        customer_phone=data.customer_phone,
        customer_name=data.customer_name,
        delivery_address=data.delivery_address,
        items=validated_items,
        idempotency_key=data.idempotency_key,
        notes=data.notes,
    )
    from app.services.provisioning import enqueue_job
    from app.services.realtime import publish_order_event

    await enqueue_job("sync_outboxes", {"tenant_id": str(tenant_id)})
    await publish_order_event(
        tenant_id,
        {"type": "order_created", "order_id": result["order_id"], "status": "placed"},
    )
    return result


async def tool_get_order_status(order_id: str, tenant_id: uuid.UUID) -> dict:
    data = await order_routing.get_order(tenant_id, uuid.UUID(order_id))
    if not data:
        return {"error": "Order not found"}
    return {"order_id": order_id, "status": data["status"]}
