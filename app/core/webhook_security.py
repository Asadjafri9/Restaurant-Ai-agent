import hashlib
import hmac
import logging

from fastapi import HTTPException, Request

from app.config.settings import settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(request: Request, body: bytes) -> None:
    if not settings.webhook_signature_required:
        return
    if not settings.whatsapp_app_secret:
        if settings.environment == "production":
            raise HTTPException(status_code=500, detail="Webhook secret not configured")
        logger.warning("WHATSAPP_APP_SECRET not set — skipping signature verification")
        return

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature:
        logger.warning("Missing X-Hub-Signature-256 header")
        raise HTTPException(status_code=403, detail="Missing signature")

    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")
