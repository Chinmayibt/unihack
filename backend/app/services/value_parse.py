from __future__ import annotations

import re

from app.services.standards import canonical_uom, uom_aliases_longest

NUMBER = r"(?:\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:\.\d+)?)"
SIZE_RE = re.compile(
    rf"(?P<width>{NUMBER})\s*(?P<width_uom>[\"”″]|in\.?|inch(?:es)?)\s*[x×]\s*"
    rf"(?P<length>{NUMBER})\s*(?P<length_uom>[\"”″]|in\.?|inch(?:es)?)?",
    re.I,
)
QTY_RE = re.compile(
    rf"(?P<qty>\d+)\s*(?P<uom>pc|pcs|piece|pieces|pk|pack|packs|ea|each)\b",
    re.I,
)
GRIT_RANGE_RE = re.compile(
    r"\b(?P<grit>\d+(?:\s*/\s*\d+){1,4})\s*-?\s*grit\b",
    re.I,
)
GRIT_SINGLE_RE = re.compile(r"\b(?P<grit>\d+)\s*-?\s*grit\b", re.I)


def _clean_number(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    mixed = re.match(r"^(\d+)\s+(\d+)\s*/\s*(\d+)$", text)
    if mixed:
        return f"{mixed.group(1)}-{mixed.group(2)}/{mixed.group(3)}"
    return text.replace(" ", "")


def split_value_and_uom(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None

    if text[-1] in {'"', "”", "″"}:
        prefix = text[:-1].strip()
        return (prefix or None, '"')

    lowered = text.lower()
    for alias in uom_aliases_longest():
        if alias in {'"', "'", "”", "″"}:
            continue
        if not lowered.endswith(alias):
            continue
        prefix = text[: len(text) - len(alias)].rstrip(" .-")
        suffix = text[len(text) - len(alias) :].strip()
        if not prefix:
            return None, suffix
        boundary = text[len(prefix) : len(text) - len(alias) + 1]
        if prefix[-1].isdigit() or boundary[:1] in {" ", ".", "-"}:
            return prefix, suffix
    return text, None


def parse_input_candidates(description: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not description:
        return found
    size = SIZE_RE.search(description)
    if size:
        found["Width"] = {
            "value": _clean_number(size.group("width")),
            "uom": size.group("width_uom"),
            "evidence_text": size.group(0),
        }
        length_uom = size.group("length_uom") or size.group("width_uom")
        found["Length"] = {
            "value": _clean_number(size.group("length")),
            "uom": length_uom,
            "evidence_text": size.group(0),
        }
    qty = QTY_RE.search(description)
    if qty:
        found["Quantity"] = {
            "value": qty.group(0).replace(" ", ""),
            "uom": None,
            "evidence_text": qty.group(0),
        }
    grit = GRIT_RANGE_RE.search(description) or GRIT_SINGLE_RE.search(description)
    if grit:
        found["Grit"] = {
            "value": re.sub(r"\s+", "", grit.group("grit")),
            "uom": None,
            "evidence_text": grit.group(0),
        }
    return found


def parse_secondary_grit(text: str) -> dict | None:
    if not text:
        return None
    match = GRIT_RANGE_RE.search(text) or GRIT_SINGLE_RE.search(text)
    if not match:
        return None
    return {
        "value": re.sub(r"\s+", "", match.group("grit")),
        "uom": None,
        "evidence_text": match.group(0),
    }


def parsed_canonical_uom(raw_uom: str | None) -> str | None:
    return canonical_uom(raw_uom)
