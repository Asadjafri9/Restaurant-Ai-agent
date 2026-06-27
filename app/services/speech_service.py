"""Speech-to-text via Gemini (preferred) with Groq Whisper as fallback.

Gemini 2.5 Flash accepts inline audio (Part.from_bytes) and can transcribe
multilingual content including Roman Urdu and Pakistani English code-switching,
which is what WhatsApp voice notes from KFC / Kababjees customers sound like.

Groq Whisper is kept as a fallback for when the Gemini key is missing.
"""

import logging

import httpx

from app.config.settings import settings
from app.services.voice_text import WHISPER_ORDER_PROMPT, ensure_latin_transcript, normalize_transcript

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Gemini caps inline audio at 20MB; WhatsApp voice notes are typically <1MB.
_GEMINI_INLINE_AUDIO_LIMIT = 20 * 1024 * 1024

_stt_provider_logged: str | None = None


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
    if not audio_bytes:
        raise ValueError("Empty audio payload")

    if settings.gemini_api_key:
        try:
            return await _transcribe_gemini(audio_bytes, mime_type)
        except Exception:
            logger.exception("Gemini STT failed; falling back to Groq if available")
            if settings.groq_api_key:
                return await _transcribe_groq(audio_bytes, mime_type)
            raise
    if settings.groq_api_key:
        return await _transcribe_groq(audio_bytes, mime_type)
    raise ValueError("Neither GEMINI_API_KEY nor GROQ_API_KEY is configured")


async def _transcribe_gemini(audio_bytes: bytes, mime_type: str) -> str:
    """Transcribe audio via Gemini 2.5 Flash (multimodal)."""
    global _stt_provider_logged
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured")
    if len(audio_bytes) > _GEMINI_INLINE_AUDIO_LIMIT:
        raise ValueError(
            f"Audio payload too large for inline STT ({len(audio_bytes)} bytes > "
            f"{_GEMINI_INLINE_AUDIO_LIMIT}); use a Files API upload instead."
        )

    clean_mime = _clean_mime(mime_type)
    # The new SDK uses camelCase; the legacy one uses snake_case. Normalize.
    gemini_mime = clean_mime.replace("_", "-")
    if not gemini_mime.startswith("audio/"):
        gemini_mime = "audio/ogg"

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=gemini_mime)
    prompt = (
        "Transcribe this WhatsApp voice note exactly as spoken. "
        "Output ONLY the transcript, no preamble, no timestamps, no labels. "
        + WHISPER_ORDER_PROMPT
    )

    response = await client.aio.models.generate_content(
        model=settings.gemini_stt_model,
        contents=[audio_part, prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1024,
        ),
    )

    raw = (response.text or "").strip()
    if not raw:
        raise ValueError("Gemini STT returned empty transcript")

    text = normalize_transcript(raw)
    text = await ensure_latin_transcript(text)
    if _stt_provider_logged != "gemini":
        logger.info("STT using Gemini model=%s", settings.gemini_stt_model)
        _stt_provider_logged = "gemini"
    logger.info("Gemini STT (%d chars): %s", len(text), text[:160])
    return text


async def _transcribe_groq(audio_bytes: bytes, mime_type: str) -> str:
    """Fallback: transcribe via Groq Whisper."""
    global _stt_provider_logged
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured")

    clean_mime = _clean_mime(mime_type)
    ext = _extension_for_mime(clean_mime)
    filename = f"voice.{ext}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            GROQ_TRANSCRIPTIONS_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            data={
                "model": "whisper-large-v3",
                "response_format": "text",
                "prompt": WHISPER_ORDER_PROMPT,
                "temperature": "0",
            },
            files={"file": (filename, audio_bytes, clean_mime)},
        )
        response.raise_for_status()
        text = normalize_transcript(response.text.strip())
        text = await ensure_latin_transcript(text)
        if _stt_provider_logged != "groq":
            logger.info("STT using Groq Whisper")
            _stt_provider_logged = "groq"
        logger.info("Whisper transcript (%d chars): %s", len(text), text[:160])
        return text
