from __future__ import annotations

import re
import unicodedata

LEGAL_SUFFIXES = (
    (re.compile(r"\bincorporated\b", re.I), "inc"),
    (re.compile(r"\bcorporation\b", re.I), "corp"),
    (re.compile(r"\blimited\b", re.I), "ltd"),
    (re.compile(r"\bcompany\b", re.I), "co"),
    (re.compile(r"\bl\.l\.c\b", re.I), "llc"),
)

MANUFACTURER_PLACEHOLDERS = {
    "-",
    "--",
    "n/a",
    "na",
    "none",
    "unknown",
    "null",
}


def normalize_entity_name(value: str | None) -> str:
    """Lowercase, strip codes/punctuation, collapse spaces, normalize legal suffixes."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = re.sub(r"\s*\([^)]*\)", " ", text)
    text = text.replace("&", " and ")
    text = text.replace("®", " ").replace("™", " ")
    text = text.lower()
    for pattern, replacement in LEGAL_SUFFIXES:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_missing_entity(value: str | None) -> bool:
    if value is None or not str(value).strip():
        return True
    return str(value).strip().lower() in MANUFACTURER_PLACEHOLDERS
