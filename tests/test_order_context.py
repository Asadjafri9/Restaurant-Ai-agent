from app.services.order_context import (
    extract_address,
    extract_customer_name,
    extract_order_items,
    fix_name_transcript,
    is_done_adding_items,
    merge_pending_items,
    pending_order_complete,
    update_pending_from_message,
)
from app.services.session_service import CustomerSession


def test_fix_kareer_to_askari():
    assert "Askari" in fix_name_transcript("kareer bhai")


def test_extract_name_explicit():
    assert extract_customer_name("mera naam askari hai") == "Askari"
    assert extract_customer_name("Askari") == "Askari"


def test_extract_name_not_from_address():
    assert extract_customer_name("Block C5") is None


def test_extract_address():
    assert extract_address("mera naam askari hai block c5 address hai") == "Block C5"
    assert extract_address("Block C5") == "Block C5"


def test_done_adding_still_detected():
    assert is_done_adding_items("nahi bas itna hi kardo")


def test_pending_order_tracking():
    session = CustomerSession(phone="+923001234567", active_tenant_slug="kfc")
    catalog = [{"name": "Cola Next", "price": 100}]
    update_pending_from_message(session, "jani kfc se cola next kardo", catalog)
    assert session.pending_items
    update_pending_from_message(session, "Askari", catalog)
    assert session.pending_customer_name == "Askari"
    update_pending_from_message(session, "mera naam askari hai block c5 address hai", catalog)
    assert session.pending_customer_name == "Askari"
    assert session.pending_address == "Block C5"
    assert pending_order_complete(session)


def test_name_correction_overwrites_kareer():
    session = CustomerSession(phone="+923001234567")
    update_pending_from_message(session, "Kareer", [])
    assert session.pending_customer_name == "Askari"
    update_pending_from_message(session, "mera naam askari hai", [])
    assert session.pending_customer_name == "Askari"


def test_extract_name_not_from_thank_you():
    assert extract_customer_name("shukriya") is None
    assert extract_customer_name("thank you") is None


def test_merge_items():
    merged = merge_pending_items(
        [{"item": "Cola Next", "quantity": 1, "unit_price": 100}],
        [{"item": "Cola Next", "quantity": 1, "unit_price": 100}],
    )
    assert merged[0]["quantity"] == 2


def test_match_chkn_briyani_to_chicken_biryani():
    from app.services.order_context import match_catalog_item

    catalog = [{"name": "Chicken Biryani", "price": 450, "tenant_item_id": "abc"}]
    hit = match_catalog_item("chkn briyani", catalog)
    assert hit is not None
    assert hit["name"] == "Chicken Biryani"


def test_extract_order_items_fuzzy_voice_name():
    catalog = [{"name": "Chicken Biryani", "price": 450, "tenant_item_id": "abc"}]
    items = extract_order_items("ek chkn briyani chahiye", catalog)
    assert len(items) == 1
    assert items[0]["item"] == "Chicken Biryani"
    assert items[0].get("menu_item_id") == "abc"


def test_multi_item_list_with_fizz_up_next():
    from app.data.restaurants import RESTAURANTS

    catalog = [
        {"name": i["item"], "price": i["price_pkr"], "tenant_item_id": str(i["id"])}
        for i in RESTAURANTS["kfc"]["menu"]
    ]
    msg = "1 fiz up next 2 fries, 2 chicken piece, 1 zinger burger and 2 hot wings"
    by_name = {i["item"]: i["quantity"] for i in extract_order_items(msg, catalog)}
    assert by_name == {
        "Fizz Up Next": 1,
        "Fries (Large)": 2,
        "Chicken Piece (1 pc)": 2,
        "Zinger Burger": 1,
        "Hot Wings (6 pcs)": 2,
    }


def test_hi_does_not_add_chicken_piece():
    from app.data.restaurants import RESTAURANTS

    catalog = [
        {"name": i["item"], "price": i["price_pkr"], "tenant_item_id": str(i["id"])}
        for i in RESTAURANTS["kfc"]["menu"]
    ]
    for msg in ("hi", "hello", "yes", "han kardo", "Block C5", "kfc", "menu dikhao", "shukriya"):
        items = extract_order_items(msg, catalog)
        assert not any(i["item"] == "Chicken Piece (1 pc)" for i in items), msg


def test_chicken_piece_requires_piece_word():
    from app.data.restaurants import RESTAURANTS

    catalog = [
        {"name": i["item"], "price": i["price_pkr"], "tenant_item_id": str(i["id"])}
        for i in RESTAURANTS["kfc"]["menu"]
    ]
    assert not extract_order_items("2 chicken", catalog)
    items = extract_order_items("2 chicken piece", catalog)
    assert len(items) == 1 and items[0]["item"] == "Chicken Piece (1 pc)"


def test_order_correction_replaces_pending_items():
    from app.data.restaurants import RESTAURANTS
    from app.services.order_context import is_order_correction_message

    catalog = [
        {"name": i["item"], "price": i["price_pkr"], "tenant_item_id": str(i["id"])}
        for i in RESTAURANTS["kfc"]["menu"]
    ]
    session = CustomerSession(
        phone="+923001234567",
        state="ordering",
        active_tenant_slug="kfc",
        pending_items=[
            {"item": "Zinger Burger", "quantity": 2},
            {"item": "Fries (Large)", "quantity": 2},
        ],
    )
    correction = (
        "you gave wrong order. 1 fiz up next 2 fries, 2 chicken piece, "
        "1 zinger burger and 2 hot wings"
    )
    assert is_order_correction_message(correction)
    update_pending_from_message(session, correction, catalog)
    by_name = {i["item"]: i["quantity"] for i in session.pending_items}
    assert by_name["Zinger Burger"] == 1
    assert by_name["Fries (Large)"] == 2
    assert by_name["Chicken Piece (1 pc)"] == 2
    assert by_name["Hot Wings (6 pcs)"] == 2
    assert by_name["Fizz Up Next"] == 1
