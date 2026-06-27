"""Tests for the agent system prompt context (prompts.py).

The prompt is what the LLM sees. The bot's "real-agent" feel is driven by
the persona, the strict invariants, the bilingual rule, and the ORDER_JSON
schema. These tests pin the prompt's contract so regressions are loud.
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


def test_prompt_declares_persona_and_bilingual_rule_english():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        language="en",
    )
    assert "Aana" in prompt
    assert "Reply in English" in prompt
    assert "PKR" in prompt
    assert "No emojis" in prompt


def test_prompt_uses_roman_urdu_for_roman_ur_language():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        language="roman_ur",
    )
    assert "Roman Urdu" in prompt
    assert "Latin letters" in prompt
    assert "han kardo" in prompt


def test_prompt_includes_time_of_day_greeting_when_in_greeting_state():
    now = datetime(2026, 6, 27, 19, 30, tzinfo=timezone.utc)
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        state="greeting",
        language="en",
        now=now,
    )
    assert "Good evening" in prompt


def test_prompt_excludes_greeting_outside_greeting_state():
    now = datetime(2026, 6, 27, 19, 30, tzinfo=timezone.utc)
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        state="ordering",
        language="en",
        now=now,
    )
    assert "Good evening" not in prompt


def test_prompt_includes_welcome_back_for_returning_customer():
    last = {"restaurant": "kfc", "items": [{"item": "Zinger Burger", "quantity": 1}]}
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        state="greeting",
        language="en",
        last_order_summary=last,
    )
    assert "RETURNING CUSTOMER" in prompt
    assert "Zinger Burger" in prompt
    assert "kfc" in prompt


def test_prompt_includes_pending_state_block_when_customer_in_mid_order():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
        pending_name="Ali",
        pending_address="Block C5",
        pending_items=[{"item": "Zinger Burger", "quantity": 2}],
    )
    assert "ALREADY COLLECTED" in prompt
    assert "Ali" in prompt
    assert "Block C5" in prompt
    assert "2x Zinger Burger" in prompt


def test_prompt_explains_modifier_and_notes_handling():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
    )
    assert "notes" in prompt
    assert "no mayo" in prompt
    assert "extra spicy" in prompt


def test_prompt_lists_edit_intents():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
    )
    assert "EDIT INTENT EXAMPLES" in prompt
    assert "remove the biryani" in prompt
    assert "make that 2" in prompt
    assert "same as last time" in prompt


def test_prompt_includes_extended_order_json_schema_with_notes_and_special_requests():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="confirming",
        language="en",
    )
    assert "[ORDER_JSON]" in prompt
    assert "[/ORDER_JSON]" in prompt
    assert '"notes"' in prompt
    assert '"special_requests"' in prompt


def test_prompt_emits_general_knowledge_about_delivery_eta():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        language="en",
    )
    assert "45-60" in prompt


def test_prompt_forbids_inventing_menu_items():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        language="en",
    )
    assert "Never invent" in prompt
    assert "Source of truth" in prompt


def test_prompt_active_restaurant_scope_restricts_to_chosen_restaurant():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
    )
    assert "ONLY" in prompt
    assert "KFC" in prompt
    assert "kfc" in prompt


def test_prompt_no_restaurant_yet_lists_both():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        state="greeting",
        language="en",
    )
    assert "KFC" in prompt
    assert "kababjees" in prompt


def test_prompt_collecting_details_flag_adds_continue_only_directive():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
        collecting_details=True,
    )
    assert "Continue collecting order details only" in prompt


def test_prompt_categories_param_appended_as_recommendation_hint():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        active_restaurant="KFC",
        active_slug="kfc",
        state="ordering",
        language="en",
        categories=["Burgers", "Drinks", "Combos"],
    )
    assert "CATEGORIES" in prompt
    assert "Burgers" in prompt
    assert "Drinks" in prompt
    assert "Combos" in prompt


def test_format_grouped_menu_groups_by_category():
    text = format_grouped_menu(MENU)
    assert "[Burgers]" in text
    assert "[Drinks]" in text
    assert "Zinger Burger" in text
    assert "Cola Next" in text


def test_format_grouped_menu_falls_back_to_flat_when_no_categories():
    flat_items = [
        {"name": "Item A", "price": 100, "category": None},
        {"name": "Item B", "price": 200, "category": None},
    ]
    text = format_grouped_menu(flat_items)
    assert "Item A" in text
    assert "Item B" in text
    assert "[" not in text


def test_format_grouped_menu_empty_returns_empty_marker():
    assert format_grouped_menu([]) == "(menu empty)"


def test_unique_categories_returns_preserves_first_seen_order():
    items = [
        {"name": "A", "category": "Drinks"},
        {"name": "B", "category": "Burgers"},
        {"name": "C", "category": "Drinks"},
        {"name": "D", "category": None},
    ]
    cats = unique_categories(items)
    assert cats == ["Drinks", "Burgers"]


def test_prompt_warns_about_one_question_at_a_time():
    prompt = build_system_prompt(
        restaurants=RESTAURANTS,
        menu_block="(none)",
        language="en",
    )
    assert "ONE question at a time" in prompt
