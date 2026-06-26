from unittest.mock import AsyncMock, patch

import pytest

from app.services.tts_service import prepare_text_for_speech, synthesize_speech


def test_prepare_text_for_speech_strips_markdown():
    text = "**Hello** _world_\n\nMenu:\n1. Biryani"
    assert prepare_text_for_speech(text) == "Hello world\n\nMenu:\n1. Biryani"


@pytest.mark.asyncio
async def test_synthesize_speech_returns_mp3_bytes():
    fake_audio = b"ID3fake-mp3"

    with patch("app.services.tts_service.settings") as mock_settings:
        mock_settings.elevenlabs_api_key = "test-key"
        mock_settings.elevenlabs_voice_id = "voice123"
        mock_settings.elevenlabs_model_id = "eleven_multilingual_v2"
        mock_settings.elevenlabs_stability = 0.5
        mock_settings.elevenlabs_similarity_boost = 0.75

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_response = AsyncMock()
            mock_response.content = fake_audio
            mock_response.raise_for_status = lambda: None

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await synthesize_speech("Aapka order confirm ho gaya.")

    assert result == fake_audio
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["headers"]["xi-api-key"] == "test-key"
    assert call_kwargs["json"]["text"] == "Aapka order confirm ho gaya."
