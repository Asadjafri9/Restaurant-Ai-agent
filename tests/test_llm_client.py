"""Tests for the LLM client: Gemini 2.5 Flash (preferred) with Groq fallback.

The dispatcher respects settings.ai_provider:
- "auto"  -> Gemini if GEMINI_API_KEY is set, else Groq
- "gemini" -> Gemini
- "groq"   -> Groq

generate_reply calls the active provider; on rate limit falls back to
the other when its key is configured.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_client import (
    LlmRateLimitError,
    _active_provider,
    _build_gemini_contents,
    _is_rate_limit,
    call_gemini,
    generate_reply,
    provider_label,
)


# -------- provider selection --------


def test_auto_provider_prefers_gemini(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "auto")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "set")
    assert _active_provider() == "gemini"


def test_auto_provider_falls_back_to_groq_when_gemini_missing(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "auto")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "set")
    assert _active_provider() == "groq"


def test_auto_provider_errors_when_no_keys(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "auto")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "")
    with pytest.raises(ValueError, match="No LLM API key"):
        _active_provider()


def test_explicit_gemini_provider(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "gemini")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    assert _active_provider() == "gemini"


def test_explicit_gemini_provider_errors_when_key_missing(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "gemini")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        _active_provider()


def test_explicit_groq_provider(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "groq")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "set")
    assert _active_provider() == "groq"


def test_provider_label_no_keys(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "auto")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "")
    assert provider_label() == "none"


# -------- rate limit detection --------


def test_is_rate_limit_429():
    assert _is_rate_limit(Exception("HTTP 429 Too Many Requests"))


def test_is_rate_limit_resource_exhausted():
    assert _is_rate_limit(Exception("RESOURCE_EXHAUSTED: quota exceeded"))


def test_is_rate_limit_quota_word():
    assert _is_rate_limit(Exception("quota exceeded for project"))


def test_is_rate_limit_other_error_returns_false():
    assert not _is_rate_limit(Exception("HTTP 500 Internal Server Error"))
    assert not _is_rate_limit(ValueError("network down"))


# -------- Gemini SDK content builder --------


def test_build_gemini_contents_basic():
    history = [
        {"role": "user", "parts": ["hi"]},
        {"role": "model", "parts": ["hello"]},
    ]
    contents = _build_gemini_contents(history, "how are you?")
    assert len(contents) == 3
    assert contents[0] == {"role": "user", "parts": [{"text": "hi"}]}
    assert contents[1] == {"role": "model", "parts": [{"text": "hello"}]}
    assert contents[2] == {"role": "user", "parts": [{"text": "how are you?"}]}


def test_build_gemini_contents_skips_empty():
    history = [
        {"role": "user", "parts": [""]},
        {"role": "model", "parts": []},
    ]
    contents = _build_gemini_contents(history, "next")
    # Only the final user message is appended
    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"] == [{"text": "next"}]


# -------- dispatch: generate_reply --------


@pytest.mark.asyncio
async def test_generate_reply_uses_gemini_when_provider_is_gemini(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "gemini")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    with patch(
        "app.services.llm_client.call_gemini",
        AsyncMock(return_value="hello from gemini"),
    ) as gem, patch(
        "app.services.llm_client.call_groq",
        AsyncMock(side_effect=AssertionError("groq should not be called")),
    ):
        out = await generate_reply("sys", [], "user msg")
    assert out == "hello from gemini"
    assert gem.await_count == 1


@pytest.mark.asyncio
async def test_generate_reply_falls_back_to_groq_when_gemini_rate_limited(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "gemini")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "set")
    with patch(
        "app.services.llm_client.call_gemini",
        AsyncMock(side_effect=LlmRateLimitError("429")),
    ), patch(
        "app.services.llm_client.call_groq",
        AsyncMock(return_value="hello from groq fallback"),
    ):
        out = await generate_reply("sys", [], "user msg")
    assert out == "hello from groq fallback"


@pytest.mark.asyncio
async def test_generate_reply_raises_when_gemini_rate_limited_and_no_groq(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "gemini")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "")
    with patch(
        "app.services.llm_client.call_gemini",
        AsyncMock(side_effect=LlmRateLimitError("429")),
    ):
        with pytest.raises(LlmRateLimitError):
            await generate_reply("sys", [], "user msg")


@pytest.mark.asyncio
async def test_generate_reply_uses_groq_when_only_groq_key(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "auto")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "set")
    with patch(
        "app.services.llm_client.call_gemini",
        AsyncMock(side_effect=AssertionError("gemini should not be called")),
    ) as gem, patch(
        "app.services.llm_client.call_groq",
        AsyncMock(return_value="groq reply"),
    ) as groq:
        out = await generate_reply("sys", [], "user msg")
    assert out == "groq reply"
    assert groq.await_count == 1
    assert gem.await_count == 0


@pytest.mark.asyncio
async def test_generate_reply_falls_back_to_gemini_when_groq_rate_limited(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.ai_provider", "auto")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    monkeypatch.setattr("app.services.llm_client.settings.groq_api_key", "set")
    with patch(
        "app.services.llm_client.call_groq",
        AsyncMock(side_effect=LlmRateLimitError("429")),
    ), patch(
        "app.services.llm_client.call_gemini",
        AsyncMock(return_value="gemini fallback reply"),
    ):
        out = await generate_reply("sys", [], "user msg")
    assert out == "gemini fallback reply"


# -------- call_gemini: retry on 429 --------


@pytest.mark.asyncio
async def test_call_gemini_retries_on_429(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    calls = {"n": 0}

    async def _flaky(_system, _history, _user_message):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "ok"

    # Patch asyncio.sleep so the test doesn't actually wait between retries
    with patch("app.services.llm_client.asyncio.sleep", AsyncMock()), patch(
        "app.services.llm_client._call_gemini_async", AsyncMock(side_effect=_flaky)
    ):
        out = await call_gemini("sys", [], "user")
    assert out == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_call_gemini_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    with patch("app.services.llm_client.asyncio.sleep", AsyncMock()), patch(
        "app.services.llm_client._call_gemini_async",
        AsyncMock(side_effect=RuntimeError("429 always")),
    ):
        with pytest.raises(LlmRateLimitError):
            await call_gemini("sys", [], "user")


@pytest.mark.asyncio
async def test_call_gemini_does_not_retry_on_non_rate_limit_error(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    calls = {"n": 0}

    async def _fail(_system, _history, _user_message):
        calls["n"] += 1
        raise ValueError("bad request")

    with patch("app.services.llm_client.asyncio.sleep", AsyncMock()), patch(
        "app.services.llm_client._call_gemini_async", AsyncMock(side_effect=_fail)
    ):
        with pytest.raises(ValueError):
            await call_gemini("sys", [], "user")
    assert calls["n"] == 1  # no retry


# -------- call_gemini: new SDK call shape --------


@pytest.mark.asyncio
async def test_call_gemini_uses_new_google_genai_sdk(monkeypatch):
    """Verify the new google.genai SDK is called with the right model, contents, and config."""
    monkeypatch.setattr("app.services.llm_client.settings.gemini_api_key", "set")
    monkeypatch.setattr("app.services.llm_client.settings.gemini_model", "gemini-2.5-flash")

    class _Resp:
        text = "  hello from gemini 2.5  "

    class _FakeAsyncModels:
        def __init__(self):
            self.calls = []

        async def generate_content(self, *, model, contents, config):
            self.calls.append({"model": model, "contents": contents, "config": config})
            return _Resp()

    fake_models = _FakeAsyncModels()
    fake_client = MagicMock()
    fake_client.aio.models = fake_models

    config_calls: list[dict] = []

    def _fake_config(*, system_instruction, temperature, max_output_tokens):
        config_calls.append(
            {
                "system_instruction": system_instruction,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            }
        )
        return "FAKE_CONFIG"


    fake_genai = MagicMock()
    fake_types = MagicMock()
    fake_types.GenerateContentConfig.side_effect = _fake_config
    fake_genai.Client.return_value = fake_client
    fake_genai.types = fake_types

    saved = {}
    saved["google"] = sys.modules.get("google")
    saved["google.genai"] = sys.modules.get("google.genai")
    sys.modules["google.genai"] = fake_genai
    fake_google = MagicMock()
    fake_google.genai = fake_genai
    sys.modules["google"] = fake_google
    try:
        out = await call_gemini(
            "system prompt here",
            [
                {"role": "user", "parts": ["hi"]},
                {"role": "model", "parts": ["hello"]},
            ],
            "what is on the menu?",
        )
    finally:
        sys.modules["google"] = saved["google"]
        sys.modules["google.genai"] = saved["google.genai"]

    assert out == "hello from gemini 2.5"
    assert len(fake_models.calls) == 1
    call = fake_models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    # Contents: history + final user message
    assert len(call["contents"]) == 3
    assert call["contents"][0]["role"] == "user"
    assert call["contents"][0]["parts"] == [{"text": "hi"}]
    assert call["contents"][2]["parts"] == [{"text": "what is on the menu?"}]
    # Config built with system_instruction
    assert config_calls == [
        {
            "system_instruction": "system prompt here",
            "temperature": 0.2,
            "max_output_tokens": 1024,
        }
    ]
    assert call["config"] == "FAKE_CONFIG"
