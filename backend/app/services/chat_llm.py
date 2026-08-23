from __future__ import annotations

import threading

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq

from app.core.config import settings
from app.services.groq_keys import advance_key_on_quota, groq_api_key

_LOCK = threading.Lock()
_FORCE_OPENROUTER = False


def reset_llm_provider() -> None:
    global _FORCE_OPENROUTER
    with _LOCK:
        _FORCE_OPENROUTER = False


def use_openrouter() -> bool:
    configured = (settings.LLM_PROVIDER or "").strip().lower()
    if configured == "openrouter":
        return True
    if configured == "groq":
        return False
    with _LOCK:
        return _FORCE_OPENROUTER


def llm_configured() -> bool:
    return bool(groq_api_key() or settings.OPENROUTER_API_KEY)


def advance_provider_on_quota() -> bool:
    """After Groq keys are exhausted, fall over to OpenRouter if configured."""
    global _FORCE_OPENROUTER
    if advance_key_on_quota():
        return True
    if use_openrouter():
        return False
    if not settings.OPENROUTER_API_KEY:
        return False
    with _LOCK:
        if _FORCE_OPENROUTER:
            return False
        _FORCE_OPENROUTER = True
        return True


def build_chat_llm(*, temperature: float = 0) -> BaseChatModel:
    global _FORCE_OPENROUTER
    if use_openrouter():
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured. Add it to backend/.env"
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=temperature,
            api_key=api_key,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/unihacks",
                "X-Title": "UniHack Product Intelligence",
            },
        )

    api_key = groq_api_key()
    if api_key:
        return ChatGroq(
            model=settings.LLM_MODEL,
            temperature=temperature,
            api_key=api_key,
        )

    if settings.OPENROUTER_API_KEY:
        with _LOCK:
            _FORCE_OPENROUTER = True
        return build_chat_llm(temperature=temperature)

    raise RuntimeError("GROQ_API_KEY is not configured. Add it to backend/.env")
