from app.services.order_agent import _is_yes_message
from app.services.voice_text import (
    has_non_latin_script,
    is_menu_request,
    is_mid_order_detail_reply,
    message_mentions_items,
    normalize_transcript,
    normalize_user_text,
    resolve_restaurant_slug,
    should_show_restaurant_menu,
)
from app.services.session_service import CustomerSession


def test_resolve_kfc_from_roman_urdu_voice():
    restaurants = [{"slug": "kfc", "name": "KFC"}, {"slug": "kababjees", "name": "Kababjees"}]
    msg = "jani ek kfc se cola next order kardo"
    assert resolve_restaurant_slug(msg, restaurants) == "kfc"


def test_resolve_kfc_from_spelled_out_transcript():
    restaurants = [{"slug": "kfc", "name": "KFC"}, {"slug": "kababjees", "name": "Kababjees"}]
    assert resolve_restaurant_slug("k f c se zinger", restaurants) == "kfc"


def test_normalize_transcript_brand_names():
    assert "kfc" in normalize_transcript("K F C se order").lower()
    assert "cola next" in normalize_transcript("Colla Next chahiye").lower()
    assert "block" in normalize_transcript("Blog C5").lower()


def test_menu_request_roman_urdu():
    assert is_menu_request("menu dikhao")
    assert is_menu_request("bhai menu bata do")
    assert is_menu_request("show menu bhi")
    assert not is_menu_request("kfc se zinger chahiye")


def test_message_mentions_items():
    items = [{"name": "Cola Next"}, {"name": "Zinger Burger"}]
    assert message_mentions_items("jani ek kfc se cola next order kardo", items)
    assert not message_mentions_items("menu dikhao", items)


def test_order_kardo_is_not_yes_confirmation():
    assert not _is_yes_message("jani ek kfc se cola next order kardo")
    assert _is_yes_message("han kardo")
    assert _is_yes_message("yes")


def test_yes_from_urdu_script_and_garbled_whisper():
    assert _is_yes_message("ہاں کل دو order confirm کل دو")
    assert _is_yes_message("हाँ confirm")


def test_mid_order_address_not_menu_pick():
    session = CustomerSession(phone="+923001234567", state="ordering", active_tenant_slug="kfc")
    assert is_mid_order_detail_reply("Block C5")
    assert is_mid_order_detail_reply("Blog C5")
    items = [{"name": "Cola Next"}]
    assert not should_show_restaurant_menu("Block C5", "kfc", session, items)


def test_should_show_kfc_menu_on_first_pick():
    session = CustomerSession(phone="+923001234567", state="greeting")
    items = [{"name": "Zinger Burger"}]
    assert should_show_restaurant_menu("i want to order from kfc", "kfc", session, items)
    assert should_show_restaurant_menu("kfc se order karna hai", "kfc", session, items)


def test_should_show_kababjees_menu_despite_kabab_item_name():
    session = CustomerSession(phone="+923001234567", state="greeting")
    items = [{"name": "Beef Kabab Roll"}, {"name": "Chicken Biryani"}]
    assert should_show_restaurant_menu("mujhay kababjees se order karna hai", "kababjees", session, items)


def test_menu_plus_item_from_kababjees():
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
    )
    items = [{"name": "Chicken Biryani", "price": 450}]
    msg = (
        "mujhay kababjees se ke chicken biryani order karni hai "
        "and menu bhi dekha do mujhay kabab jee ka"
    )
    assert resolve_restaurant_slug(msg, [{"slug": "kfc", "name": "KFC"}, {"slug": "kababjees", "name": "Kababjees"}]) == "kababjees"
    assert should_show_restaurant_menu(msg, "kababjees", session, items)


def test_kabab_jee_spelling_resolves():
    restaurants = [{"slug": "kfc", "name": "KFC"}, {"slug": "kababjees", "name": "Kababjees"}]
    assert resolve_restaurant_slug("mujhay kabab jee ka menu dikhao", restaurants) == "kababjees"


def test_kababjees_not_matched_as_menu_item():
    items = [{"name": "Beef Kabab Roll"}, {"name": "Chicken Biryani"}]
    assert not message_mentions_items("mujhay kababjees se order karna hai", items)
    assert message_mentions_items("ek beef kabab roll chahiye", items)


def test_should_not_redump_menu_mid_order_with_items():
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[{"item": "Zinger Burger", "quantity": 1}],
    )
    items = [{"name": "Zinger Burger"}]
    assert not should_show_restaurant_menu("kfc", "kfc", session, items)


def test_has_non_latin_script():
    assert has_non_latin_script("جانی kfc se cola")
    assert not has_non_latin_script("jani kfc se cola")


def test_normalize_user_text():
    assert normalize_user_text("Yes.") == "yes"


def test_shukriya_is_thank_you_not_order_detail():
    from app.services.voice_text import is_thank_you_message

    assert is_thank_you_message("shukriya")
    assert is_thank_you_message("shukria")
    assert is_thank_you_message("thank you")
    assert is_thank_you_message("bahut shukriya bhai")
    assert is_thank_you_message("شکریہ")
    assert is_thank_you_message("shukreeya")
    assert not is_thank_you_message("kfc se cola next")
    assert not is_mid_order_detail_reply("shukriya")
