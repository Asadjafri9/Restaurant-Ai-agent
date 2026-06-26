"""Text-to-speech via ElevenLabs for WhatsApp voice replies."""

import logging
import re

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# Max chars per voice note — keeps latency and API cost reasonable.
MAX_TTS_CHARS = 1500


def prepare_text_for_speech(text: str) -> str:
    """Strip formatting that does not read well aloud."""
    t = (text or "").strip()
    t = re.sub(r"\*+", "", t)
    t = re.sub(r"[_~`]", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    if len(t) > MAX_TTS_CHARS:
        t = t[: MAX_TTS_CHARS - 3].rstrip() + "..."
    return t


def voice_reply_available() -> bool:
    return bool(settings.elevenlabs_api_key.strip())


async def synthesize_speech(text: str) -> bytes:
    """Return MP3 audio bytes for the given reply text."""
    api_key = settings.elevenlabs_api_key.strip()
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is not configured")

    speech_text = prepare_text_for_speech(text)
    if not speech_text:
        raise ValueError("Empty text for speech synthesis")

    voice_id = settings.elevenlabs_voice_id.strip()
    url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": speech_text,
                "model_id": settings.elevenlabs_model_id,
                "voice_settings": {
                    "stability": settings.elevenlabs_stability,
                    "similarity_boost": settings.elevenlabs_similarity_boost,
                },
            },
        )
        response.raise_for_status()
        audio = response.content
        if not audio:
            raise ValueError("ElevenLabs returned empty audio")
        logger.info(
            "ElevenLabs TTS: %d chars -> %d bytes",
            len(speech_text),
            len(audio),
        )
        return audio
