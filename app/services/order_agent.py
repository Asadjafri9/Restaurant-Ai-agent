"""LLM-primary agent flow.

The LLM is the single source of truth for the conversation. It returns a
JSON object with the reply text AND the new cart state. Python just applies
it and persists when place_order is true. No hardcoded intent waterfall.
"""

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from logging import getLogger

from app.services.agent.prompts import build_system_prompt, format_grouped_menu, unique_categories
from app.services.catalog_service import get_menu_by_slug, list_active_restaurants
from app.services.i18n import detect_language, msg
from app.services.llm_client import LlmRateLimitError, generate_reply
from app.services.order_routing import order_routing
from app.services.session_service import get_session_async, reset_session_async, save_session_async
from app.services.voice_text import normalize_user_text as _normalize_user_text

logger = getLogger(__name__)

ORDER_JSON_PATTERN = re.compile(r"\[ORDER_JSON\]\s*(\{.*?\})\s*\[/ORDER_JSON\]", re.DOTALL)
_BARE_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

RESET_WORDS = frozenset({"reset", "start over", "restart", "new order"})


def _extract_json_object(raw_text: str) -> dict | None:
    """Robustly extract the JSON object from the LLM reply.

    Tries, in order: bare JSON object parse, [ORDER_JSON] fenced block,
    text-with-mixed-text-first. Strips markdown fences.
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    # Strip common markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try fenced [ORDER_JSON] block
    m = ORDER_JSON_PATTERN.search(raw_text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # Try locating the outermost braces
    brace_match = _BARE_JSON_PATTERN.search(raw_text)
    if brace_match:
        candidate = brace_match.group(0)
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _validate_cart_items(items_raw, catalog: list[dict]) -> list[dict]:
    """Validate cart items against the catalog. Returns cleaned items with
    exact menu names, integer quantities, notes strings. Items not in the
    catalog are dropped (the LLM hallucinated them).
    """
    if not isinstance(items_raw, list):
        return []
    by_name = {i["name"].lower(): i for i in catalog if i.get("name")}
    cleaned: list[dict] = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        raw_name = (it.get("item") or it.get("name") or "").strip()
        if not raw_name:
            continue
        cat = by_name.get(raw_name.lower())
        if not cat:
            continue
        try:
            qty = int(it.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 1
        if qty < 1:
            continue
        notes = it.get("notes") or ""
        if not isinstance(notes, str):
            notes = str(notes)
        notes = notes.strip()
        cleaned.append(
            {
                "item": cat["name"],
                "quantity": qty,
                "unit_price": float(cat.get("price", 0)),
                "menu_item_id": cat.get("tenant_item_id"),
                "notes": notes or None,
            }
        )
    return cleaned


async def _build_menu_block(session, restaurants: list[dict]) -> tuple[str, list[dict], str, list[str]]:
    """Return (menu_block_for_prompt, catalog_items, active_name, categories)."""
    catalog: list[dict] = []
    active_name = None
    slug = session.active_tenant_slug
    if slug:
        _, catalog = await get_menu_by_slug(slug, force_refresh=True)
        active_name = next((r["name"] for r in restaurants if r["slug"] == slug), slug)
    if catalog:
        menu_block = f"{active_name} ({slug}):\n{format_grouped_menu(catalog)}"
        return menu_block, catalog, active_name, unique_categories(catalog)
    return "(customer must pick KFC or Kababjees first)", [], None, []


async def _finalize_order_from_json(phone: str, order_obj: dict, session) -> str | None:
    """Build a persisted order from the LLM's JSON and call order_routing."""
    slug = (order_obj.get("restaurant") or session.active_tenant_slug or "").strip().lower()
    if not slug:
        return None
    tenant_id, catalog = await get_menu_by_slug(slug, force_refresh=True)
    if not tenant_id:
        logger.warning("persist: no tenant for slug=%s", slug)
        return None
    cleaned_items = _validate_cart_items(order_obj.get("items"), catalog)
    if not cleaned_items:
        logger.warning("persist: no usable items in %s", order_obj.get("items"))
        return None
    items_key = hashlib.sha256(
        json.dumps(order_obj.get("items", []), sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    name = (order_obj.get("customer_name") or "").strip()
    address = (order_obj.get("address") or "").strip()
    idem = f"{phone}:{slug}:{name}:{address}:{items_key}"
    notes = (order_obj.get("special_requests") or "").strip() or None
    result = await order_routing.create_order(
        tenant_id,
        customer_phone=phone,
        customer_name=name,
        delivery_address=address,
        items=[
            {
                "name": i["item"],
                "quantity": i["quantity"],
                "unit_price": i["unit_price"],
                "menu_item_id": i.get("menu_item_id"),
                "modifiers": i.get("notes"),
            }
            for i in cleaned_items
        ],
        idempotency_key=idem,
        notes=notes,
    )
    try:
        from app.services.provisioning import enqueue_job
        from app.services.realtime import publish_order_event
        await enqueue_job("sync_outboxes", {"tenant_id": str(tenant_id)})
        await publish_order_event(
            tenant_id,
            {"type": "order_created", "order_id": result["order_id"], "status": "placed"},
        )
    except Exception:
        logger.exception("post-persist event failed (non-fatal)")
    session.state = "done"
    session.active_tenant_slug = slug
    session.pending_customer_name = None
    session.pending_address = None
    session.pending_items = []
    session.confirmed_orders.append(
        {
            "restaurant": slug,
            "customer_name": name,
            "address": address,
            "items": cleaned_items,
        }
    )
    logger.info("Order persisted for %s slug=%s", phone[:6] + "***", slug)
    return result


async def _smart_fallback_reply(session, restaurants: list[dict], catalog: list[dict]) -> str:
    """When the LLM is rate-limited / errors, produce a useful deterministic reply."""
    lang = session.language
    if not session.active_tenant_slug:
        if not restaurants:
            return msg("no_restaurants", lang)
        names = [r["name"] for r in restaurants]
        list_text = " or ".join(names) if len(names) == 2 else ", ".join(names)
        return msg("greeting", lang, restaurants=list_text)
    if session.pending_items:
        items_text = "\n".join(
            f"{int(i.get('quantity', 1))}x {i.get('item', '')}" for i in session.pending_items
        )
        if not session.pending_customer_name:
            return f"{items_text}\n\n{msg('ask_name', lang)}"
        if not session.pending_address:
            return f"{items_text}\n\n{msg('ask_address', lang)}"
        # Show summary
        total = 0.0
        lines = []
        for pi in session.pending_items:
            by_name = {c["name"].lower(): c for c in catalog} if catalog else {}
            cat = by_name.get(pi["item"].lower(), {})
            price = float(cat.get("price", 0))
            qty = int(pi.get("quantity", 1))
            line = price * qty
            total += line
            lines.append(f"{qty}x {pi['item']} — Rs {line:.0f}")
        items_str = "\n".join(lines)
        return (
            f"Order summary:\n{items_str}\n"
            f"Name: {session.pending_customer_name}\n"
            f"Address: {session.pending_address}\n"
            f"Total: Rs {total:.0f}\n\n"
            f"{msg('ask_name', lang) if False else 'Reply YES to confirm.'}"
        )
    return msg("menu_ask", lang)


async def process_order_message_async(phone: str, user_message: str) -> str:
    t0 = time.perf_counter()
    user_message = (user_message or "").strip()
    normalized = _normalize_user_text(user_message)

    if normalized in RESET_WORDS:
        await reset_session_async(phone)

    session, restaurants = await _gather_session_and_restaurants(phone)
    if hasattr(session, "language") and not session.language:
        session.language = detect_language(user_message) or "en"
    lang = session.language

    try:
        await _light_routing(session, user_message, restaurants, normalized)
    except Exception:
        logger.exception("light routing failed (non-fatal)")

    menu_block, catalog, active_name, categories = await _build_menu_block(session, restaurants)

    now = datetime.now(timezone.utc)
    last_order_summary = None
    if getattr(session, "confirmed_orders", None):
        last = session.confirmed_orders[-1] or {}
        last_order_summary = {
            "restaurant": last.get("restaurant"),
            "items": last.get("items") or [],
        }

    system = build_system_prompt(
        restaurants=restaurants,
        menu_block=menu_block,
        active_restaurant=active_name,
        active_slug=session.active_tenant_slug,
        state=session.state or ("ordering" if session.active_tenant_slug else "greeting"),
        language=lang,
        pending_name=session.pending_customer_name,
        pending_address=session.pending_address,
        pending_items=session.pending_items,
        now=now,
        last_order_summary=last_order_summary,
        categories=categories,
    )

    history = _build_history_for_llm(session)

    try:
        raw_text = await generate_reply(system, history, user_message)
    except LlmRateLimitError:
        logger.warning("LLM rate limited for %s — smart fallback", phone[:6] + "***")
        reply = await _smart_fallback_reply(session, restaurants, catalog)
        await _save_and_log(session, phone, user_message, reply, t0, source="fallback")
        return reply
    except Exception as exc:
        err = str(exc)
        if "429" in err or "ResourceExhausted" in err or "quota" in err.lower():
            logger.warning("LLM quota for %s — smart fallback", phone[:6] + "***")
            reply = await _smart_fallback_reply(session, restaurants, catalog)
            await _save_and_log(session, phone, user_message, reply, t0, source="fallback")
            return reply
        logger.exception("LLM call failed after %.2fs", time.perf_counter() - t0)
        reply = msg("rate_limit", lang)
        await _save_and_log(session, phone, user_message, reply, t0, source="error")
        return reply

    if not raw_text or not raw_text.strip():
        reply = await _smart_fallback_reply(session, restaurants, catalog)
        await _save_and_log(session, phone, user_message, reply, t0, source="empty")
        return reply

    obj = _extract_json_object(raw_text)

    if obj is None:
        # The LLM ignored the JSON contract and replied in prose.
        # Show its text to the customer but keep cart unchanged.
        customer_reply = _strip_order_json_text(raw_text).strip() or msg("menu_ask", lang)
        if session.active_tenant_slug:
            session.state = "ordering"
        await _save_and_log(session, phone, user_message, customer_reply, t0, source="llm-text")
        return customer_reply

    reply_text = (obj.get("reply") or "").strip() or msg("menu_ask", lang)

    new_slug = (obj.get("restaurant") or "").strip().lower()
    new_name = (obj.get("customer_name") or "").strip()
    new_address = (obj.get("address") or "").strip()
    new_items = _validate_cart_items(obj.get("items"), catalog)
    place = bool(obj.get("place_order"))

    # Apply cart changes
    if new_slug and new_slug != session.active_tenant_slug:
        from app.core.tenant_ids import TENANT_IDS
        session.active_tenant_slug = new_slug
        session.active_tenant_id = str(TENANT_IDS.get(new_slug, ""))
        session.pending_items = []
        session.state = "ordering"
    if new_name:
        session.pending_customer_name = new_name
    if new_address:
        session.pending_address = new_address
    if new_items:
        # Merge if the restaurant didn't change; otherwise replace
        existing = {(i.get("item") or "").lower(): i for i in session.pending_items}
        for it in new_items:
            key = it["item"].lower()
            if key in existing and session.active_tenant_slug == session.active_tenant_slug:
                # Last-write-wins per turn: replace existing entry's qty/notes
                existing[key] = it
            else:
                existing[key] = it
        session.pending_items = list(existing.values())
    elif obj.get("items") == [] and session.pending_items and not place:
        # LLM explicitly cleared the cart
        session.pending_items = []

    # Determine whether to show menu (first time the restaurant is chosen)
    if new_slug and new_slug != session.active_tenant_slug:
        # Just changed — state already set above
        pass

    # If the LLM signaled place_order, persist
    placed = False
    if place:
        order_obj = {
            "restaurant": new_slug or session.active_tenant_slug,
            "customer_name": new_name or session.pending_customer_name or "",
            "address": new_address or session.pending_address or "",
            "items": new_items or session.pending_items,
            "special_requests": (obj.get("special_requests") or "").strip(),
        }
        if order_obj["customer_name"] and order_obj["address"] and order_obj["items"]:
            result = await _finalize_order_from_json(phone, order_obj, session)
            if result:
                placed = True
                reply_text = msg(
                    "order_confirmed",
                    lang,
                    total=float(result["total"]),
                    order_id=str(result["order_id"])[:8].upper(),
                )
                session.awaiting_confirm = False
                # Defense-in-depth even if _finalize_order_from_json is mocked
                session.pending_items = []
                session.pending_customer_name = None
                session.pending_address = None
                session.state = "done"
            else:
                reply_text = msg("persist_fail", lang)
                session.state = "ordering"
        else:
            # Not enough info to place — ask for the missing piece
            missing = []
            if not order_obj["customer_name"]:
                missing.append("name")
            if not order_obj["address"]:
                missing.append("address")
            if not order_obj["items"]:
                missing.append("items")
            if "name" in missing:
                reply_text = msg("ask_name", lang)
            elif "address" in missing:
                reply_text = msg("ask_address", lang)
            elif "items" in missing:
                reply_text = msg("menu_ask", lang)
            session.state = "ordering"
            session.awaiting_confirm = False
    else:
        if session.active_tenant_slug:
            session.state = "ordering"

    # Light heuristics for state ONLY when placement did not already decide it
    if not placed and not session.active_tenant_slug:
        session.state = "greeting"
    # Otherwise the place branch above already set state correctly.

    await _save_and_log(session, phone, user_message, reply_text, t0, source="llm")
    return reply_text


def _strip_order_json_text(text: str) -> str:
    """Remove any [ORDER_JSON] block from text, return the cleaned prose."""
    return ORDER_JSON_PATTERN.sub("", text).strip()


def _build_history_for_llm(session) -> list[dict]:
    history: list[dict] = []
    for h in session.history or []:
        role = "user" if h.get("role") == "user" else "model"
        parts = h.get("parts") or []
        text = parts[0] if parts else ""
        text = ORDER_JSON_PATTERN.sub("", text).strip()
        if text:
            history.append({"role": role, "parts": [text]})
    return history[-16:]


async def _gather_session_and_restaurants(phone: str):
    return await asyncio.gather(get_session_async(phone), list_active_restaurants())


async def _save_and_log(session, phone, user_message, reply_text, t0, *, source):
    session.history = [
        {"role": "user", "parts": [user_message]},
        {"role": "model", "parts": [reply_text[:2000]]},
    ] + (session.history or [])[-16:]
    session.updated_at = datetime.now(timezone.utc)
    await save_session_async(session)
    logger.info(
        "%s reply for %s state=%s in %.2fs",
        source,
        phone[:6] + "***",
        getattr(session, "state", "?"),
        time.perf_counter() - t0,
    )


async def _light_routing(session, user_message: str, restaurants: list[dict], normalized: str) -> None:
    """Apply a few cheap, high-recall routing rules BEFORE the LLM is called.

    Pure additions to avoid a wasted LLM round trip on the clearest cases:
    - reset / new order
    - restaurant name in text → set active slug (so the menu block is right)
    - language stickiness
    """
    if normalized in RESET_WORDS:
        session.active_tenant_slug = None
        session.active_tenant_id = None
        session.state = "greeting"
        session.awaiting_confirm = False
        session.pending_customer_name = None
        session.pending_address = None
        session.pending_items = []
        session.history = []
        return
    if not session.active_tenant_slug:
        slug = _resolve_slug_light(user_message, restaurants)
        if slug:
            from app.core.tenant_ids import TENANT_IDS
            session.active_tenant_slug = slug
            session.active_tenant_id = str(TENANT_IDS.get(slug, ""))
            session.state = "ordering"
    # Keep language sticky across short replies in the same chat
    detected = detect_language(user_message)
    if detected == "roman_ur":
        session.language = "roman_ur"
    elif not session.history and detected:
        session.language = detected


def _resolve_slug_light(text: str, restaurants: list[dict]) -> str | None:
    """Cheap restaurant detection — full slug-match wins."""
    if not restaurants or not text:
        return None
    lower = text.lower()
    for r in sorted(restaurants, key=lambda x: len(x["slug"]), reverse=True):
        slug = r["slug"]
        name = (r.get("name") or "").lower()
        if slug in lower or (name and name in lower):
            return slug
    if "kababjees" in lower or "kababjee" in lower or re.search(r"kabab\s*jee?s?", lower):
        return "kababjees"
    if "kfc" in lower or "kentucky" in lower:
        return "kfc"
    return None


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