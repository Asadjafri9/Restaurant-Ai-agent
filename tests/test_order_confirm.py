from app.services.order_agent import (
    _conversation_awaiting_confirm,
    _is_no_message,
    _is_yes_message,
)
from app.services.voice_text import normalize_user_text as _normalize_user_text
from app.services.session_service import CustomerSession


def test_normalize_strips_voice_punctuation():
    assert _normalize_user_text("Yes.") == "yes"
    assert _normalize_user_text("  Han kardo!  ") == "han kardo"


def test_is_yes_message_english_and_roman_urdu():
    assert _is_yes_message("yes")
    assert _is_yes_message("Yes.")
    assert _is_yes_message("han kardo")
    assert _is_yes_message("Haan kar do")
    assert _is_yes_message("ji haan")
    assert _is_yes_message("theek hai")
    assert not _is_yes_message("no thanks")
    assert not _is_yes_message("kfc menu")


def test_is_no_message():
    assert _is_no_message("nahi")
    assert _is_no_message("No.")
    assert not _is_no_message("han")


def test_awaiting_confirm_from_last_bot_summary():
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        history=[
            {"role": "user", "parts": ["2 zinger"]},
            {
                "role": "model",
                "parts": [
                    "Order summary:\n2x Zinger — Rs 800\nTotal: Rs 800\nYES likhein confirm karne ke liye."
                ],
            },
        ],
    )
    assert _conversation_awaiting_confirm(session)


def test_awaiting_confirm_when_state_confirming():
    session = CustomerSession(phone="+923001234567", state="confirming", history=[])
    assert _conversation_awaiting_confirm(session)


def test_confirm_reply_voice_garbled_hun_kardo():
    from app.services.order_agent import _is_confirm_reply

    session = CustomerSession(
        phone="+923001234567",
        state="confirming",
        awaiting_confirm=True,
        history=[
            {
                "role": "model",
                "parts": ["Order summary:\n1x Chicken Biryani — Rs 450\nYES likhein confirm karne ke liye."],
            }
        ],
    )
    assert _is_confirm_reply("hun kardo", session)
    assert _is_confirm_reply("ji haan", session)
    assert not _is_confirm_reply("shukriya", session)
    assert not _is_confirm_reply("shukria", session)
