"""Speech-to-text via Groq Whisper."""

import logging

import httpx

from app.config.settings import settings
from app.services.voice_text import WHISPER_ORDER_PROMPT, ensure_latin_transcript, normalize_transcript

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def _extension_for_mime(mime_type: str) -> str:
    mime = (mime_type or "").lower().split(";")[0].strip()
    return {
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }.get(mime, "ogg")


def _clean_mime(mime_type: str) -> str:
    """Strip codec params — WhatsApp sends 'audio/ogg; codecs=opus'."""
    mime = (mime_type or "audio/ogg").lower().split(";")[0].strip()
    return mime or "audio/ogg"


async def transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured")
    if not audio_bytes:
        raise ValueError("Empty audio payload")

    clean_mime = _clean_mime(mime_type)
    ext = _extension_for_mime(clean_mime)
    filename = f"voice.{ext}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            GROQ_TRANSCRIPTIONS_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            data={
                "model": settings.groq_whisper_model,
                "response_format": "text",
                "prompt": WHISPER_ORDER_PROMPT,
                "temperature": "0",
            },
            files={"file": (filename, audio_bytes, clean_mime)},
        )
        response.raise_for_status()
        text = normalize_transcript(response.text.strip())
        text = await ensure_latin_transcript(text)
        logger.info("Whisper transcript (%d chars): %s", len(text), text[:160])
        return text
