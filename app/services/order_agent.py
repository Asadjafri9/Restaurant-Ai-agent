import asyncio
import json
import logging
import re
import time

from app.config.settings import settings
from app.services.agent.prompts import build_system_prompt
from app.services.catalog_service import get_menu_by_slug, get_menus_prompt_cached, list_active_restaurants
from app.services.llm_client import generate_reply, provider_label
from app.services.order_routing import order_routing
from app.services.session_service import get_session_async, reset_session_async, save_session_async

logger = logging.getLogger(__name__)

FAST_GREETINGS = frozenset(
    {"hi", "hello", "hey", "hii", "hola", "salam", "aoa", "assalamualaikum", "asalamualaikum"}
)

ORDER_JSON_PATTERN = re.compile(
    r"\[ORDER_JSON\]\s*(\{.*?\})\s*\[/ORDER_JSON\]",
    re.DOTALL,
)


def _strip_order_json(text: str) -> tuple[str, dict | None]:
    match = ORDER_JSON_PATTERN.search(text)
    if not match:
        return text.strip(), None
    customer_text = ORDER_JSON_PATTERN.sub("", text).strip()
    try:
        return customer_text, json.loads(match.group(1))
    except json.JSONDecodeError:
        return customer_text, None


async def _persist_order(phone: str, order: dict) -> None:
    slug = order.get("restaurant", "").lower().replace(" ", "")
    slug_map = {"kababjees": "kababjees", "kfc": "kfc"}
    slug = slug_map.get(slug, slug)
    tenant_id, catalog = await get_menu_by_slug(slug, force_refresh=True)
    if not tenant_id:
        logger.warning("No tenant for restaurant %s — order kept in session only", slug)
        return
    catalog_by_name = {i["name"].lower(): i for i in catalog}
    items = []
    for item in order.get("items", []):
        name = item.get("item", "")
        cat = catalog_by_name.get(name.lower())
        if cat:
            items.append(
                {
                    "name": cat["name"],
                    "quantity": int(item.get("quantity", 1)),
                    "unit_price": cat["price"],
                    "menu_item_id": cat.get("tenant_item_id"),
                }
            )
    if not items:
        logger.warning("No valid menu items for order (slug=%s)", slug)
        return
    idem = f"{phone}:{slug}:{order.get('customer_name')}:{order.get('address')}"
    result = await order_routing.create_order(
        tenant_id,
        customer_phone=phone,
        customer_name=order.get("customer_name", ""),
        delivery_address=order.get("address", ""),
        items=items,
        idempotency_key=idem,
    )
    from app.services.provisioning import enqueue_job
    from app.services.realtime import publish_order_event

    await enqueue_job("sync_outboxes", {"tenant_id": str(tenant_id)})
    await publish_order_event(
        tenant_id,
        {"type": "order_created", "order_id": result["order_id"], "status": "placed"},
    )
    logger.info("Order persisted: %s", result)


def _fast_greeting(restaurants: list[dict]) -> str:
    if not restaurants:
        return (
            "Hello! Welcome to our ordering service.\n\n"
            "No restaurants are available right now. Please try again shortly."
        )
    names = [r["name"] for r in restaurants]
    if len(names) == 1:
        list_text = names[0]
    elif len(names) == 2:
        list_text = f"{names[0]} and {names[1]}"
    else:
        list_text = ", ".join(names[:-1]) + f", and {names[-1]}"
    return (
        f"Hello! Welcome to our ordering service.\n\n"
        f"We have {list_text}. Which restaurant would you like to order from?"
    )


async def process_order_message_async(phone: str, user_message: str) -> str:
    t0 = time.perf_counter()
    normalized = user_message.strip().lower()
    if normalized in {"reset", "start over", "restart", "new order"}:
        await reset_session_async(phone)

    session, menus, restaurants = await asyncio.gather(
        get_session_async(phone),
        get_menus_prompt_cached(force_refresh=normalized in {"reset", "start over", "restart", "new order"}),
        list_active_restaurants(),
    )

    if normalized in FAST_GREETINGS and not session.history:
        reply = _fast_greeting(restaurants)
        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [reply]},
        ]
        asyncio.create_task(save_session_async(session))
        logger.info("Fast greeting for %s in %.2fs", phone[:6] + "***", time.perf_counter() - t0)
        return reply

    system = build_system_prompt(menus) + """

WHEN ORDER IS CONFIRMED (customer said YES), append at end:
[ORDER_JSON]
{"restaurant": "slug", "customer_name": "...", "address": "...", "items": [{"item": "...", "quantity": 1}]}
[/ORDER_JSON]

Use exact item names and prices from the LIVE MENUS section above. Never invent items.
"""
    history = []
    for h in session.history:
        role = "user" if h.get("role") == "user" else "model"
        parts = h.get("parts", [])
        text = parts[0] if parts else ""
        history.append({"role": role, "parts": [text]})

    try:
        raw_text = await generate_reply(system, history, user_message)
        if not raw_text:
            return settings.ai_fallback_message

        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [raw_text[:500]]},
        ] + session.history[-18:]

        customer_reply, order = _strip_order_json(raw_text)
        if order:
            order["phone"] = phone
            session.confirmed_orders.append(order)
            asyncio.create_task(_persist_order(phone, order))

        asyncio.create_task(save_session_async(session))
        logger.info(
            "%s reply for %s in %.2fs",
            provider_label(),
            phone[:6] + "***",
            time.perf_counter() - t0,
        )
        return customer_reply or settings.ai_fallback_message
    except Exception as exc:
        err = str(exc)
        if "429" in err or "ResourceExhausted" in err or "quota" in err.lower():
            logger.warning("LLM quota exceeded, using fallback reply")
            if normalized in FAST_GREETINGS:
                return _fast_greeting(restaurants)
        logger.exception("Order agent failed after %.2fs", time.perf_counter() - t0)
        return settings.ai_fallback_message


def process_order_message(phone: str, user_message: str) -> str:
    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, process_order_message_async(phone, user_message)).result(
                timeout=60
            )
    except RuntimeError:
        return asyncio.run(process_order_message_async(phone, user_message))
