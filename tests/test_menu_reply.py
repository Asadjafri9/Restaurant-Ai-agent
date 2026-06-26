import pytest

from app.services.order_agent import _reply_with_menu
from app.services.order_context import extract_order_items, update_pending_from_message
from app.services.session_service import CustomerSession
from app.services.voice_text import is_menu_request


@pytest.mark.asyncio
async def test_menu_reply_acknowledges_item_and_shows_full_menu(monkeypatch):
    catalog = [
        {"name": "Chicken Biryani", "price": 450},
        {"name": "Beef Kabab Roll", "price": 350},
        {"name": "Seekh Kabab (2 pcs)", "price": 400},
        {"name": "Chicken Karahi (Half)", "price": 850},
        {"name": "Garlic Naan", "price": 60},
        {"name": "Raita", "price": 80},
        {"name": "Chicken Tikka (4 pcs)", "price": 550},
    ]

    async def fake_get_menu(slug, force_refresh=False):
        return "tenant-id", catalog

    monkeypatch.setattr("app.services.order_agent.get_menu_by_slug", fake_get_menu)

    session = CustomerSession(phone="+923001234567", language="roman_ur")
    msg = (
        "mujhay kababjees se ek chicken biryani order karni hai "
        "and mujhay kababjees ka menu bhi bhejdo"
    )
    assert is_menu_request(msg)
    update_pending_from_message(session, msg, catalog)
    assert session.pending_items
    assert session.pending_items[0]["item"] == "Chicken Biryani"

    reply = await _reply_with_menu(
        "kababjees",
        [{"slug": "kababjees", "name": "Kababjees"}],
        False,
        "roman_ur",
        session,
    )
    assert "Chicken Biryani" in reply
    assert "note kar liya" in reply or "order note" in reply.lower()
    assert "1x Chicken Biryani" in reply or "1x" in reply
    assert "Beef Kabab Roll" in reply
    assert "Garlic Naan" in reply
    assert "Kuch aur order" in reply or "kuch aur" in reply.lower()
    assert "Rs 250" not in reply


@pytest.mark.asyncio
async def test_try_serve_catalog_menu_blocks_llm_path(monkeypatch):
    catalog = [
        {"name": "Chicken Biryani", "price": 450},
        {"name": "Beef Kabab Roll", "price": 350},
        {"name": "Seekh Kabab (2 pcs)", "price": 400},
        {"name": "Chicken Karahi (Half)", "price": 850},
        {"name": "Garlic Naan", "price": 60},
        {"name": "Raita", "price": 80},
        {"name": "Chicken Tikka (4 pcs)", "price": 550},
    ]
    restaurants = [{"slug": "kababjees", "name": "Kababjees"}, {"slug": "kfc", "name": "KFC"}]

    async def fake_get_menu(slug, force_refresh=False):
        return "tid", catalog

    monkeypatch.setattr("app.services.order_agent.get_menu_by_slug", fake_get_menu)

    from app.services.order_agent import _try_serve_catalog_menu

    session = CustomerSession(phone="+923001234567", language="en", active_tenant_slug="kababjees", state="ordering")
    msg = "You've chosen Kababjees. I want chicken biryani. Send the menu please."
    reply = await _try_serve_catalog_menu(session, msg, restaurants)
    assert reply is not None
    assert "Garlic Naan" in reply
    assert "Seekh Kabab" in reply
    assert "Rs 250" not in reply
    assert len([l for l in reply.splitlines() if "Rs" in l]) >= 7


def test_extract_birayani_typo():
    catalog = [{"name": "Chicken Biryani", "price": 450}]
    items = extract_order_items("ek chicken birayani order karni hai", catalog)
    assert len(items) == 1
    assert items[0]["item"] == "Chicken Biryani"
