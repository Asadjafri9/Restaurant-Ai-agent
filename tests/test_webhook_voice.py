from unittest.mock import AsyncMock, patch

import pytest

from app.routes.webhook import extract_message


def _audio_payload(msg_type: str = "audio", audio_key: str = "audio") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.voice123",
                                    "type": msg_type,
                                    audio_key: {
                                        "id": "media_abc",
                                        "mime_type": "audio/ogg; codecs=opus",
                                        "voice": True,
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_extract_audio_message():
    data = extract_message(_audio_payload())
    assert data is not None
    assert data["input_type"] == "audio"
    assert data["media_id"] == "media_abc"
    assert data["phone_number"] == "923001234567"
    assert "codecs=opus" in data["mime_type"]


def test_extract_legacy_voice_type():
    payload = _audio_payload(msg_type="voice", audio_key="voice")
    data = extract_message(payload)
    assert data is not None
    assert data["input_type"] == "audio"
    assert data["media_id"] == "media_abc"


def test_extract_text_still_works():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.text1",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    data = extract_message(payload)
    assert data == {
        "phone_number": "923001234567",
        "message": "hello",
        "message_id": "wamid.text1",
        "input_type": "text",
    }


def test_unsupported_media_type():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.img1",
                                    "type": "image",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    data = extract_message(payload)
    assert data is not None
    assert data["input_type"] == "unsupported"


@pytest.mark.asyncio
async def test_handle_incoming_audio_transcribes_and_replies():
    from app.routes.webhook import _handle_incoming_message
    from app.services.session_service import CustomerSession

    message_data = {
        "phone_number": "923001234567",
        "message_id": "wamid.voice.test",
        "media_id": "fake_media",
        "mime_type": "audio/ogg; codecs=opus",
        "input_type": "audio",
    }

    with patch("app.routes.webhook.verify_whatsapp_token_cached", AsyncMock(return_value=(True, None))):
        with patch(
            "app.routes.webhook.get_session_async",
            AsyncMock(return_value=CustomerSession(phone="923001234567")),
        ):
            with patch("app.routes.webhook.get_media_url", AsyncMock(return_value="https://example.com/a.ogg")):
                with patch("app.routes.webhook.download_media", AsyncMock(return_value=b"audio")):
                    with patch("app.routes.webhook.transcribe", AsyncMock(return_value="kfc se order")):
                        with patch(
                            "app.services.order_agent.process_order_message_async",
                            AsyncMock(return_value="KFC menu here"),
                        ):
                            with patch(
                                "app.routes.webhook.send_text_message",
                                AsyncMock(return_value=True),
                            ) as mock_text:
                                with patch("app.routes.webhook.voice_reply_available", return_value=False):
                                    await _handle_incoming_message(message_data)

    assert mock_text.call_count >= 2
    assert mock_text.call_args_list[-1].args[1] == "KFC menu here"
