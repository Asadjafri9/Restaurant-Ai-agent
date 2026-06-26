import pytest

from app.data.restaurants import RESTAURANTS
from app.services.order_agent import (
    _conversation_awaiting_confirm,
    _is_confirm_reply,
    _labels_for_new_items,
    _reply_after_items_added,
)
from app.services.order_context import extract_order_items, pending_items_changed, update_pending_from_message
from app.services.session_service import CustomerSession

KFC_CATALOG = [
    {"name": i["item"], "price": i["price_pkr"], "tenant_item_id": str(i["id"])}
    for i in RESTAURANTS["kfc"]["menu"]
]


def _menu_session() -> CustomerSession:
    return CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        language="roman_ur",
        pending_items=[{"item": "Zinger Burger", "quantity": 1}],
        history=[
            {
                "role": "model",
                "parts": [
                    "Theek hai — aapka order note kar liya: 1x Zinger Burger\n\n"
                    "KFC ka poora menu:\n"
                    "1. Zinger Burger — Rs 520\n"
                    "2. Hot Wings (6 pcs) — Rs 650\n"
                    "Yeh poora menu hai. Kuch aur order karna chahte hain?"
                ],
            }
        ],
    )


def test_menu_ask_more_is_not_awaiting_confirm():
    session = _menu_session()
    assert not _conversation_awaiting_confirm(session)


def test_han_pepsi_is_add_not_confirm():
    session = _menu_session()
    assert not _is_confirm_reply("han ek pepsi bhi kardo", session, KFC_CATALOG)


def test_multi_item_voice_extracts_hot_wings_and_quantities():
    msg = (
        "han ek zinger burger tu hogaya aab ek kaam karo 1 hot wings kardo "
        "ek pepsi kardo 2 chicken piece kardo 1 krusher kardo"
    )
    items = extract_order_items(msg, KFC_CATALOG)
    by_name = {i["item"]: i["quantity"] for i in items}
    assert by_name["Hot Wings (6 pcs)"] == 1
    assert by_name["Pepsi (1L)"] == 1
    assert by_name["Chicken Piece (1 pc)"] == 2
    assert by_name["Krusher"] == 1


def test_update_pending_keeps_existing_zinger_and_adds_new_items():
    session = _menu_session()
    before = list(session.pending_items)
    msg = "1 hot wings kardo ek pepsi kardo 2 chicken piece kardo 1 krusher kardo"
    update_pending_from_message(session, msg, KFC_CATALOG)
    assert pending_items_changed(before, session.pending_items)
    by_name = {i["item"]: i["quantity"] for i in session.pending_items}
    assert by_name["Zinger Burger"] == 1
    assert by_name["Hot Wings (6 pcs)"] == 1
    assert by_name["Pepsi (1L)"] == 1
    assert by_name["Chicken Piece (1 pc)"] == 2


@pytest.mark.asyncio
async def test_reply_after_items_added_lists_full_order():
    session = _menu_session()
    before = list(session.pending_items)
    update_pending_from_message(session, "ek pepsi bhi kardo", KFC_CATALOG)
    added = _labels_for_new_items(before, session.pending_items)
    reply = await _reply_after_items_added(session, "roman_ur", added_labels=added)
    assert "Pepsi" in reply
    assert "Zinger Burger" in reply
    assert "Add kar liya" in reply or "add" in reply.lower()


@pytest.mark.asyncio
async def test_correction_reply_after_wrong_order():
    from app.services.order_context import is_order_correction_message, update_pending_from_message
    from app.services.order_agent import _reply_after_items_added

    session = _menu_session()
    session.pending_items = [
        {"item": "Zinger Burger", "quantity": 2},
        {"item": "Fries (Large)", "quantity": 2},
    ]
    correction = (
        "wrong order. 1 fiz up next 2 fries, 2 chicken piece, "
        "1 zinger burger and 2 hot wings"
    )
    assert is_order_correction_message(correction)
    update_pending_from_message(session, correction, KFC_CATALOG)
    reply = await _reply_after_items_added(session, "en", corrected=True)
    assert "corrected" in reply.lower()
    assert "Chicken Piece" in reply
    assert "Hot Wings" in reply
    assert "1x Zinger Burger" in reply
    assert "ask_name" not in reply.lower()
