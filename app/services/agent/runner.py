import json
import logging
import uuid

import google.generativeai as genai

from app.config.settings import settings
from app.services.agent.prompts import build_system_prompt
from app.services.agent.tools import (
    CreateOrderInput,
    OrderItemInput,
    tool_create_order,
    tool_get_menu,
    tool_get_order_status,
    tool_list_restaurants,
)
from app.services.catalog_service import format_menu_text, list_active_restaurants
from app.services.session_service import get_session_async, reset_session_async, save_session_async

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)

TOOLS_DECL = [
    {
        "name": "list_restaurants",
        "description": "List available restaurants",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_menu",
        "description": "Get menu for a restaurant by slug",
        "parameters": {
            "type": "object",
            "properties": {"restaurant_slug": {"type": "string"}},
            "required": ["restaurant_slug"],
        },
    },
    {
        "name": "create_order",
        "description": "Place a confirmed order",
        "parameters": {
            "type": "object",
            "properties": {
                "restaurant_slug": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "integer"},
                        },
                    },
                },
                "customer_name": {"type": "string"},
                "delivery_address": {"type": "string"},
            },
            "required": ["restaurant_slug", "items", "customer_name", "delivery_address"],
        },
    },
    {
        "name": "get_order_status",
        "description": "Get status of an order",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
]


async def _execute_tool(name: str, args: dict, phone: str, session) -> str:
    if name == "list_restaurants":
        data = await tool_list_restaurants()
        return json.dumps(data)
    if name == "get_menu":
        slug = args.get("restaurant_slug", "")
        data = await tool_get_menu(slug)
        if data.get("items") and not session.active_tenant_id:
            restaurants = await list_active_restaurants()
            for r in restaurants:
                if r["slug"] == slug:
                    session.active_tenant_id = r["tenant_id"]
                    break
        return json.dumps(data)
    if name == "create_order":
        items = [
            OrderItemInput(name=i["name"], quantity=int(i["quantity"]), unit_price=0)
            for i in args.get("items", [])
        ]
        inp = CreateOrderInput(
            restaurant_slug=args["restaurant_slug"],
            items=items,
            customer_name=args["customer_name"],
            delivery_address=args["delivery_address"],
            customer_phone=phone,
            idempotency_key=f"{phone}:{args.get('restaurant_slug')}:{hash(json.dumps(args, sort_keys=True))}",
        )
        tid = uuid.UUID(session.active_tenant_id) if session.active_tenant_id else None
        result = await tool_create_order(inp, tid)
        return json.dumps(result)
    if name == "get_order_status":
        if not session.active_tenant_id:
            return json.dumps({"error": "No active restaurant"})
        result = await tool_get_order_status(args["order_id"], uuid.UUID(session.active_tenant_id))
        return json.dumps(result)
    return json.dumps({"error": f"Unknown tool {name}"})


def _history_to_gemini(history: list[dict]) -> list:
    out = []
    for h in history:
        role = "user" if h.get("role") == "user" else "model"
        parts = h.get("parts", [])
        if isinstance(parts, list) and parts:
            out.append({"role": role, "parts": parts})
    return out


def _gemini_to_history(chat_history) -> list[dict]:
    result = []
    for content in chat_history:
        role = "user" if content.role == "user" else "model"
        parts = []
        for p in content.parts:
            if hasattr(p, "text") and p.text:
                parts.append(p.text)
        if parts:
            result.append({"role": role, "parts": parts})
    return result[-20:]


async def process_order_message_async(phone: str, user_message: str) -> str:
    normalized = user_message.strip().lower()
    if normalized in {"reset", "start over", "restart", "new order"}:
        await reset_session_async(phone)

    session = await get_session_async(phone)
    restaurants = await list_active_restaurants()
    menus_parts = []
    for r in restaurants[:5]:
        _, items = await __import__(
            "app.services.catalog_service", fromlist=["get_menu_by_slug"]
        ).get_menu_by_slug(r["slug"])
        if items:
            menus_parts.append(f"\n{r['name']} ({r['slug']}):\n{format_menu_text(items)}")
    menus_block = "".join(menus_parts) if menus_parts else ""

    try:
        model = genai.GenerativeModel(
            settings.gemini_model,
            system_instruction=build_system_prompt(
                restaurants=await list_active_restaurants(),
                menu_block=menus_block,
            ),
            tools=TOOLS_DECL,
        )
        history = _history_to_gemini(session.history)
        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)

        # Handle function calls
        for _ in range(3):
            if not response.candidates:
                break
            parts = response.candidates[0].content.parts
            fn_calls = [p for p in parts if hasattr(p, "function_call") and p.function_call.name]
            if not fn_calls:
                break
            fn_responses = []
            for fc in fn_calls:
                fn = fc.function_call
                args = dict(fn.args) if fn.args else {}
                tool_result = await _execute_tool(fn.name, args, phone, session)
                fn_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn.name,
                            response={"result": tool_result},
                        )
                    )
                )
            response = chat.send_message(fn_responses)

        raw_text = (response.text or "").strip()
        session.history = _gemini_to_history(chat.history)
        await save_session_async(session)
        return raw_text or settings.ai_fallback_message
    except Exception:
        logger.exception("Agent failed for phone")
        return settings.ai_fallback_message


def process_order_message(phone: str, user_message: str) -> str:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, process_order_message_async(phone, user_message))
            return future.result(timeout=60)
    except RuntimeError:
        return asyncio.run(process_order_message_async(phone, user_message))
