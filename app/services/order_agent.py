import asyncio
import hashlib
import json
import logging
import re
import time

from app.config.settings import settings
from app.core.tenant_ids import TENANT_IDS
from app.services.agent.prompts import build_system_prompt
from app.services.catalog_service import format_menu_text, get_menu_by_slug, list_active_restaurants
from app.services.llm_client import generate_reply, provider_label
from app.services.order_routing import order_routing
from app.services.session_service import get_session_async, reset_session_async, save_session_async

logger = logging.getLogger(__name__)

FAST_GREETINGS = frozenset(
    {"hi", "hello", "hey", "hii", "hola", "salam", "aoa", "assalamualaikum", "asalamualaikum"}
)
MENU_KEYWORDS = frozenset({"menu", "show menu", "see menu", "full menu", "what's on the menu", "whats on the menu"})
YES_WORDS = frozenset({"yes", "y", "yeah", "yep", "confirm", "ok", "okay", "done", "place order", "confirmed"})
NO_WORDS = frozenset({"no", "n", "nope", "change", "cancel", "wrong"})

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


def _resolve_slug(text: str, restaurants: list[dict]) -> str | None:
    lower = text.lower()
    # Match longer slugs first (e.g. kababjees before kfc)
    for r in sorted(restaurants, key=lambda x: len(x["slug"]), reverse=True):
        if r["slug"] in lower or r["name"].lower() in lower:
            return r["slug"]
    # Common aliases
    if "kabab" in lower or "kababjee" in lower:
        return "kababjees"
    if "kfc" in lower or "kentucky" in lower:
        return "kfc"
    return None


def _apply_restaurant_choice(session, slug: str) -> bool:
    """Set active restaurant; returns True if customer switched from another."""
    switched = bool(session.active_tenant_slug and session.active_tenant_slug != slug)
    session.active_tenant_slug = slug
    session.active_tenant_id = str(TENANT_IDS.get(slug, ""))
    session.state = "ordering"
    if switched:
        session.history = []
    return switched


def _update_session_from_message(session, user_message: str, restaurants: list[dict]) -> tuple[str | None, bool]:
    """Update session state. Returns (slug, switched) if user picked/switched restaurant."""
    normalized = user_message.strip().lower()
    if normalized in {"reset", "start over", "restart", "new order"}:
        session.active_tenant_slug = None
        session.active_tenant_id = None
        session.state = "greeting"
        session.history = []
        return None, False

    slug = _resolve_slug(user_message, restaurants)
    if slug:
        switched = _apply_restaurant_choice(session, slug)
        return slug, switched

    if normalized in YES_WORDS and session.state in ("ordering", "confirming"):
        session.state = "confirming"
    elif normalized in NO_WORDS:
        session.state = "ordering"
    return None, False


async def _menu_block_for_session(session, restaurants: list[dict], user_message: str) -> str:
    if session.active_tenant_slug:
        _, items = await get_menu_by_slug(session.active_tenant_slug, force_refresh=True)
        name = next(
            (r["name"] for r in restaurants if r["slug"] == session.active_tenant_slug),
            session.active_tenant_slug,
        )
        if items:
            return f"{name} ({session.active_tenant_slug}):\n{format_menu_text(items)}"
        return f"{name} ({session.active_tenant_slug}): (menu empty)"

    lines = [f"- {r['name']} (slug: {r['slug']})" for r in restaurants]
    return "Available restaurants:\n" + "\n".join(lines)


async def _reply_with_menu(slug: str, restaurants: list[dict], switched: bool) -> str | None:
    """Deterministic menu reply when customer picks a restaurant — no LLM needed."""
    _, items = await get_menu_by_slug(slug, force_refresh=True)
    name = next((r["name"] for r in restaurants if r["slug"] == slug), slug)
    if not items:
        return f"Sorry, the {name} menu is empty right now. Please try again later or pick another restaurant."
    intro = f"Sure, switching to {name}!" if switched else f"Great choice — {name}!"
    menu = format_menu_text(items)
    return f"{intro}\n\n{menu}\n\nWhat would you like to order?"


async def _persist_order(phone: str, order: dict, session) -> dict | None:
    slug = (order.get("restaurant") or session.active_tenant_slug or "").lower().replace(" ", "")
    for r_slug in ("kababjees", "kfc"):
        if r_slug in slug:
            slug = r_slug
            break

    tenant_id, catalog = await get_menu_by_slug(slug, force_refresh=True)
    if not tenant_id:
        logger.warning("No tenant for restaurant %s", slug)
        return None

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
        logger.warning("No valid items for order slug=%s items=%s", slug, order.get("items"))
        return None

    items_key = hashlib.sha256(
        json.dumps(order.get("items", []), sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    idem = f"{phone}:{slug}:{order.get('customer_name', '')}:{items_key}"
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
    logger.info("Order persisted: %s tenant=%s", result, slug)
    session.state = "done"
    session.active_tenant_slug = slug
    return result


def _fast_greeting(restaurants: list[dict]) -> str:
    if not restaurants:
        return "Hello! No restaurants are available right now. Please try again shortly."
    names = [r["name"] for r in restaurants]
    if len(names) == 2:
        list_text = f"{names[0]} or {names[1]}"
    else:
        list_text = ", ".join(names)
    return (
        f"Hello! Welcome to our food ordering service.\n\n"
        f"We have {list_text}. Which restaurant would you like to order from?"
    )


async def process_order_message_async(phone: str, user_message: str) -> str:
    t0 = time.perf_counter()
    normalized = user_message.strip().lower()

    if normalized in {"reset", "start over", "restart", "new order"}:
        await reset_session_async(phone)

    session, restaurants = await asyncio.gather(
        get_session_async(phone),
        list_active_restaurants(),
    )

    chosen_slug, switched = _update_session_from_message(session, user_message, restaurants)

    # Deterministic reply when customer picks or switches restaurant
    if chosen_slug:
        menu_reply = await _reply_with_menu(chosen_slug, restaurants, switched)
        if menu_reply:
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [menu_reply]},
            ] + session.history[-14:]
            await save_session_async(session)
            logger.info("Menu reply for %s slug=%s in %.2fs", phone[:6] + "***", chosen_slug, time.perf_counter() - t0)
            return menu_reply

    if any(k in normalized for k in MENU_KEYWORDS) and session.active_tenant_slug:
        menu_reply = await _reply_with_menu(session.active_tenant_slug, restaurants, False)
        if menu_reply:
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [menu_reply]},
            ] + session.history[-14:]
            await save_session_async(session)
            return menu_reply

    if normalized in FAST_GREETINGS and not session.history:
        reply = _fast_greeting(restaurants)
        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [reply]},
        ]
        session.state = "greeting"
        await save_session_async(session)
        logger.info("Fast greeting for %s in %.2fs", phone[:6] + "***", time.perf_counter() - t0)
        return reply

    menu_block = await _menu_block_for_session(session, restaurants, user_message)
    active_name = None
    if session.active_tenant_slug:
        active_name = next(
            (r["name"] for r in restaurants if r["slug"] == session.active_tenant_slug),
            session.active_tenant_slug,
        )

    system = build_system_prompt(
        restaurants=restaurants,
        menu_block=menu_block,
        active_restaurant=active_name,
        active_slug=session.active_tenant_slug,
        state=session.state,
    )

    history = []
    for h in session.history:
        role = "user" if h.get("role") == "user" else "model"
        parts = h.get("parts", [])
        text = parts[0] if parts else ""
        # Strip any leaked ORDER_JSON from history shown to model
        text = ORDER_JSON_PATTERN.sub("", text).strip()
        if text:
            history.append({"role": role, "parts": [text]})

    try:
        raw_text = await generate_reply(system, history, user_message)
        if not raw_text:
            return settings.ai_fallback_message

        customer_reply, order = _strip_order_json(raw_text)

        if order:
            order["phone"] = phone
            if not order.get("restaurant") and session.active_tenant_slug:
                order["restaurant"] = session.active_tenant_slug
            try:
                result = await _persist_order(phone, order, session)
                if result:
                    customer_reply = (
                        f"Order confirmed! Total: Rs {result['total']:.0f}\n"
                        f"Order ID: #{result['order_id'][:8].upper()}\n"
                        f"Estimated delivery: 45-60 minutes.\n\n"
                        f"Reply 'new order' to order again."
                    )
                    session.confirmed_orders.append(order)
                else:
                    customer_reply = (
                        "Sorry, I could not place your order — some items may be unavailable. "
                        "Please check the menu and try again."
                    )
            except Exception:
                logger.exception("Order persist failed for %s", phone[:6] + "***")
                customer_reply = (
                    "Sorry, there was a problem placing your order. Please try again in a moment."
                )
        elif normalized in YES_WORDS and session.state == "confirming":
            customer_reply = (
                "I still need your order details to confirm. "
                "Please tell me the items, your name, and delivery address."
            )

        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [customer_reply[:500]]},
        ] + session.history[-16:]

        if "YES" in raw_text.upper() or "confirm" in raw_text.lower():
            session.state = "confirming"
        elif order or session.state == "done":
            pass
        elif session.active_tenant_slug:
            session.state = "ordering"

        await save_session_async(session)
        logger.info(
            "%s reply for %s state=%s in %.2fs",
            provider_label(),
            phone[:6] + "***",
            session.state,
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
