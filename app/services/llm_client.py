"""LLM client — Gemini 2.5 Flash (preferred) with Groq as fallback.

The primary LLM is now Google's Gemini 2.5 Flash via the new google.genai
SDK (client.aio.models.generate_content). Groq (Llama 3.3 70B) remains as
a fallback for when Gemini is rate-limited or otherwise unavailable.

The dispatcher respects settings.ai_provider:
- "auto"  -> Gemini if GEMINI_API_KEY is set, else Groq
- "gemini" -> Gemini (must have GEMINI_API_KEY)
- "groq"   -> Groq (must have GROQ_API_KEY)
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_RETRY_DELAYS = (0.0, 1.0, 2.5)
_LLM_MAX_TOKENS = 1024
_LLM_TEMPERATURE = 0.2


class LlmRateLimitError(Exception):
    """The active LLM provider returned 429 after retries."""


def _active_provider() -> str:
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        return "gemini"
    if settings.ai_provider == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured")
        return "groq"
    # auto: prefer Gemini
    if settings.gemini_api_key:
        return "gemini"
    if settings.groq_api_key:
        return "groq"
    raise ValueError(
        "No LLM API key configured (set GEMINI_API_KEY or GROQ_API_KEY)"
    )


def _is_rate_limit(exc: Exception) -> bool:
    err = str(exc)
    return "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower()


# ----- Gemini (new google.genai SDK) -----


def _build_gemini_contents(
    history: list[dict], user_message: str
) -> list[dict[str, Any]]:
    """Convert session history into the new SDK's `contents` format.

    Each entry is `{"role": "user"|"model", "parts": [{"text": "..."}]}`.
    """
    contents: list[dict[str, Any]] = []
    for h in history or []:
        role = "user" if h.get("role") == "user" else "model"
        parts = h.get("parts") or []
        text = parts[0] if parts else ""
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})
    return contents


async def _call_gemini_async(
    system: str, history: list[dict], user_message: str
) -> str:
    """Single Gemini 2.5 Flash call (async, no retry)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=_build_gemini_contents(history, user_message),
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=_LLM_TEMPERATURE,
            max_output_tokens=_LLM_MAX_TOKENS,
        ),
    )
    return (response.text or "").strip()


async def call_gemini(
    system: str, history: list[dict], user_message: str
) -> str:
    """Public Gemini entry with retry on rate limits (429 / quota)."""
    last_error: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await _call_gemini_async(system, history, user_message)
        except Exception as exc:
            if _is_rate_limit(exc):
                logger.warning(
                    "Gemini rate limit (attempt %d/%d)", attempt + 1, len(_RETRY_DELAYS)
                )
                last_error = LlmRateLimitError(str(exc)[:200])
                continue
            raise
    raise last_error or LlmRateLimitError("Gemini rate limit exceeded")


# ----- Groq (fallback) -----


def _history_to_messages(
    system: str, history: list[dict], user_message: str
) -> list[dict]:
    messages = [{"role": "system", "content": system}]
    for h in history:
        role = "user" if h.get("role") == "user" else "assistant"
        parts = h.get("parts") or []
        text = parts[0] if parts else ""
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_message})
    return messages


async def call_groq(
    system: str, history: list[dict], user_message: str
) -> str:
    """Groq (OpenAI-compatible) chat completion with retry on 429."""
    messages = _history_to_messages(system, history, user_message)
    last_error: Exception | None = None

    for attempt, delay in enumerate(_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    GROQ_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {settings.groq_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.groq_model,
                        "messages": messages,
                        "max_tokens": _LLM_MAX_TOKENS,
                        "temperature": _LLM_TEMPERATURE,
                    },
                )
                if response.status_code == 429:
                    logger.warning(
                        "Groq rate limit (attempt %d/%d)",
                        attempt + 1,
                        len(_RETRY_DELAYS),
                    )
                    last_error = LlmRateLimitError(response.text[:200])
                    continue
                response.raise_for_status()
                data = response.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
        except LlmRateLimitError as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning(
                    "Groq rate limit (attempt %d/%d)",
                    attempt + 1,
                    len(_RETRY_DELAYS),
                )
                last_error = LlmRateLimitError(str(exc))
                continue
            raise

    raise last_error or LlmRateLimitError("Groq rate limit exceeded")


# ----- Dispatcher -----


async def generate_reply(
    system: str, history: list[dict], user_message: str
) -> str:
    """Call the active LLM provider; on rate limit fall back to the other."""
    provider = _active_provider()
    if provider == "gemini":
        try:
            return await call_gemini(system, history, user_message)
        except LlmRateLimitError:
            if settings.groq_api_key:
                logger.warning("Gemini rate limited — falling back to Groq")
                return await call_groq(system, history, user_message)
            raise
    # groq path — fall back to Gemini if Groq is rate-limited and Gemini is available
    try:
        return await call_groq(system, history, user_message)
    except LlmRateLimitError:
        if settings.gemini_api_key:
            logger.warning("Groq rate limited — falling back to Gemini")
            return await call_gemini(system, history, user_message)
        raise


def provider_label() -> str:
    try:
        return _active_provider()
    except ValueError:
        return "none"
