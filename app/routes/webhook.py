import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from app.config.settings import settings
from app.core.webhook_security import verify_webhook_signature
from app.db.redis_client import redis_dedupe
from app.services.whatsapp_service import mark_message_read, send_text_message

logger = logging.getLogger(__name__)

router = APIRouter()


def extract_message(payload: dict[str, Any]) -> dict[str, str] | None:
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
        if message.get("type") != "text":
            return None
        text_body = message.get("text", {}).get("body", "").strip()
        phone_number = message.get("from", "").strip()
        message_id = message.get("id", "").strip()
        if not phone_number or not text_body:
            return None
        return {
            "phone_number": phone_number,
            "message": text_body,
            "message_id": message_id,
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


async def _handle_incoming_message(
    phone_number: str, user_message: str, message_id: str = ""
) -> None:
    logger.info("Processing message from %s", phone_number[:6] + "***")
    from app.services.order_agent import process_order_message_async

    t0 = time.perf_counter()
    ai_response = await process_order_message_async(phone_number, user_message)
    sent = await send_text_message(phone_number, ai_response)
    logger.info(
        "Webhook pipeline for %s: reply_sent=%s total=%.2fs",
        phone_number[:6] + "***",
        sent,
        time.perf_counter() - t0,
    )
    if not sent:
        logger.error("Failed to send reply to %s", phone_number[:6] + "***")


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

    import json

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
        asyncio.create_task(mark_message_read(message_id))

    background_tasks.add_task(
        _handle_incoming_message,
        message_data["phone_number"],
        message_data["message"],
        message_id or "",
    )
    return {"status": "ok"}
