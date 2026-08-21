from __future__ import annotations

import threading

from app.core.config import settings

_LOCK = threading.Lock()
_INDEX = 0


def groq_api_keys() -> list[str]:
    if settings.TESTING:
        text = (settings.GROQ_API_KEY or "").strip()
        return [text] if text else []
    keys: list[str] = []
    seen: set[str] = set()
    for value in (
        settings.GROQ_API_KEY,
        settings.GROQ_API_KEY_BACKUP,
        settings.GROQ_API_KEY_BACKUP_2,
    ):
        text = (value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        keys.append(text)
    return keys


def groq_api_key() -> str | None:
    keys = groq_api_keys()
    if not keys:
        return None
    with _LOCK:
        index = min(_INDEX, len(keys) - 1)
        return keys[index]


def advance_key_on_quota() -> bool:
    """Switch to the next Groq key after TPD. Returns True if another key is available."""
    global _INDEX
    keys = groq_api_keys()
    if len(keys) < 2:
        return False
    with _LOCK:
        if _INDEX + 1 >= len(keys):
            return False
        _INDEX += 1
        return True


def reset_groq_key_index() -> None:
    global _INDEX
    with _LOCK:
        _INDEX = 0
