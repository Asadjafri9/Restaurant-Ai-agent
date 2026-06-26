from unittest.mock import AsyncMock, patch

import pytest

from app.routes.webhook import _send_reply


@pytest.mark.asyncio
async def test_send_reply_uses_voice_for_audio_when_tts_configured():
    with patch("app.routes.webhook.voice_reply_available", return_value=True):
        with patch("app.routes.webhook.synthesize_speech", AsyncMock(return_value=b"mp3")):
            with patch("app.routes.webhook.upload_media", AsyncMock(return_value="media_1")):
                with patch("app.routes.webhook.send_audio_message", AsyncMock(return_value=True)):
                    with patch(
                        "app.routes.webhook.send_text_message",
                        AsyncMock(return_value=True),
                    ) as mock_text:
                        sent = await _send_reply(
                            "923001234567",
                            "Zabardast! Menu bhej diya.",
                            reply_with_voice=True,
                        )

    assert sent is True
    mock_text.assert_called_once_with("923001234567", "Zabardast! Menu bhej diya.")


@pytest.mark.asyncio
async def test_send_reply_falls_back_to_text_when_tts_fails():
    with patch("app.routes.webhook.voice_reply_available", return_value=True):
        with patch(
            "app.routes.webhook.synthesize_speech",
            AsyncMock(side_effect=RuntimeError("tts down")),
        ):
            with patch("app.routes.webhook.send_text_message", AsyncMock(return_value=True)) as mock_text:
                sent = await _send_reply(
                    "923001234567",
                    "Fallback text",
                    reply_with_voice=True,
                )

    assert sent is True
    mock_text.assert_called_once_with("923001234567", "Fallback text")


@pytest.mark.asyncio
async def test_send_reply_text_only_for_text_messages():
    with patch("app.routes.webhook.send_text_message", AsyncMock(return_value=True)) as mock_text:
        with patch("app.routes.webhook.synthesize_speech", AsyncMock()) as mock_tts:
            sent = await _send_reply(
                "923001234567",
                "Text reply",
                reply_with_voice=False,
            )

    assert sent is True
    mock_tts.assert_not_called()
    mock_text.assert_called_once_with("923001234567", "Text reply")
