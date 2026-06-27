"""Tests for the agent system prompt contract (prompts.py).

The prompt is the LLM's contract: it tells the model the persona, the
bilingual rule, the JSON output format, the cart block, and the menu.
These tests pin the contract so regressions are loud.
"""

from datetime import datetime, timezone

from app.services.agent.prompts import (
    build_system_prompt,
    format_grouped_menu,
    unique_categories,
)


RESTAURANTS = [
    {"name": "KFC", "slug": "kfc"},
    {"name": "Kababjees", "slug": "kababjees"},
]

MENU = [
    {"name": "Zinger Burger", "price": 450, "category": "Burgers"},
    {"name": "Hot Wings (6 pcs)", "price": 600, "category": "Burgers"},
    {"name": "Cola Next", "price": 120, "category": "Drinks"},
    {"name": "Krusher", "price": 250, "category": "Drinks"},
]


def test_prompt_has_persona():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "Aana" in p
    assert "WhatsApp" in p


def test_prompt_english_language_rule():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "Reply text in English" in p


def test_prompt_roman_urdu_language_rule():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="roman_ur")
    assert "Roman Urdu" in p


def test_prompt_declares_json_output_contract():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "OUTPUT CONTRACT" in p
    assert '"reply"' in p
    assert '"items"' in p
    assert '"place_order"' in p
    assert '"customer_name"' in p
    assert '"address"' in p
    assert '"special_requests"' in p
    assert '"notes"' in p


def test_prompt_enforces_cart_is_full_state_not_delta():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "FULL" in p and ("cart" in p.lower() or "current cart" in p.lower())


def test_prompt_forbids_inventing_items():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "Never invent" in p
    assert "menu" in p.lower()


def test_prompt_place_order_only_on_clear_confirm_with_all_details():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "place_order" in p
    assert "true" in p.lower()
    assert "YES" in p or "confirm" in p.lower()


def test_prompt_keeps_replies_short():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "2-5" in p or "short" in p.lower()


def test_prompt_no_emojis():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "No emojis" in p or "no emoji" in p.lower()


def test_prompt_currency_pkr():
    p = build_system_prompt(restaurants=RESTAURANTS, menu_block="(none)", language="en")
    assert "PKR" in p


def test_prompt_passes_through_cart_state():
    """When pending items/name/address are passed, they appear in the prompt
    so the LLM knows the current state."""
    p = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
        pending_name="Asad",
        pending_address="Block C5",
        pending_items=[{"item": "Krusher", "quantity": 2}],
    )
    assert "Asad" in p
    assert "Block C5" in p
    assert "Krusher" in p
    assert "Current cart" in p


def test_prompt_greeting_state_shows_time_of_day():
    now = datetime(2026, 6, 27, 8, 30, tzinfo=timezone.utc)
    p = build_system_prompt(
        restaurants=RESTAURANTS, menu_block="(none)", state="greeting", language="en", now=now
    )
    assert "Good morning" in p


def test_prompt_no_greeting_outside_greeting_state():
    now = datetime(2026, 6, 27, 8, 30, tzinfo=timezone.utc)
    p = build_system_prompt(
        restaurants=RESTAURANTS, menu_block="(none)", state="ordering", language="en", now=now
    )
    assert "Good morning" not in p


def test_prompt_welcome_back_when_returning_customer():
    last = {"restaurant": "kfc", "items": [{"item": "Krusher", "quantity": 1}]}
    p = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        state="greeting",
        language="en",
        last_order_summary=last,
    )
    assert "RETURNING CUSTOMER" in p
    assert "Krusher" in p


def test_prompt_categories_hint_when_provided():
    p = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_slug="kfc",
        state="ordering",
        language="en",
        categories=["Burgers", "Drinks"],
    )
    assert "Burgers" in p
    assert "Drinks" in p


def test_format_grouped_menu_groups_by_category():
    text = format_grouped_menu(MENU)
    assert "[Burgers]" in text
    assert "[Drinks]" in text
    assert "Zinger Burger" in text
    assert "Cola Next" in text


def test_format_grouped_menu_flat_when_no_categories():
    flat = [
        {"name": "A", "price": 100, "category": None},
        {"name": "B", "price": 200, "category": None},
    ]
    text = format_grouped_menu(flat)
    assert "A" in text
    assert "B" in text
    assert "[" not in text


def test_format_grouped_menu_empty():
    assert format_grouped_menu([]) == "(menu empty)"


def test_unique_categories_preserves_order():
    items = [
        {"name": "A", "category": "Drinks"},
        {"name": "B", "category": "Burgers"},
        {"name": "C", "category": "Drinks"},
        {"name": "D", "category": None},
    ]
    assert unique_categories(items) == ["Drinks", "Burgers"]