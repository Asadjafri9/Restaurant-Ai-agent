import json
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from app.config.settings import settings
from app.core.webhook_security import verify_webhook_signature
from app.db.redis_client import redis_dedupe
from app.services.i18n import msg
from app.services.session_service import get_session_async
from app.services.speech_service import transcribe
from app.services.tts_service import synthesize_speech, voice_reply_available
from app.services.whatsapp_service import (
    download_media,
    get_media_url,
    invalidate_whatsapp_token_cache,
    mark_message_read,
    send_audio_message,
    send_text_message,
    upload_media,
    verify_whatsapp_token_cached,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def extract_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        entry = payload.get("entry", [])
        if not entry:
            return None
        changes = entry[0].get("changes", [])
        if not changes:
            return None
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None
        message = messages[0]
        phone_number = message.get("from", "").strip()
        message_id = message.get("id", "").strip()
        if not phone_number:
            return None

        msg_type = message.get("type")

        if msg_type == "text":
            text_body = message.get("text", {}).get("body", "").strip()
            if not text_body:
                return None
            return {
                "phone_number": phone_number,
                "message": text_body,
                "message_id": message_id,
                "input_type": "text",
            }

        if msg_type in ("audio", "voice"):
            audio = message.get("audio") or message.get("voice") or {}
            media_id = (audio.get("id") or "").strip()
            if not media_id:
                return None
            return {
                "phone_number": phone_number,
                "message_id": message_id,
                "media_id": media_id,
                "mime_type": audio.get("mime_type", "audio/ogg"),
                "input_type": "audio",
            }

        return {
            "phone_number": phone_number,
            "message_id": message_id,
            "input_type": "unsupported",
        }
    except (IndexError, KeyError, TypeError, AttributeError):
        logger.exception("Failed to parse WhatsApp webhook payload")
        return None


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> Response:
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("Webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="Forbidden")


async def _send_reply(
    phone_number: str,
    text: str,
    *,
    reply_with_voice: bool,
) -> bool:
    """Send text; for voice notes also attach a voice reply when TTS is available."""
    sent_text = await send_text_message(phone_number, text)
    sent_voice = False

    if reply_with_voice and voice_reply_available():
        try:
            audio_bytes = await synthesize_speech(text)
            media_id = await upload_media(audio_bytes, "audio/mpeg", "reply.mp3")
            sent_voice = await send_audio_message(phone_number, media_id)
            if not sent_voice:
                logger.warning("Voice reply send failed — text reply already sent=%s", sent_text)
        except Exception:
            logger.exception("Voice reply synthesis/upload failed — text reply already sent=%s", sent_text)

    return sent_text or sent_voice


async def _handle_incoming_message(message_data: dict[str, Any]) -> None:
    phone_number = message_data["phone_number"]
    input_type = message_data.get("input_type", "text")
    lang = "en"

    try:
        wa_ok, wa_err = await verify_whatsapp_token_cached()
        if not wa_ok:
            logger.error(
                "WhatsApp token invalid — replies may fail. %s",
                (wa_err or "")[:200],
            )
            if wa_err and "expired" in wa_err.lower():
                invalidate_whatsapp_token_cache()

        logger.info(
            "Processing %s message from %s",
            input_type,
            phone_number[:6] + "***",
        )

        session = await get_session_async(phone_number)
        lang = session.language

        if input_type == "unsupported":
            await send_text_message(phone_number, msg("unsupported_media", lang))
            return

        user_message = message_data.get("message", "")

        if input_type == "audio":
            await send_text_message(phone_number, msg("voice_ack", lang))
            try:
                media_url = await get_media_url(message_data["media_id"])
                audio_bytes = await download_media(media_url)
                user_message = await transcribe(
                    audio_bytes, message_data.get("mime_type", "audio/ogg")
                )
                if not user_message.strip():
                    raise ValueError("Empty transcript")
                logger.info(
                    "Voice transcript for %s: %s",
                    phone_number[:6] + "***",
                    user_message[:200],
                )
            except Exception:
                logger.exception("Voice transcription failed for %s", phone_number[:6] + "***")
                await send_text_message(phone_number, msg("voice_fail", lang))
                return

        from app.services.order_agent import process_order_message_async

        t0 = time.perf_counter()
        ai_response = await process_order_message_async(phone_number, user_message)
        if not (ai_response or "").strip():
            ai_response = msg("fallback", lang)
        sent = await _send_reply(
            phone_number,
            ai_response,
            reply_with_voice=(input_type == "audio"),
        )
        logger.info(
            "Webhook pipeline for %s: reply_sent=%s voice=%s total=%.2fs",
            phone_number[:6] + "***",
            sent,
            input_type == "audio" and voice_reply_available(),
            time.perf_counter() - t0,
        )
        if not sent:
            logger.error("Failed to send reply to %s", phone_number[:6] + "***")
    except Exception:
        logger.exception("Webhook handler failed for %s", phone_number[:6] + "***")
        try:
            await send_text_message(phone_number, msg("fallback", lang))
        except Exception:
            logger.exception("Could not send fallback reply to %s", phone_number[:6] + "***")


@router.post("/webhook")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str]:
    body = await request.body()
    try:
        verify_webhook_signature(request, body)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Signature verification error")
        return {"status": "ok"}

    try:
        payload = json.loads(body)
    except Exception:
        logger.exception("Invalid webhook payload")
        return {"status": "ok"}

    message_data = extract_message(payload)
    if not message_data:
        return {"status": "ok"}

    message_id = message_data.get("message_id")
    if message_id:
        try:
            is_new = await redis_dedupe(f"wamid:{message_id}", 600)
            if not is_new:
                logger.info("Duplicate message %s skipped", message_id)
                return {"status": "ok"}
        except Exception:
            logger.exception("Dedupe check failed — processing anyway")

    background_tasks.add_task(_handle_incoming_message, message_data)

    if message_id:
        background_tasks.add_task(mark_message_read, message_id)

    return {"status": "ok"}
