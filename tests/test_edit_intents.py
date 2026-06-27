"""Tests for order edit-intent helpers and voice-text intent helpers."""

from app.services.order_context import (
    apply_pending_edit,
    detect_remove_intent,
    detect_set_qty_intent,
)
from app.services.session_service import CustomerSession
from app.services.voice_text import has_modifier_cue, has_remove_cue, is_question_message


CATALOG = [
    {"name": "Zinger Burger", "price": 450, "category": "Burgers"},
    {"name": "Cola Next", "price": 120, "category": "Drinks"},
    {"name": "Chicken Biryani", "price": 450, "category": "Mains"},
    {"name": "Hot Wings (6 pcs)", "price": 600, "category": "Burgers"},
]


def test_detect_remove_urdu_hatao():
    assert detect_remove_intent("biryani hatao bhai", CATALOG) == "Chicken Biryani"


def test_detect_remove_english_cancel():
    assert detect_remove_intent("cancel the zinger", CATALOG) == "Zinger Burger"


def test_detect_remove_wo_nahi_chahiye_returns_none_without_context():
    """'wo nahi chahiye' needs conversation context; detector returns None conservatively."""
    assert detect_remove_intent("wo nahi chahiye", CATALOG) is None


def test_detect_remove_thank_you_returns_none():
    assert detect_remove_intent("thanks bhai", CATALOG) is None


def test_detect_remove_done_adding_returns_none():
    assert detect_remove_intent("kuch aur nahi", CATALOG) is None


def test_detect_remove_wings():
    assert detect_remove_intent("wings hatao", CATALOG) == "Hot Wings (6 pcs)"


def test_detect_set_qty_urdu():
    assert detect_set_qty_intent("2 zinger chahiye", CATALOG) == ("Zinger Burger", 2)


def test_detect_set_qty_english_make_it():
    assert detect_set_qty_intent("make it 3 zinger", CATALOG) == ("Zinger Burger", 3)


def test_detect_set_qty_word_after_item():
    assert detect_set_qty_intent("zinger 2 chahiye", CATALOG) == ("Zinger Burger", 2)


def test_detect_set_qty_no_number_returns_none():
    assert detect_set_qty_intent("kuch aur nahi", CATALOG) is None


def test_detect_set_qty_drink():
    assert detect_set_qty_intent("3 cola next", CATALOG) == ("Cola Next", 3)


def test_detect_set_qty_wings():
    assert detect_set_qty_intent("give me 4 wings", CATALOG) == ("Hot Wings (6 pcs)", 4)


def test_apply_pending_edit_remove():
    s = CustomerSession(
        phone="+923001234567",
        pending_items=[
            {"item": "Zinger Burger", "quantity": 1},
            {"item": "Cola Next", "quantity": 2},
        ],
    )
    apply_pending_edit(s, remove="Cola Next")
    assert len(s.pending_items) == 1
    assert s.pending_items[0]["item"] == "Zinger Burger"


def test_apply_pending_edit_set_qty_existing():
    s = CustomerSession(
        phone="+923001234567",
        pending_items=[{"item": "Zinger Burger", "quantity": 1}],
    )
    apply_pending_edit(s, set_qty=("Zinger Burger", 5))
    assert s.pending_items[0]["quantity"] == 5


def test_apply_pending_edit_set_qty_new_adds_to_cart():
    s = CustomerSession(phone="+923001234567", pending_items=[])
    apply_pending_edit(s, set_qty=("Cola Next", 2))
    assert s.pending_items == [{"item": "Cola Next", "quantity": 2}]


def test_apply_pending_edit_remove_missing_no_op():
    s = CustomerSession(
        phone="+923001234567",
        pending_items=[{"item": "Zinger Burger", "quantity": 1}],
    )
    apply_pending_edit(s, remove="Cola Next")
    assert s.pending_items == [{"item": "Zinger Burger", "quantity": 1}]


def test_is_question_message_with_question_mark():
    assert is_question_message("how long is delivery?")


def test_is_question_message_with_how():
    assert is_question_message("how spicy is the zinger")


def test_is_question_message_with_kya():
    assert is_question_message("kya hai aap ke pas")


def test_is_question_message_with_kitna():
    assert is_question_message("kitne ka hai biryani")


def test_is_question_message_order_is_not_question():
    assert not is_question_message("ek zinger chahiye")
    assert not is_question_message("zinger 2 chahiye")
    assert not is_question_message("biryani hatao")


def test_has_modifier_cue_no_mayo():
    assert has_modifier_cue("zinger without mayo")


def test_has_modifier_cue_extra_spicy():
    assert has_modifier_cue("make it extra spicy")


def test_has_modifier_cue_no_cue_returns_false():
    assert not has_modifier_cue("zinger chahiye")
    assert not has_modifier_cue("2 zinger please")
    assert not has_modifier_cue("biryani hatao")


def test_has_remove_cue_urdu():
    assert has_remove_cue("biryani hatao")


def test_has_remove_cue_english():
    assert has_remove_cue("cancel the zinger")


def test_has_remove_cue_thank_you_false():
    assert not has_remove_cue("thanks bhai")
    assert not has_remove_cue("shukriya")
