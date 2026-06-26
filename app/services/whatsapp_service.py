import logging
import time

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

_TOKEN_CACHE: tuple[bool, str | None, float] = (False, None, 0.0)
_TOKEN_CACHE_TTL = 300.0


def invalidate_whatsapp_token_cache() -> None:
    global _TOKEN_CACHE
    _TOKEN_CACHE = (False, None, 0.0)


async def verify_whatsapp_token() -> tuple[bool, str | None]:
    """Return (valid, error_message). Uses debug_token for expiry details."""
    token = settings.whatsapp_access_token.strip()
    if not token:
        return False, "WHATSAPP_ACCESS_TOKEN is not set"
    if not settings.whatsapp_phone_number_id.strip():
        return False, "WHATSAPP_PHONE_NUMBER_ID is not set"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/debug_token",
                params={"input_token": token, "access_token": token},
            )
            if not response.is_success:
                return False, response.text[:300]
            data = response.json().get("data", {})
            if not data.get("is_valid"):
                return False, data.get("error", {}).get("message") or "Token invalid"
            expires_at = data.get("expires_at")
            if expires_at and int(expires_at) > 0:
                if int(expires_at) <= int(time.time()):
                    return False, (
                        "WhatsApp access token expired — generate a new token in "
                        "Meta Developer Console (WhatsApp > API Setup) and update "
                        "WHATSAPP_ACCESS_TOKEN, then run scripts/sync_env_to_railway.ps1"
                    )
            return True, None
    except Exception as exc:
        logger.exception("WhatsApp token verification failed")
        return False, str(exc)


async def verify_whatsapp_token_cached() -> tuple[bool, str | None]:
    global _TOKEN_CACHE
    now = time.time()
    if now - _TOKEN_CACHE[2] < _TOKEN_CACHE_TTL:
        return _TOKEN_CACHE[0], _TOKEN_CACHE[1]
    ok, err = await verify_whatsapp_token()
    _TOKEN_CACHE = (ok, err, now)
    return ok, err


def _parse_whatsapp_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        return body.get("error", {}).get("message") or response.text[:300]
    except Exception:
        return response.text[:300]


def _messages_url() -> str:
    phone_id = settings.whatsapp_phone_number_id.strip()
    if not phone_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured")
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{phone_id}/messages"
    )


async def download_media(url: str) -> bytes:
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.content


async def get_media_url(media_id: str) -> str:
    if not media_id:
        raise ValueError("media_id is required")
    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{media_id}"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        media_url = data.get("url")
        if not media_url:
            raise ValueError("Media URL missing from Meta response")
        return media_url


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
            response = await client.post(_messages_url(), headers=headers, json=payload)
            response.raise_for_status()
    except Exception:
        logger.debug("mark_message_read failed for %s", message_id[:12])


def _media_upload_url() -> str:
    phone_id = settings.whatsapp_phone_number_id.strip()
    if not phone_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured")
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{phone_id}/media"
    )


async def upload_media(
    data: bytes,
    mime_type: str = "audio/mpeg",
    filename: str = "reply.mp3",
) -> str:
    """Upload media to WhatsApp Cloud API; returns media id."""
    if not data:
        raise ValueError("Empty media payload")
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    files = {"file": (filename, data, mime_type)}
    form = {"messaging_product": "whatsapp", "type": mime_type}
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            _media_upload_url(),
            headers=headers,
            data=form,
            files=files,
        )
        response.raise_for_status()
        media_id = response.json().get("id")
        if not media_id:
            raise ValueError("Media upload response missing id")
        return str(media_id)


async def send_audio_message(to: str, media_id: str) -> bool:
    if not settings.whatsapp_phone_number_id.strip():
        logger.error("Cannot send WhatsApp audio: WHATSAPP_PHONE_NUMBER_ID is missing")
        return False
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(_messages_url(), headers=headers, json=payload)
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError:
        err_text = _parse_whatsapp_error(response)
        logger.error("WhatsApp audio send failed (%s): %s", response.status_code, err_text)
        return False
    except Exception:
        logger.exception("Failed to send WhatsApp audio message")
        return False


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
        err_text = _parse_whatsapp_error(response)
        if response.status_code in (401, 403):
            invalidate_whatsapp_token_cache()
            logger.error(
                "WhatsApp send failed (%s): %s — regenerate WHATSAPP_ACCESS_TOKEN in "
                "Meta Developer Console and run scripts/sync_env_to_railway.ps1",
                response.status_code,
                err_text,
            )
        else:
            logger.error("WhatsApp API error (%s): %s", response.status_code, err_text)
        return False
    except Exception:
        logger.exception("Failed to send WhatsApp message")
        return False
