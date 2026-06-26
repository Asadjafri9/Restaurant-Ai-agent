"""LLM client — Groq (preferred) with retry, Gemini fallback on rate limits."""

import asyncio
import logging

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

_genai_configured = False
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_RETRY_DELAYS = (0.0, 1.0, 2.5)


class LlmRateLimitError(Exception):
    """Groq (or primary provider) returned 429 after retries."""


def _active_provider() -> str:
    if settings.ai_provider == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured")
        return "groq"
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        return "gemini"
    if settings.groq_api_key:
        return "groq"
    if settings.gemini_api_key:
        return "gemini"
    raise ValueError("No LLM API key configured (set GROQ_API_KEY or GEMINI_API_KEY)")


def _history_to_messages(system: str, history: list[dict], user_message: str) -> list[dict]:
    messages = [{"role": "system", "content": system}]
    for h in history:
        role = "user" if h.get("role") == "user" else "assistant"
        parts = h.get("parts", [])
        text = parts[0] if parts else ""
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_message})
    return messages


async def call_groq(system: str, history: list[dict], user_message: str) -> str:
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
                        "max_tokens": 400,
                        "temperature": 0.2,
                    },
                )
                if response.status_code == 429:
                    logger.warning("Groq rate limit (attempt %d/%d)", attempt + 1, len(_RETRY_DELAYS))
                    last_error = LlmRateLimitError(response.text[:200])
                    continue
                response.raise_for_status()
                data = response.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
        except LlmRateLimitError as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("Groq rate limit (attempt %d/%d)", attempt + 1, len(_RETRY_DELAYS))
                last_error = LlmRateLimitError(str(exc))
                continue
            raise

    raise last_error or LlmRateLimitError("Groq rate limit exceeded")


def _call_gemini_sync(system: str, history: list[dict], user_message: str) -> str:
    import google.generativeai as genai

    global _genai_configured
    if not _genai_configured:
        genai.configure(api_key=settings.gemini_api_key)
        _genai_configured = True
    generation_config = genai.GenerationConfig(max_output_tokens=400, temperature=0.2)
    model = genai.GenerativeModel(
        settings.gemini_model,
        system_instruction=system,
        generation_config=generation_config,
    )
    gemini_history = []
    for h in history:
        role = "user" if h.get("role") == "user" else "model"
        parts = h.get("parts", [])
        text = parts[0] if parts else ""
        if text:
            gemini_history.append({"role": role, "parts": [text]})
    chat = model.start_chat(history=gemini_history)
    response = chat.send_message(user_message)
    return (response.text or "").strip()


async def generate_reply(system: str, history: list[dict], user_message: str) -> str:
    provider = _active_provider()
    if provider == "groq":
        try:
            return await call_groq(system, history, user_message)
        except LlmRateLimitError:
            if settings.gemini_api_key:
                logger.warning("Groq rate limited — falling back to Gemini")
                return await asyncio.to_thread(_call_gemini_sync, system, history, user_message)
            raise
    return await asyncio.to_thread(_call_gemini_sync, system, history, user_message)


def provider_label() -> str:
    try:
        return _active_provider()
    except ValueError:
        return "none"
