from __future__ import annotations

import re


def compact_alnum(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def preserve_display_text(
    value: str | None,
    known_labels: list[str] | None = None,
) -> str | None:
    """Keep human-readable spacing. Restore labels like SandingBelt → Sanding Belt."""
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").replace("_", " ").replace("-", " ")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None

    compact = compact_alnum(text)
    for label in known_labels or []:
        if compact_alnum(label) == compact:
            return label
    return text
