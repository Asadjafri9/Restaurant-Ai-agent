"""Tests for the LLM-primary agent: JSON contract parsing, cart application,
and persistence. These verify the layer where Python trusts the LLM and only
guards against the LLM hallucinating items not on the menu."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.order_agent import (
    _extract_json_object,
    _validate_cart_items,
    process_order_message_async,
    RESET_WORDS,
)
from app.services.session_service import CustomerSession

KFC_CATALOG = [
    {"name": "Krusher", "price": 380, "tenant_item_id": "6", "category": "Drinks"},
    {"name": "Zinger Burger", "price": 520, "tenant_item_id": "1", "category": "Burgers"},
    {"name": "Hot Wings (6 pcs)", "price": 650, "tenant_item_id": "2", "category": "Burgers"},
]


def _llm_reply(obj: dict) -> str:
    return json.dumps(obj)


def test_extract_plain_json():
    obj = _extract_json_object(_llm_reply({"reply": "Hi", "items": []}))
    assert obj["reply"] == "Hi"
    assert obj["items"] == []


def test_extract_order_json_fenced():
    raw = (
        "Some prose.\n[ORDER_JSON]"
        + json.dumps({"reply": "ok", "items": [{"item": "Krusher", "quantity": 1}]})
        + "[/ORDER_JSON]"
    )
    obj = _extract_json_object(raw)
    assert obj and obj["reply"] == "ok"


def test_extract_markdown_fenced():
    raw = "```json\n" + json.dumps({"reply": "x", "items": []}) + "\n```"
    obj = _extract_json_object(raw)
    assert obj["reply"] == "x"


def test_extract_broken_text_returns_none():
    assert _extract_json_object("Just prose, no JSON here.") is None
    assert _extract_json_object("") is None


def test_validate_cart_drops_unknown_items():
    cleaned = _validate_cart_items(
        [
            {"item": "Krusher", "quantity": 2},
            {"item": "Does Not Exist", "quantity": 1},
        ],
        KFC_CATALOG,
    )
    assert len(cleaned) == 1
    assert cleaned[0]["item"] == "Krusher"
    assert cleaned[0]["quantity"] == 2
    assert cleaned[0]["unit_price"] == 380
    assert cleaned[0]["menu_item_id"] == "6"


def test_validate_cart_clamps_invalid_quantity():
    cleaned = _validate_cart_items(
        [{"item": "Krusher", "quantity": 0}, {"item": "Zinger Burger", "quantity": -5}],
        KFC_CATALOG,
    )
    assert cleaned == []


def test_validate_cart_preserves_notes():
    cleaned = _validate_cart_items(
        [{"item": "Krusher", "quantity": 1, "notes": "extra cold"}],
        KFC_CATALOG,
    )
    assert cleaned[0]["notes"] == "extra cold"


@pytest.mark.asyncio
async def test_flow_adds_items_to_cart_and_does_not_place():
    session = CustomerSession(phone="+923001234567", state="greeting")
    restaurants = [{"slug": "kfc", "name": "KFC"}, {"slug": "kababjees", "name": "Kababjees"}]

    async def fake_session(phone):
        return session

    async def fake_list():
        return restaurants

    async def fake_menu(slug, *, force_refresh=False):
        return "tid-kfc", KFC_CATALOG

    async def fake_llm(system, history, user_message):
        return _llm_reply(
            {
                "reply": "Great — KFC it is. Here's the menu:\n1. Krusher — Rs 380\n2. Zinger Burger — Rs 520\nWhat would you like?",
                "restaurant": "kfc",
                "items": [],
                "place_order": False,
            }
        )

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch("app.services.order_agent.list_active_restaurants", AsyncMock(side_effect=fake_list)),
        patch("app.services.order_agent.get_menu_by_slug", AsyncMock(side_effect=fake_menu)),
        patch("app.services.order_agent.generate_reply", AsyncMock(side_effect=fake_llm)),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
    ):
        reply = await process_order_message_async("+923001234567", "kfc")
    assert "Krusher" in reply
    assert session.active_tenant_slug == "kfc"
    assert session.state == "ordering"


@pytest.mark.asyncio
async def test_flow_increments_quantity_when_customer_says_1_more():
    """The conversation in the bug report: 'Yes 1 more krusher' after 1 Krusher."""
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Krusher", "quantity": 1, "unit_price": 380, "menu_item_id": "6"}],
    )
    restaurants = [{"slug": "kfc", "name": "KFC"}]

    async def fake_session(phone):
        return session

    async def fake_list():
        return restaurants

    async def fake_menu(slug, *, force_refresh=False):
        return "tid-kfc", KFC_CATALOG

    async def fake_llm(system, history, user_message):
        return _llm_reply(
            {
                "reply": "Got it — 2 Krushers now. Anything else?",
                "restaurant": "kfc",
                "items": [{"item": "Krusher", "quantity": 2}],
                "place_order": False,
            }
        )

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch("app.services.order_agent.list_active_restaurants", AsyncMock(side_effect=fake_list)),
        patch("app.services.order_agent.get_menu_by_slug", AsyncMock(side_effect=fake_menu)),
        patch("app.services.order_agent.generate_reply", AsyncMock(side_effect=fake_llm)),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
    ):
        await process_order_message_async("+923001234567", "Yes 1 more krusher")
    assert len(session.pending_items) == 1
    assert session.pending_items[0]["item"] == "Krusher"
    assert session.pending_items[0]["quantity"] == 2


@pytest.mark.asyncio
async def test_flow_captures_name_and_address_from_one_message():
    """The 'Asad Jafri block c5' case: name + address delivered together."""
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Krusher", "quantity": 2}],
    )

    async def fake_session(phone):
        return session

    async def fake_list():
        return [{"slug": "kfc", "name": "KFC"}]

    async def fake_menu(slug, *, force_refresh=False):
        return "tid-kfc", KFC_CATALOG

    async def fake_llm(system, history, user_message):
        return _llm_reply(
            {
                "reply": "Thanks Asad. Block C5 noted. Anything else?",
                "restaurant": "kfc",
                "customer_name": "Asad Jafri",
                "address": "Block C5",
                "items": [{"item": "Krusher", "quantity": 2}],
                "place_order": False,
            }
        )

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch("app.services.order_agent.list_active_restaurants", AsyncMock(side_effect=fake_list)),
        patch("app.services.order_agent.get_menu_by_slug", AsyncMock(side_effect=fake_menu)),
        patch("app.services.order_agent.generate_reply", AsyncMock(side_effect=fake_llm)),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
    ):
        await process_order_message_async("+923001234567", "Asad Jafri block c5")
    assert session.pending_customer_name == "Asad Jafri"
    assert session.pending_address == "Block C5"
    assert len(session.pending_items) == 1
    assert session.pending_items[0]["quantity"] == 2


@pytest.mark.asyncio
async def test_flow_places_order_only_when_name_and_address_present():
    """Refuses to place when name/address missing even if LLM said place_order=true."""
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Krusher", "quantity": 1}],
    )

    async def fake_session(phone):
        return session

    async def fake_list():
        return [{"slug": "kfc", "name": "KFC"}]

    async def fake_menu(slug, *, force_refresh=False):
        return "tid-kfc", KFC_CATALOG

    async def fake_llm(system, history, user_message):
        return _llm_reply(
            {
                "reply": "Order placed.",
                "restaurant": "kfc",
                "items": [{"item": "Krusher", "quantity": 1}],
                "place_order": True,
            }
        )

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch("app.services.order_agent.list_active_restaurants", AsyncMock(side_effect=fake_list)),
        patch("app.services.order_agent.get_menu_by_slug", AsyncMock(side_effect=fake_menu)),
        patch("app.services.order_agent.generate_reply", AsyncMock(side_effect=fake_llm)),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
    ):
        reply = await process_order_message_async("+923001234567", "yes")
    # Name missing → should NOT have persisted
    assert "name" in reply.lower() or "naam" in reply.lower()
    assert session.state != "done"


@pytest.mark.asyncio
async def test_flow_places_order_when_complete(monkeypatch):
    session = CustomerSession(
        phone="+923001234567",
        state="confirming",
        active_tenant_slug="kfc",
        pending_customer_name="Asad",
        pending_address="Block C5",
        pending_items=[{"item": "Krusher", "quantity": 1, "unit_price": 380, "menu_item_id": "6"}],
    )

    async def fake_session(phone):
        return session

    persist_calls = []

    async def fake_finalize(phone, order_obj, sess):
        persist_calls.append(order_obj)
        sess.state = "done"
        return {"order_id": "abc12345-6789", "total": 380.0}

    monkeypatch.setattr("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session))
    monkeypatch.setattr(
        "app.services.order_agent.list_active_restaurants",
        AsyncMock(return_value=[{"slug": "kfc", "name": "KFC"}]),
    )
    monkeypatch.setattr(
        "app.services.order_agent.get_menu_by_slug",
        AsyncMock(return_value=("tid-kfc", KFC_CATALOG)),
    )
    monkeypatch.setattr("app.services.order_agent.save_session_async", AsyncMock())

    monkeypatch.setattr(
        "app.services.order_agent.generate_reply",
        AsyncMock(
            return_value=_llm_reply(
                {
                    "reply": "Order confirmed! Total Rs 380.",
                    "restaurant": "kfc",
                    "customer_name": "Asad",
                    "address": "Block C5",
                    "items": [{"item": "Krusher", "quantity": 1}],
                    "place_order": True,
                }
            )
        ),
    )
    monkeypatch.setattr("app.services.order_agent._finalize_order_from_json", fake_finalize)

    reply = await process_order_message_async("+923001234567", "yes")
    assert persist_calls, "should have persisted"
    assert "Order confirmed" in reply or "Order ID" in reply
    assert session.state == "done"
    assert session.pending_items == []


@pytest.mark.asyncio
async def test_flow_decline_word_does_not_become_name():
    """The 'No' became the name. With LLM-primary, name stays unset."""
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Krusher", "quantity": 1}],
    )

    async def fake_session(phone):
        return session

    async def fake_llm(system, history, user_message):
        return _llm_reply(
            {
                "reply": "Sure, that's 1 Krusher. Anything else?",
                "restaurant": "kfc",
                "items": [{"item": "Krusher", "quantity": 1}],
                "place_order": False,
            }
        )

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch(
            "app.services.order_agent.list_active_restaurants",
            AsyncMock(return_value=[{"slug": "kfc", "name": "KFC"}]),
        ),
        patch(
            "app.services.order_agent.get_menu_by_slug",
            AsyncMock(return_value=("tid-kfc", KFC_CATALOG)),
        ),
        patch("app.services.order_agent.generate_reply", AsyncMock(side_effect=fake_llm)),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
    ):
        await process_order_message_async("+923001234567", "no")
    assert not session.pending_customer_name


def test_reset_words_constant():
    assert "reset" in RESET_WORDS
    assert "new order" in RESET_WORDS


@pytest.mark.asyncio
async def test_reset_clears_session():
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Krusher", "quantity": 1}],
    )

    async def fake_session(phone):
        return session

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch(
            "app.services.order_agent.list_active_restaurants",
            AsyncMock(return_value=[{"slug": "kfc", "name": "KFC"}]),
        ),
        patch(
            "app.services.order_agent.get_menu_by_slug",
            AsyncMock(return_value=("tid-kfc", KFC_CATALOG)),
        ),
        patch("app.services.order_agent.generate_reply", AsyncMock(return_value="{}")),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
        patch("app.services.order_agent.reset_session_async", AsyncMock()),
    ):
        await process_order_message_async("+923001234567", "new order")
    assert session.active_tenant_slug is None
    assert session.state == "greeting"
    assert session.pending_items == []


@pytest.mark.asyncio
async def test_llm_prose_fallback_shown_to_customer():
    """When the LLM ignores the JSON contract and replies with prose, the prose
    is shown to the customer (the cart is left unchanged)."""
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Krusher", "quantity": 1}],
    )

    async def fake_session(phone):
        return session

    async def fake_llm(system, history, user_message):
        return "I'm sorry, I didn't get that — could you repeat?"

    with (
        patch("app.services.order_agent.get_session_async", AsyncMock(side_effect=fake_session)),
        patch(
            "app.services.order_agent.list_active_restaurants",
            AsyncMock(return_value=[{"slug": "kfc", "name": "KFC"}]),
        ),
        patch(
            "app.services.order_agent.get_menu_by_slug",
            AsyncMock(return_value=("tid-kfc", KFC_CATALOG)),
        ),
        patch("app.services.order_agent.generate_reply", AsyncMock(side_effect=fake_llm)),
        patch("app.services.order_agent.save_session_async", AsyncMock()),
    ):
        reply = await process_order_message_async("+923001234567", "hi")
    assert "could you repeat" in reply.lower()