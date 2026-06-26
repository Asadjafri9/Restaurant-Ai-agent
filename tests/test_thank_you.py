import pytest

from app.services.i18n import msg
from app.services.order_agent import _order_recently_completed, process_order_message_async
from app.services.session_service import CustomerSession


@pytest.mark.asyncio
async def test_shukriya_after_order_summary_gets_closing(monkeypatch):
    session = CustomerSession(
        phone="+923001234567",
        state="confirming",
        language="roman_ur",
        active_tenant_slug="kababjees",
        pending_customer_name="Askari",
        pending_address="Block C5",
        pending_items=[{"item": "Chicken Biryani", "quantity": 1}],
        history=[
            {
                "role": "model",
                "parts": [
                    "kababjees se ek chkn briyani ka order hai, naam Askari, address C5 block, "
                    "Total Rs 450. YES ya han kardo likhein confirm karne ke liye."
                ],
            }
        ],
    )

    async def fake_get_session(phone):
        return session

    async def fake_restaurants():
        return [{"slug": "kababjees", "name": "Kababjees"}]

    async def fake_save(s):
        pass

    monkeypatch.setattr("app.services.order_agent.get_session_async", fake_get_session)
    monkeypatch.setattr("app.services.order_agent.list_active_restaurants", fake_restaurants)
    monkeypatch.setattr("app.services.order_agent.save_session_async", fake_save)

    reply = await process_order_message_async("+923001234567", "shukriya")
    assert "naam" not in reply.lower() or "shukriya" in reply.lower()
    assert "khushi" in reply.lower() or "shukriya" in reply.lower()
    assert session.pending_customer_name == "Askari"


@pytest.mark.asyncio
async def test_shukriya_after_order_gets_closing_reply(monkeypatch):
    session = CustomerSession(
        phone="+923001234567",
        state="done",
        language="roman_ur",
        active_tenant_slug="kfc",
        history=[
            {
                "role": "model",
                "parts": [
                    "Order confirm ho gaya! Total: Rs 100\nOrder ID: #ABC12345\nDelivery: 45-60 minute."
                ],
            }
        ],
    )

    async def fake_get_session(phone):
        return session

    async def fake_restaurants():
        return [{"slug": "kfc", "name": "KFC"}]

    async def fake_save(s):
        pass

    monkeypatch.setattr("app.services.order_agent.get_session_async", fake_get_session)
    monkeypatch.setattr("app.services.order_agent.list_active_restaurants", fake_restaurants)
    monkeypatch.setattr("app.services.order_agent.save_session_async", fake_save)

    reply = await process_order_message_async("+923001234567", "shukriya")
    assert "shukriya" in reply.lower() or "khushi" in reply.lower()
    assert "address" not in reply.lower()
    assert "cola" not in reply.lower()


def test_order_recently_completed_detects_done_state():
    session = CustomerSession(phone="+923001234567", state="done")
    assert _order_recently_completed(session)


def test_order_recently_completed_from_confirmation_message():
    session = CustomerSession(
        phone="+923001234567",
        history=[{"role": "model", "parts": ["Order confirmed! Total: Rs 500\nOrder ID: #ABCDEF12"]}],
    )
    assert _order_recently_completed(session)


def test_thank_you_closing_message_templates():
    assert "welcome" in msg("thank_you_closing", "en").lower()
    assert "shukriya" in msg("thank_you_closing", "roman_ur").lower()
