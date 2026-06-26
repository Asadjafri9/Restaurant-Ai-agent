import asyncio
import hashlib
import json
import logging
import re
import time

from app.core.tenant_ids import TENANT_IDS
from app.services.agent.prompts import build_system_prompt
from app.services.catalog_service import format_menu_text, get_menu_by_slug, list_active_restaurants
from app.services.i18n import detect_language, msg
from app.services.llm_client import LlmRateLimitError, generate_reply, provider_label
from app.services.order_context import (
    bot_asked_for_more_items,
    clear_pending_order,
    extract_order_items,
    fix_name_transcript,
    format_order_summary,
    format_pending_items_list,
    is_declining_more_items,
    is_done_adding_items,
    is_order_correction_message,
    match_catalog_item,
    order_from_session,
    pending_items_changed,
    pending_order_complete,
    update_pending_from_message,
)
from app.services.order_routing import order_routing
from app.services.session_service import get_session_async, reset_session_async, save_session_async
from app.services.voice_text import (
    URDU_YES_MARKERS,
    is_menu_request,
    is_mid_order_detail_reply,
    is_thank_you_message,
    message_mentions_items,
    normalize_confirm_transcript,
    normalize_user_text as _normalize_user_text,
    resolve_restaurant_slug as _resolve_slug,
    restaurant_named_in_text,
    should_show_restaurant_menu,
)

logger = logging.getLogger(__name__)

FAST_GREETINGS = frozenset(
    {"hi", "hello", "hey", "hii", "hola", "salam", "aoa", "assalamualaikum", "asalamualaikum"}
)
MENU_KEYWORDS = frozenset({"menu", "show menu", "see menu", "full menu", "what's on the menu", "whats on the menu"})
YES_WORDS = frozenset(
    {
        "yes",
        "y",
        "yeah",
        "yep",
        "confirm",
        "ok",
        "okay",
        "done",
        "place order",
        "confirmed",
        "haan",
        "han",
        "hann",
        "ji",
        "jee",
        "theek",
        "bilkul",
        "agreed",
        "correct",
        "sahi",
    }
)
YES_PHRASES = (
    "han kardo",
    "haan kardo",
    "han kar do",
    "haan kar do",
    "confirm karo",
    "confirm kar do",
    "confirm kardo",
    "theek hai",
    "ok hai",
    "ji haan",
    "ji han",
    "done hai",
    "yes please",
    "go ahead",
    "place it",
)
YES_PHRASES_LONG = (
    "han kardo",
    "haan kardo",
    "han kar do",
    "haan kar do",
    "confirm kardo",
    "confirm kar do",
    "theek hai",
    "ji haan",
    "yes confirm",
    "confirm karo",
)
NO_WORDS = frozenset({"no", "n", "nope", "change", "cancel", "wrong", "nahi", "na", "mat"})

ORDER_JSON_PATTERN = re.compile(
    r"\[ORDER_JSON\]\s*(\{.*?\})\s*\[/ORDER_JSON\]",
    re.DOTALL,
)
CONFIRM_PHRASES = (
    "reply yes",
    "yes to confirm",
    "confirm or no",
    "reply yes to confirm",
    "yes likhein",
    "confirm karne",
    "han likhein",
    "haan likhein",
    "yes bhejein",
    "confirm karein",
    "theek hai to",
    "order confirm",
    "confirm karoon",
    "confirm karna",
)
CONFIRM_SUMMARY_MARKERS = ("total", "rs ", "rs.", "grand total", "order summary", "kul ")
CONFIRM_ASK_MARKERS = (
    "confirm karne",
    "yes likhein",
    "yes to confirm",
    "han kardo likhein",
    "reply yes",
    "confirm karein",
    "confirm karoon",
    "order summary",
)
ORDER_DONE_MARKERS = (
    "order confirmed",
    "order confirm ho gaya",
    "confirm ho gaya",
    "delivery:",
    "delivery ",
    "order id",
    "dobara order",
    "new order",
    "45-60",
)


def _update_session_language(session, user_message: str) -> None:
    """Keep Roman Urdu across short/ambiguous voice replies in the same chat."""
    detected = detect_language(user_message)
    if detected == "roman_ur":
        session.language = "roman_ur"
    elif not session.history:
        session.language = detected
    elif session.language != "roman_ur":
        session.language = detected


def _is_yes_message(text: str) -> bool:
    if any(marker in text for marker in URDU_YES_MARKERS):
        return True
    raw_lower = text.lower()
    if "confirm" in raw_lower and any(
        x in raw_lower for x in ("haan", "han", "yes", "han kardo", "haan kardo", "ہاں", "हाँ")
    ):
        return True
    normalized = _normalize_user_text(text)
    if not normalized:
        return False
    words = normalized.split()
    if len(words) <= 4:
        if normalized in YES_WORDS:
            return True
        if words[0] in YES_WORDS:
            return True
        if any(phrase in normalized for phrase in YES_PHRASES):
            return True
        if re.match(r"^(han|haan|hann|ji|jee|yes|ok|okay|theek|bilkul|confirm)\b", normalized):
            return True
        return False
    return any(phrase in normalized for phrase in YES_PHRASES_LONG)


def _is_no_message(text: str, session=None) -> bool:
    if is_order_correction_message(text):
        return False
    if is_done_adding_items(text):
        return False
    if session and session.pending_items and bot_asked_for_more_items(_last_model_text(session)):
        if is_declining_more_items(text, _last_model_text(session)):
            return False
    normalized = _normalize_user_text(text)
    if not normalized:
        return False
    if normalized in NO_WORDS:
        return True
    return normalized.split()[0] in NO_WORDS


def _last_model_text(session) -> str:
    for h in session.history:
        if h.get("role") == "model":
            parts = h.get("parts") or []
            if parts:
                return str(parts[0])
    return ""


def _conversation_awaiting_confirm(session) -> bool:
    if session.state == "confirming" or session.awaiting_confirm:
        return True
    last = _last_model_text(session)
    if not last:
        return False
    if bot_asked_for_more_items(last):
        return False
    if _looks_like_confirm_prompt(last):
        return True
    lower = last.lower()
    has_summary = any(m in lower for m in CONFIRM_SUMMARY_MARKERS)
    asks_confirm = any(m in lower for m in CONFIRM_ASK_MARKERS)
    return has_summary and asks_confirm


def _order_recently_completed(session) -> bool:
    """True after a placed order — customer saying thanks should get a warm close."""
    if session.state == "done":
        return True
    if session.confirmed_orders:
        return True
    last = _last_model_text(session).lower()
    if any(m in last for m in ORDER_DONE_MARKERS):
        return True
    # Bot showed order summary / asked YES — customer may say shukriya after failed/successful flow
    if session.state in ("confirming", "ordering") and session.pending_customer_name:
        if any(m in last for m in CONFIRM_SUMMARY_MARKERS) or _looks_like_confirm_prompt(last):
            return True
    return False


def _is_confirm_reply(text: str, session, catalog: list[dict] | None = None) -> bool:
    """Broader YES when awaiting confirmation — catches garbled voice 'han kardo'."""
    if is_thank_you_message(text):
        return False
    last_bot = _last_model_text(session)
    if bot_asked_for_more_items(last_bot):
        return False
    if catalog and extract_order_items(text, catalog):
        return False
    if catalog and message_mentions_items(text, catalog):
        return False
    if _is_yes_message(text) and not _looks_like_order_add_message(text):
        if session.state == "confirming" or session.awaiting_confirm or _conversation_awaiting_confirm(session):
            return True
        return False
    if not (
        session.state == "confirming"
        or session.awaiting_confirm
        or _conversation_awaiting_confirm(session)
    ):
        return False
    if _is_no_message(text, session):
        return False
    if _looks_like_order_add_message(text):
        return False
    normalized = _normalize_user_text(normalize_confirm_transcript(text))
    if not normalized or len(normalized.split()) > 8:
        return False
    words = set(normalized.split())
    if words & {"han", "haan", "hann", "yes", "yep", "yeah", "ok", "okay", "ji", "jee", "theek", "bilkul", "confirm", "sahi", "done"}:
        return True
    confirm_phrases = ("han kardo", "haan kardo", "han kar do", "haan kar do", "confirm kardo", "kar do", "place order")
    return any(p in normalized for p in confirm_phrases)


def _looks_like_order_add_message(text: str) -> bool:
    """Voice/text that lists food items — not a bare YES."""
    normalized = _normalize_user_text(text)
    if not normalized:
        return False
    food_tokens = (
        "burger",
        "wings",
        "pepsi",
        "cola",
        "biryani",
        "kabab",
        "zinger",
        "krusher",
        "piece",
        "fries",
        "chicken",
        "karahi",
        "roll",
        "naan",
        "menu",
    )
    if any(t in normalized for t in food_tokens):
        return True
    if "kardo" in normalized and len(normalized.split()) > 3:
        return True
    return False


def _match_catalog_item(name: str, catalog_by_name: dict[str, dict]) -> dict | None:
    """Delegate to shared fuzzy matcher (catalog_by_name kept for tests)."""
    catalog = list(catalog_by_name.values())
    return match_catalog_item(name, catalog)


def _looks_like_confirm_prompt(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in CONFIRM_PHRASES)


def _order_summary_in_reply(text: str) -> bool:
    lower = text.lower()
    has_total = any(m in lower for m in CONFIRM_SUMMARY_MARKERS)
    asks_confirm = any(m in lower for m in CONFIRM_ASK_MARKERS)
    return has_total and asks_confirm


def _strip_order_json(text: str) -> tuple[str, dict | None]:
    match = ORDER_JSON_PATTERN.search(text)
    if not match:
        return text.strip(), None
    customer_text = ORDER_JSON_PATTERN.sub("", text).strip()
    try:
        return customer_text, json.loads(match.group(1))
    except json.JSONDecodeError:
        return customer_text, None


def _apply_restaurant_choice(session, slug: str) -> bool:
    """Set active restaurant; returns True if customer switched from another."""
    switched = bool(session.active_tenant_slug and session.active_tenant_slug != slug)
    session.active_tenant_slug = slug
    session.active_tenant_id = str(TENANT_IDS.get(slug, ""))
    session.state = "ordering"
    if switched:
        session.history = []
        clear_pending_order(session)
    return switched


def _update_session_from_message(session, user_message: str, restaurants: list[dict]) -> tuple[str | None, bool]:
    """Update session state. Returns (slug, switched) if user picked/switched restaurant."""
    normalized = _normalize_user_text(user_message)
    if normalized in {"reset", "start over", "restart", "new order"}:
        session.active_tenant_slug = None
        session.active_tenant_id = None
        session.state = "greeting"
        session.awaiting_confirm = False
        clear_pending_order(session)
        session.history = []
        return None, False

    slug = _resolve_slug(user_message, restaurants)
    if slug:
        switched = _apply_restaurant_choice(session, slug)
        return slug, switched

    awaiting = _conversation_awaiting_confirm(session)
    if (
        _is_confirm_reply(user_message, session)
        and (session.state in ("ordering", "confirming") or awaiting)
        and not bot_asked_for_more_items(_last_model_text(session))
        and not _looks_like_order_add_message(user_message)
    ):
        session.state = "confirming"
    elif _is_no_message(user_message, session):
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


def _menu_already_sent(session) -> bool:
    for h in session.history:
        if h.get("role") != "model":
            continue
        parts = h.get("parts") or []
        if not parts:
            continue
        text = str(parts[0]).lower()
        if "full menu" in text or "poora menu" in text or "here's the menu" in text:
            return True
        if text.count("rs ") >= 3 or text.count("— rs") >= 3:
            return True
    return False


async def _try_serve_catalog_menu(session, user_message: str, restaurants: list[dict]) -> str | None:
    """Serve the real catalog menu — never let the LLM invent items or prices."""
    slug = _resolve_slug(user_message, restaurants) or session.active_tenant_slug
    if not slug:
        return None

    _, catalog_items = await get_menu_by_slug(slug, force_refresh=True)
    if not catalog_items:
        return None

    normalized = _normalize_user_text(user_message)
    menu_intent = (
        is_menu_request(user_message)
        or "menu" in normalized
        or any(k in normalized for k in MENU_KEYWORDS)
    )
    has_items = message_mentions_items(user_message, catalog_items)
    restaurant_named = restaurant_named_in_text(user_message, slug, restaurants)

    if not menu_intent and not (has_items and restaurant_named and not _menu_already_sent(session)):
        return None

    switched = bool(session.active_tenant_slug and session.active_tenant_slug != slug)
    _apply_restaurant_choice(session, slug)
    update_pending_from_message(session, user_message, catalog_items)
    return await _reply_with_menu(slug, restaurants, switched, session.language, session)


async def _reply_with_menu(
    slug: str,
    restaurants: list[dict],
    switched: bool,
    lang: str,
    session=None,
) -> str | None:
    """Deterministic menu reply when customer picks a restaurant — no LLM needed."""
    _, items = await get_menu_by_slug(slug, force_refresh=True)
    name = next((r["name"] for r in restaurants if r["slug"] == slug), slug)
    if not items:
        return msg("menu_empty", lang, name=name)
    intro_key = "menu_intro_switch" if switched else "menu_intro_pick"
    intro = msg(intro_key, lang, name=name)
    menu = format_menu_text(items)
    parts = [intro]
    has_pending = bool(session and session.pending_items)
    if has_pending:
        added = ", ".join(
            f"{int(i.get('quantity', 1))}x {i.get('item', '')}" for i in session.pending_items
        )
        parts.append(msg("menu_item_added", lang, items=added))
    parts.append(msg("menu_full_header", lang, name=name) + "\n" + menu)
    if has_pending:
        parts.append(msg("menu_ask_more", lang))
    else:
        parts.append(msg("menu_ask", lang))
    return "\n\n".join(parts)


async def _reply_after_items_added(
    session,
    lang: str,
    *,
    added_labels: str | None = None,
    corrected: bool = False,
) -> str:
    items_text = format_pending_items_list(session.pending_items)
    parts: list[str] = []
    if corrected:
        parts.append(msg("order_corrected", lang))
    elif added_labels:
        parts.append(msg("items_added_now", lang, items=added_labels))
    parts.append(msg("order_updated", lang, items=items_text))
    return "\n\n".join(parts)


def _labels_for_new_items(before: list[dict], after: list[dict]) -> str:
    before_sig = {i["item"].lower(): int(i.get("quantity", 1)) for i in before}
    labels: list[str] = []
    for item in after:
        key = item["item"].lower()
        qty = int(item.get("quantity", 1))
        prev = before_sig.get(key, 0)
        delta = qty - prev
        if delta > 0:
            labels.append(f"{delta}x {item['item']}")
    return ", ".join(labels)


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

    catalog_by_id = {
        str(i.get("tenant_item_id")): i for i in catalog if i.get("tenant_item_id")
    }
    items = []
    for item in order.get("items", []):
        name = (item.get("item") or item.get("name") or "").strip()
        mid = item.get("menu_item_id")
        cat = None
        if mid and str(mid) in catalog_by_id:
            cat = catalog_by_id[str(mid)]
        if not cat and name:
            cat = match_catalog_item(name, catalog)
        if cat:
            items.append(
                {
                    "name": cat["name"],
                    "quantity": int(item.get("quantity", 1)),
                    "unit_price": cat["price"],
                    "menu_item_id": cat.get("tenant_item_id"),
                }
            )
        elif name and item.get("unit_price") is not None:
            items.append(
                {
                    "name": name,
                    "quantity": int(item.get("quantity", 1)),
                    "unit_price": float(item["unit_price"]),
                    "menu_item_id": mid,
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
    clear_pending_order(session)
    return result


def _fast_greeting(restaurants: list[dict], lang: str) -> str:
    if not restaurants:
        return msg("no_restaurants", lang)
    names = [r["name"] for r in restaurants]
    if len(names) == 2:
        list_text = f"{names[0]} or {names[1]}"
    else:
        list_text = ", ".join(names)
    return msg("greeting", lang, restaurants=list_text)


def _smart_fallback_reply(session, restaurants: list[dict], catalog_items: list[dict]) -> str:
    """Useful reply when LLM is rate-limited — avoid generic 'can't respond'."""
    lang = session.language
    if session.awaiting_confirm and pending_order_complete(session):
        return format_order_summary(session, catalog_items, lang)
    if session.pending_items:
        if not session.pending_customer_name:
            return msg("ask_name", lang)
        if not session.pending_address:
            return msg("ask_address", lang)
        return format_order_summary(session, catalog_items, lang)
    if not session.history:
        return _fast_greeting(restaurants, lang)
    return msg("rate_limit", lang)


async def _extract_order_on_confirm(
    phone: str,
    user_message: str,
    session,
    restaurants: list[dict],
    history: list[dict],
    menu_block: str,
) -> tuple[str | None, dict | None]:
    """Force ORDER_JSON extraction when the customer replies YES."""
    active_name = None
    if session.active_tenant_slug:
        active_name = next(
            (r["name"] for r in restaurants if r["slug"] == session.active_tenant_slug),
            session.active_tenant_slug,
        )
    confirm_system = (
        build_system_prompt(
            restaurants=restaurants,
            menu_block=menu_block,
            active_restaurant=active_name,
            active_slug=session.active_tenant_slug,
            state="confirming",
            language=session.language,
            pending_name=session.pending_customer_name,
            pending_address=session.pending_address,
            pending_items=session.pending_items,
        )
        + "\n\nThe customer just confirmed their order (YES / haan / han kardo / etc.). "
        "Respond with ONLY the ORDER_JSON block — no other text. "
        "Use exact menu item names from the menu above and details from conversation history."
    )
    raw_text = await generate_reply(confirm_system, history, user_message)
    _, order = _strip_order_json(raw_text or "")
    if not order:
        retry_system = (
            confirm_system
            + "\n\nIMPORTANT: Build ORDER_JSON from the full conversation — items, customer name, "
            "and delivery address already mentioned by the customer. Output ONLY [ORDER_JSON]...[/ORDER_JSON]."
        )
        raw_text = await generate_reply(retry_system, history, user_message)
        _, order = _strip_order_json(raw_text or "")
    if not order:
        order = order_from_session(session)
    if order:
        order["customer_name"] = order.get("customer_name") or session.pending_customer_name or ""
        order["address"] = order.get("address") or session.pending_address or ""
        if not order.get("items") and session.pending_items:
            order["items"] = list(session.pending_items)
    if not order:
        return None, None
    order["phone"] = phone
    if not order.get("restaurant") and session.active_tenant_slug:
        order["restaurant"] = session.active_tenant_slug
    return raw_text, order


async def _finalize_order(
    phone: str, order: dict, session, *, persist_fail_message: str
) -> str:
    lang = session.language
    try:
        result = await _persist_order(phone, order, session)
        if result:
            session.confirmed_orders.append(order)
            return msg(
                "order_confirmed",
                lang,
                total=result["total"],
                order_id=result["order_id"][:8].upper(),
            )
        return persist_fail_message
    except Exception:
        logger.exception("Order persist failed for %s", phone[:6] + "***")
        return msg("persist_error", lang)


async def process_order_message_async(phone: str, user_message: str) -> str:
    t0 = time.perf_counter()
    user_message = fix_name_transcript(user_message)
    user_message = normalize_confirm_transcript(user_message)
    normalized = _normalize_user_text(user_message)

    if normalized in {"reset", "start over", "restart", "new order"}:
        await reset_session_async(phone)

    session, restaurants = await asyncio.gather(
        get_session_async(phone),
        list_active_restaurants(),
    )
    catalog_items: list[dict] = []

    _update_session_language(session, user_message)

    # Thanks / shukriya — before YES detection (shukriya contains "ji" as substring)
    if is_thank_you_message(user_message):
        if _order_recently_completed(session):
            reply = msg("thank_you_closing", session.language)
            session.state = "done"
            session.awaiting_confirm = False
        else:
            reply = msg("thank_you_ack", session.language)
        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [reply]},
        ] + session.history[-16:]
        await save_session_async(session)
        logger.info("Thank-you reply for %s in %.2fs", phone[:6] + "***", time.perf_counter() - t0)
        return reply

    # Restaurant pick → show ONLY that restaurant's menu (before session state is updated)
    detected_slug = _resolve_slug(user_message, restaurants)
    if detected_slug:
        pick_switched = bool(session.active_tenant_slug and session.active_tenant_slug != detected_slug)
        _, catalog_items = await get_menu_by_slug(detected_slug, force_refresh=True)
        has_items = bool(catalog_items) and message_mentions_items(user_message, catalog_items)
        wants_menu = is_menu_request(user_message) or should_show_restaurant_menu(
            user_message, detected_slug, session, catalog_items
        )
        if wants_menu or (
            has_items and restaurant_named_in_text(user_message, detected_slug, restaurants)
        ):
            _apply_restaurant_choice(session, detected_slug)
            update_pending_from_message(session, user_message, catalog_items)
            menu_reply = await _reply_with_menu(
                detected_slug, restaurants, pick_switched, session.language, session
            )
            if menu_reply:
                session.history = [
                    {"role": "user", "parts": [user_message]},
                    {"role": "model", "parts": [menu_reply]},
                ] + session.history[-14:]
                await save_session_async(session)
                logger.info(
                    "Menu reply for %s slug=%s in %.2fs",
                    phone[:6] + "***",
                    detected_slug,
                    time.perf_counter() - t0,
                )
                return menu_reply

    chosen_slug, switched = _update_session_from_message(session, user_message, restaurants)
    if session.active_tenant_slug:
        _, catalog_items = await get_menu_by_slug(session.active_tenant_slug, force_refresh=True)
    is_yes = _is_confirm_reply(user_message, session, catalog_items)
    awaiting_confirm = _conversation_awaiting_confirm(session)

    detected_for_menu = _resolve_slug(user_message, restaurants)
    if detected_for_menu and detected_for_menu != session.active_tenant_slug:
        _apply_restaurant_choice(session, detected_for_menu)
    menu_slug = detected_for_menu or session.active_tenant_slug
    if is_menu_request(user_message) and menu_slug:
        if not session.active_tenant_slug:
            _apply_restaurant_choice(session, menu_slug)
        _, catalog_items = await get_menu_by_slug(menu_slug, force_refresh=True)
        update_pending_from_message(session, user_message, catalog_items)
        menu_reply = await _reply_with_menu(menu_slug, restaurants, False, session.language, session)
        if menu_reply:
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [menu_reply]},
            ] + session.history[-14:]
            await save_session_async(session)
            logger.info("Menu request for %s slug=%s in %.2fs", phone[:6] + "***", menu_slug, time.perf_counter() - t0)
            return menu_reply

    if any(k in normalized for k in MENU_KEYWORDS) and session.active_tenant_slug:
        _, catalog_items = await get_menu_by_slug(session.active_tenant_slug, force_refresh=True)
        update_pending_from_message(session, user_message, catalog_items)
        menu_reply = await _reply_with_menu(
            session.active_tenant_slug, restaurants, False, session.language, session
        )
        if menu_reply:
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [menu_reply]},
            ] + session.history[-14:]
            await save_session_async(session)
            return menu_reply

    if normalized in FAST_GREETINGS and not session.history:
        reply = _fast_greeting(restaurants, session.language)
        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [reply]},
        ]
        session.state = "greeting"
        await save_session_async(session)
        logger.info("Fast greeting for %s in %.2fs", phone[:6] + "***", time.perf_counter() - t0)
        return reply

    # Confirm YES before mutating pending order from a short voice transcript
    if is_yes and (session.state == "confirming" or awaiting_confirm or session.awaiting_confirm):
        if session.active_tenant_slug:
            _, catalog_items = await get_menu_by_slug(session.active_tenant_slug, force_refresh=True)
        order = order_from_session(session)
        if order:
            order["phone"] = phone
            persist_fail_message = msg("persist_fail", session.language)
            customer_reply = await _finalize_order(
                phone, order, session, persist_fail_message=persist_fail_message
            )
            session.awaiting_confirm = False
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [customer_reply[:2000]]},
            ] + session.history[-16:]
            if session.state != "done":
                session.state = "confirming"
            await save_session_async(session)
            logger.info("Early confirm for %s placed=%s in %.2fs", phone[:6] + "***", session.state == "done", time.perf_counter() - t0)
            return customer_reply

    menu_block = await _menu_block_for_session(session, restaurants, user_message)
    pending_snapshot = list(session.pending_items)
    order_correction = is_order_correction_message(user_message)
    if session.active_tenant_slug and not is_thank_you_message(user_message):
        _, catalog_items = await get_menu_by_slug(session.active_tenant_slug, force_refresh=True)
        update_pending_from_message(session, user_message, catalog_items)
        logger.info(
            "Pending order for %s: name=%s addr=%s items=%s",
            phone[:6] + "***",
            session.pending_customer_name,
            session.pending_address,
            session.pending_items,
        )

    if (
        session.active_tenant_slug
        and session.pending_items
        and (
            pending_items_changed(pending_snapshot, session.pending_items)
            or order_correction
        )
        and not is_yes
        and not is_menu_request(user_message)
        and not is_done_adding_items(user_message)
        and not is_declining_more_items(user_message, _last_model_text(session))
    ):
        added = None if order_correction else _labels_for_new_items(pending_snapshot, session.pending_items)
        reply = await _reply_after_items_added(
            session,
            session.language,
            added_labels=added or None,
            corrected=order_correction,
        )
        session.state = "ordering"
        session.awaiting_confirm = False
        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [reply]},
        ] + session.history[-16:]
        await save_session_async(session)
        logger.info("Items added for %s in %.2fs", phone[:6] + "***", time.perf_counter() - t0)
        return reply

    menu_reply = await _try_serve_catalog_menu(session, user_message, restaurants)
    if menu_reply:
        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [menu_reply]},
        ] + session.history[-14:]
        await save_session_async(session)
        logger.info("Catalog menu for %s slug=%s in %.2fs", phone[:6] + "***", session.active_tenant_slug, time.perf_counter() - t0)
        return menu_reply

    # Customer done adding items — show summary if we have everything
    last_bot = _last_model_text(session)
    done_adding = is_done_adding_items(user_message) or (
        session.pending_items and is_declining_more_items(user_message, last_bot)
    )
    if done_adding and session.pending_items:
        if pending_order_complete(session):
            customer_reply = format_order_summary(session, catalog_items, session.language)
            session.state = "confirming"
            session.awaiting_confirm = True
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [customer_reply]},
            ] + session.history[-16:]
            await save_session_async(session)
            logger.info("Order summary (done adding) for %s", phone[:6] + "***")
            return customer_reply
        missing = []
        if not session.pending_customer_name:
            missing.append("name")
        if not session.pending_address:
            missing.append("address")
        if missing:
            if "name" in missing:
                reply = msg("ask_name", session.language)
            else:
                reply = msg("ask_address", session.language)
            session.history = [
                {"role": "user", "parts": [user_message]},
                {"role": "model", "parts": [reply]},
            ] + session.history[-16:]
            await save_session_async(session)
            return reply

    active_name = None
    if session.active_tenant_slug:
        active_name = next(
            (r["name"] for r in restaurants if r["slug"] == session.active_tenant_slug),
            session.active_tenant_slug,
        )

    collecting_details = (
        bool(session.active_tenant_slug)
        and session.state == "ordering"
        and is_mid_order_detail_reply(user_message)
        and not is_menu_request(user_message)
    )

    system = build_system_prompt(
        restaurants=restaurants,
        menu_block=menu_block,
        active_restaurant=active_name,
        active_slug=session.active_tenant_slug,
        state=session.state,
        language=session.language,
        collecting_details=collecting_details,
        pending_name=session.pending_customer_name,
        pending_address=session.pending_address,
        pending_items=session.pending_items,
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

    persist_fail_message = msg("persist_fail", session.language)

    try:
        order = None
        customer_reply = ""

        if is_yes and (session.state == "confirming" or awaiting_confirm):
            if session.state != "confirming":
                session.state = "confirming"
            logger.info("Confirm yes detected for %s (awaiting=%s)", phone[:6] + "***", awaiting_confirm)
            order = order_from_session(session)
            if order:
                order["phone"] = phone
                customer_reply = await _finalize_order(
                    phone, order, session, persist_fail_message=persist_fail_message
                )
                session.awaiting_confirm = False
            else:
                _, order = await _extract_order_on_confirm(
                    phone, user_message, session, restaurants, history, menu_block
                )
                if order:
                    customer_reply = await _finalize_order(
                        phone, order, session, persist_fail_message=persist_fail_message
                    )
                    session.awaiting_confirm = False
                else:
                    customer_reply = msg("confirm_fail", session.language)
                    session.awaiting_confirm = True
        else:
            menu_reply = await _try_serve_catalog_menu(session, user_message, restaurants)
            if menu_reply:
                customer_reply = menu_reply
                order = None
            else:
                raw_text = await generate_reply(system, history, user_message)
                if not raw_text:
                    return _smart_fallback_reply(session, restaurants, catalog_items)

                customer_reply, order = _strip_order_json(raw_text)

                if order:
                    order["phone"] = phone
                    if not order.get("restaurant") and session.active_tenant_slug:
                        order["restaurant"] = session.active_tenant_slug
                    customer_reply = await _finalize_order(
                        phone, order, session, persist_fail_message=persist_fail_message
                    )
                elif _looks_like_confirm_prompt(customer_reply) or _order_summary_in_reply(customer_reply):
                    session.state = "confirming"
                    session.awaiting_confirm = True

        session.history = [
            {"role": "user", "parts": [user_message]},
            {"role": "model", "parts": [customer_reply[:2000]]},
        ] + session.history[-16:]

        if order or session.state == "done":
            session.awaiting_confirm = False
        elif _looks_like_confirm_prompt(customer_reply) or _order_summary_in_reply(customer_reply):
            session.state = "confirming"
            session.awaiting_confirm = True
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
        return customer_reply or msg("rate_limit", session.language)
    except LlmRateLimitError:
        logger.warning("LLM rate limited for %s — using smart fallback", phone[:6] + "***")
        return _smart_fallback_reply(session, restaurants, catalog_items)
    except Exception as exc:
        err = str(exc)
        if "429" in err or "ResourceExhausted" in err or "quota" in err.lower():
            logger.warning("LLM quota exceeded for %s — using smart fallback", phone[:6] + "***")
            return _smart_fallback_reply(session, restaurants, catalog_items)
        logger.exception("Order agent failed after %.2fs", time.perf_counter() - t0)
        return msg("rate_limit", session.language)


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
