import logging

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

def _messages_url() -> str:
    phone_id = settings.whatsapp_phone_number_id.strip()
    if not phone_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured")
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{phone_id}/messages"
    )


async def mark_message_read(message_id: str) -> None:
    if not message_id or not settings.whatsapp_phone_number_id.strip():
        return
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(_messages_url(), headers=headers, json=payload)
    except Exception:
        logger.debug("mark_message_read failed for %s", message_id[:12])


async def send_text_message(to: str, message: str) -> bool:
    if not settings.whatsapp_phone_number_id.strip():
        logger.error("Cannot send WhatsApp message: WHATSAPP_PHONE_NUMBER_ID is missing")
        return False
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _messages_url(),
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError:
        if response.status_code == 401:
            logger.error(
                "WhatsApp access token invalid or expired — update WHATSAPP_ACCESS_TOKEN in .env and run scripts/sync_env_to_railway.ps1"
            )
        logger.exception(
            "WhatsApp API error: %s",
            response.text if "response" in locals() else "unknown",
        )
        return False
    except Exception:
        logger.exception("Failed to send WhatsApp message")
        return False
