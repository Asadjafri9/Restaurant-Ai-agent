"""Tests for the speech-to-text service: Gemini is the primary provider,
Groq is the fallback when Gemini is missing or fails."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.speech_service import _transcribe_gemini, transcribe


def test_clean_mime_strips_codec_params():
    from app.services.speech_service import _clean_mime

    assert _clean_mime("audio/ogg; codecs=opus") == "audio/ogg"
    assert _clean_mime("audio/ogg") == "audio/ogg"
    assert _clean_mime("") == "audio/ogg"
    assert _clean_mime("AUDIO/OGG; codecs=OPUS") == "audio/ogg"


def test_extension_for_mime():
    from app.services.speech_service import _extension_for_mime

    assert _extension_for_mime("audio/ogg") == "ogg"
    assert _extension_for_mime("audio/ogg; codecs=opus") == "ogg"
    assert _extension_for_mime("audio/mpeg") == "mp3"
    assert _extension_for_mime("audio/mp4") == "m4a"
    assert _extension_for_mime("audio/wav") == "wav"
    assert _extension_for_mime("audio/webm") == "webm"
    assert _extension_for_mime("unknown") == "ogg"


@pytest.mark.asyncio
async def test_transcribe_uses_gemini_when_key_set():
    """When GEMINI_API_KEY is set, Gemini is the primary path (Groq not called)."""
    audio = b"\x00\x01\x02"  # 3 bytes of fake audio

    async def fake_gemini(_audio, _mime):
        return "hello from gemini"

    with (
        patch("app.services.speech_service._transcribe_gemini", AsyncMock(side_effect=fake_gemini)),
        patch("app.services.speech_service._transcribe_groq", AsyncMock(side_effect=AssertionError("groq should not be called"))),
    ):
        result = await transcribe(audio, "audio/ogg")
    assert result == "hello from gemini"


@pytest.mark.asyncio
async def test_transcribe_falls_back_to_groq_when_gemini_fails_and_both_set():
    audio = b"\x00"

    async def fake_gemini(_audio, _mime):
        raise RuntimeError("gemini 503")

    async def fake_groq(_audio, _mime):
        return "hello from groq fallback"

    with (
        patch("app.services.speech_service._transcribe_gemini", AsyncMock(side_effect=fake_gemini)),
        patch("app.services.speech_service._transcribe_groq", AsyncMock(side_effect=fake_groq)),
    ):
        result = await transcribe(audio, "audio/ogg")
    assert result == "hello from groq fallback"


@pytest.mark.asyncio
async def test_transcribe_uses_groq_when_only_groq_key_set(monkeypatch):
    audio = b"\x00"
    monkeypatch.setattr("app.services.speech_service.settings.gemini_api_key", "")

    async def fake_groq(_audio, _mime):
        return "groq only"

    with patch("app.services.speech_service._transcribe_groq", AsyncMock(side_effect=fake_groq)):
        result = await transcribe(audio, "audio/ogg")
    assert result == "groq only"


@pytest.mark.asyncio
async def test_transcribe_raises_when_no_keys(monkeypatch):
    monkeypatch.setattr("app.services.speech_service.settings.gemini_api_key", "")
    monkeypatch.setattr("app.services.speech_service.settings.groq_api_key", "")
    with pytest.raises(ValueError, match="API_KEY"):
        await transcribe(b"\x00", "audio/ogg")


@pytest.mark.asyncio
async def test_transcribe_raises_on_empty_audio(monkeypatch):
    with pytest.raises(ValueError, match="Empty audio"):
        await transcribe(b"", "audio/ogg")


@pytest.mark.asyncio
async def test_transcribe_gemini_rejects_oversize():
    """Inline audio over 20MB raises; the dispatcher would then fall back to Groq."""
    big = b"\x00" * (20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        await _transcribe_gemini(big, "audio/ogg")


@pytest.mark.asyncio
async def test_transcribe_gemini_calls_new_sdk_with_audio_part():
    """Verify the new google.genai SDK is called with Part.from_bytes and the
    correct model. Mocks the client so no real network call is made."""
    from app.services import speech_service

    config_calls: list[dict] = []
    part_calls: list[dict] = []

    class _FakeAsyncModels:
        def __init__(self):
            self.calls = []

        async def generate_content(self, *, model, contents, config):
            self.calls.append({"model": model, "contents": contents, "config": config})

            class _Resp:
                text = "transcribed text"

            return _Resp()

    fake_models = _FakeAsyncModels()
    fake_client = MagicMock()
    fake_client.aio.models = fake_models

    def _fake_part_from_bytes(*, data, mime_type):
        part_calls.append({"data": data, "mime_type": mime_type})
        return "FAKE_AUDIO_PART"

    def _fake_config(*, temperature, max_output_tokens):
        config_calls.append({"temperature": temperature, "max_output_tokens": max_output_tokens})
        return "FAKE_CONFIG"

    import sys

    fake_genai = MagicMock()
    fake_types = MagicMock()
    fake_types.Part.from_bytes.side_effect = _fake_part_from_bytes
    fake_types.GenerateContentConfig.side_effect = _fake_config
    fake_genai.Client.return_value = fake_client
    fake_genai.types = fake_types
    sys.modules["google.genai"] = fake_genai
    sys.modules["google"] = MagicMock()
    sys.modules["google"].genai = fake_genai
    try:
        result = await _transcribe_gemini(b"abc", "audio/ogg; codecs=opus")
    finally:
        sys.modules.pop("google.genai", None)

    assert result == "transcribed text"
    assert len(fake_models.calls) == 1
    call = fake_models.calls[0]
    assert call["model"] == speech_service.settings.gemini_stt_model
    assert call["contents"][0] == "FAKE_AUDIO_PART"
    assert isinstance(call["contents"][1], str)
    assert "KFC" in call["contents"][1]
    assert call["config"] == "FAKE_CONFIG"
    # And the constructor was called with the right params
    assert config_calls == [{"temperature": 0.0, "max_output_tokens": 1024}]
    # And the audio part was built with the cleaned mime type
    assert part_calls == [{"data": b"abc", "mime_type": "audio/ogg"}]
