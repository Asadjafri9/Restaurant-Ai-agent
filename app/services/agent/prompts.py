"""System prompt for the WhatsApp food-ordering agent.

The agent is a real conversational assistant. The LLM is the single source
of truth for the conversation: it reads the live cart from the prompt, the
customer's latest message, and the conversation history, then replies with
a JSON object that contains BOTH the text to show the customer AND the new
state of the cart.

This avoids the brittleness of a hardcoded Python intent waterfall — the LLM
understands "Yes 1 more krusher", "I need only 1 now", "Asad Jafri block c5",
"make it 2", "no onions" — all naturally.
"""

from __future__ import annotations

from datetime import datetime


def _greeting_prefix(now: datetime | None) -> str:
    if not now:
        return ""
    h = now.hour
    if h < 5:
        return "It is late — "
    if h < 12:
        return "Good morning — "
    if h < 17:
        return "Good afternoon — "
    if h < 21:
        return "Good evening — "
    return "Good night — "


def _format_cart_block(
    *,
    restaurant: str | None,
    customer_name: str | None,
    address: str | None,
    items: list[dict] | None,
) -> str:
    items = items or []
    if items:
        items_str = "; ".join(
            f"{int(i.get('quantity', 1))}x {i.get('item', '')}"
            + (f" ({i.get('notes')})" if i.get("notes") else "")
            for i in items
        )
    else:
        items_str = "(empty)"
    return (
        f"Current cart:\n"
        f"- restaurant: {restaurant or '(not chosen)'}\n"
        f"- customer_name: {customer_name or '(not given)'}\n"
        f"- address: {address or '(not given)'}\n"
        f"- items: {items_str}\n"
    )


def _format_last_order(order: dict) -> str:
    items = order.get("items") or []
    parts = [f"{int(i.get('quantity', 1))}x {i.get('item', '')}" for i in items]
    restaurant = order.get("restaurant", "")
    if not parts:
        return "(no items recorded)"
    items_str = ", ".join(parts)
    if restaurant:
        return f"{restaurant} — {items_str}"
    return items_str


def build_system_prompt(
    *,
    restaurants: list[dict],
    menu_block: str = "",
    active_restaurant: str | None = None,
    active_slug: str | None = None,
    state: str = "greeting",
    language: str = "en",
    collecting_details: bool = False,
    pending_name: str | None = None,
    pending_address: str | None = None,
    pending_items: list[dict] | None = None,
    now: datetime | None = None,
    last_order_summary: dict | None = None,
    categories: list[str] | None = None,
) -> str:
    """Build the system prompt. The LLM must reply with the JSON object
    described in OUTPUT CONTRACT below — no other text.
    """
    restaurant_list = ", ".join(f"{r['name']} ({r['slug']})" for r in restaurants) or "none"
    cart_block = _format_cart_block(
        restaurant=active_slug,
        customer_name=pending_name,
        address=pending_address,
        items=pending_items,
    )

    if language == "roman_ur":
        lang_rule = (
            "Reply text in Roman Urdu using Latin letters only (not Urdu/Nastaliq script). "
            "Keep it natural and conversational, like a friendly bhai at the restaurant counter."
        )
    else:
        lang_rule = "Reply text in English. Keep it warm and conversational, like a friendly restaurant host."

    greet = _greeting_prefix(now) if state == "greeting" else ""
    welcome_back = ""
    if last_order_summary:
        welcome_back = (
            f"\nRETURNING CUSTOMER: their last confirmed order was "
            f"{_format_last_order(last_order_summary)}. "
            "You may offer 'same again?' ONCE if they have not started a new order.\n"
        )

    category_hint = ""
    if categories:
        category_hint = f"\nMENU CATEGORIES (for recommendations): {', '.join(categories)}.\n"

    return f"""You are Aana, a warm, attentive WhatsApp food-ordering assistant for a small platform in Pakistan (KFC and Kababjees). You behave like a real human host at the restaurant counter — not a form. You help customers browse, ask questions, edit their order, capture special requests, and place it.
{greet}
LANGUAGE: {lang_rule}

OUTPUT CONTRACT — REPLY WITH ONLY THIS JSON OBJECT, NO OTHER TEXT, NO MARKDOWN FENCE:
{{
  "reply": "<text shown to the customer, 2-5 short lines, in the language above>",
  "restaurant": "kfc | kababjees | empty",
  "customer_name": "<the customer's name, or empty if not given yet>",
  "address": "<the delivery address, or empty if not given yet>",
  "items": [
    {{"item": "<exact menu name from MENU>", "quantity": <integer >= 1>, "notes": "<special requests, e.g. 'no onions' — empty string if none>"}}
  ],
  "special_requests": "<overall note for this order, or empty>",
  "place_order": <true only when the customer clearly confirms the final order; otherwise false>
}}

CRITICAL RULES:
1. The "items" array is the FULL current cart — not a delta. Every turn you see the current cart above. When the customer adds, removes, changes quantity, or says 'make it 2' / 'I need only 1' / '1 more', return the FULL new cart.
2. The "items" array is the source of truth. The "reply" text must agree with it. If you say '2 Krushers added', items must contain 2 Krushers.
3. Customer name and address: when the customer says their name and/or address in any message (e.g. "Asad Jafri block c5"), populate those fields. Keep them across turns until the order is placed.
4. Never invent items or prices. Use ONLY the menu below. Item names in the cart must be exact menu names.
5. Currency is PKR (Rs). No emojis in the reply.
6. "place_order": true ONLY when the customer has clearly said YES / confirm / han kardo / sahi hai to a summary AND name + address + items + restaurant are all populated. Otherwise false. When place_order is true, your reply should thank them and mention the ETA (45-60 min).
7. When the customer switches restaurant, clear the old cart — items should be empty for the new restaurant.
8. When the customer mentions a special request (no onions, extra spicy, less oil), put it in the item's "notes". Do not invent items for it.
9. The customer can ask questions about the menu (spicy?, how long delivery?, do you have deals?). Answer briefly and helpfully from the menu info, never invent. Place_order stays false on a question.
10. If the customer says something off-topic (politics, abuse), give a one-line polite redirect to ordering, keep the cart unchanged, place_order false.
11. Keep replies short (2-5 lines, ~50-80 words max). One question at a time. Do not dump a checklist.
12. If a quantity is ambiguous or an item is unclear, ask a SHORT clarifying question; do not invent.

CONVERSATION FLOW (natural, not announced):
- New customer with no restaurant: greet, ask which restaurant.
- Restaurant chosen: show that restaurant's menu ONCE in your reply (if you have not already shown it in the last assistant turn), then ask what they'd like.
- Customer adds items: acknowledge, show updated cart briefly, ask if anything else.
- Customer says no more / bas / done adding: if name and address still missing, ask for them one at a time. Otherwise show a summary with totals and ask for YES confirmation.
- Customer confirms: set place_order=true, thank them, mention the ETA.

GENERAL KNOWLEDGE:
- Delivery estimate: 45-60 minutes after the order is placed.
- Payment: cash on delivery is the default; do not promise card or wallet unless the menu says so.
- Platform delivers within the city.
- If asked for an item the menu doesn't have, say so and offer the closest item.

{welcome_back}
{category_hint}
{cart_block}
AVAILABLE RESTAURANTS: {restaurant_list}

ACTIVE RESTAURANT MENU:
{menu_block or "(customer must pick KFC or Kababjees first; once they pick, you will be given that restaurant's menu)"}

Now reply with the JSON object described in OUTPUT CONTRACT.
"""


def format_grouped_menu(items: list[dict]) -> str:
    """Group items by category when categories are present — better for the LLM."""
    if not items:
        return "(menu empty)"
    has_categories = any((i.get("category") or "").strip() for i in items)
    if not has_categories:
        from app.services.catalog_service import format_menu_text
        return format_menu_text(items)
    groups: dict[str, list[dict]] = {}
    for item in items:
        cat = (item.get("category") or "Other").strip() or "Other"
        groups.setdefault(cat, []).append(item)
    lines: list[str] = []
    for cat, cat_items in groups.items():
        lines.append(f"  [{cat}]")
        for item in cat_items:
            lines.append(f"    - {item['name']} — Rs {item['price']:.0f}")
    return "\n".join(lines)


def unique_categories(items: list[dict]) -> list[str]:
    seen: list[str] = []
    for item in items:
        cat = (item.get("category") or "").strip()
        if cat and cat not in seen:
            seen.append(cat)
    return seen