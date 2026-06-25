from sqlalchemy import inspect as sa_inspect

from app.db.models_central import OrderRoutingIndex


def test_routing_index_has_no_money_columns():
    mapper = sa_inspect(OrderRoutingIndex)
    col_names = {c.key for c in mapper.columns}
    forbidden = {"total", "amount", "balance", "revenue", "subtotal", "price"}
    assert not col_names & forbidden, f"Routing index must not have money columns: {col_names & forbidden}"


def test_order_status_transitions():
    from app.services.order_routing import ORDER_STATUSES

    assert "accepted" in ORDER_STATUSES["placed"]
    assert ORDER_STATUSES["delivered"] == []


def test_phone_hash_deterministic():
    from app.services.session_service import phone_hash

    assert phone_hash("+923001234567") == phone_hash("+923001234567")
    assert phone_hash("+923001234567") != phone_hash("+923009999999")
