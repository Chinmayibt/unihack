from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.standards import (
    allowed_lov_values,
    approved_lov_alias_map,
    canonical_lov_key,
    canonical_uom,
    fraction_table,
)
from app.services.value_parse import split_value_and_uom


@dataclass
class ParsedValue:
    raw_value: str | None
    raw_uom: str | None
    normalized_value: str | None
    normalized_uom: str | None
    methods: list[str]


def _as_float(value: str) -> float | None:
    text = value.strip().replace(" ", "")
    mixed = re.match(r"^(\d+)-(\d+)/(\d+)$", text)
    if mixed:
        whole, num, den = (int(mixed.group(1)), int(mixed.group(2)), int(mixed.group(3)))
        if den == 0:
            return None
        return whole + (num / den)
    simple = re.match(r"^(\d+)/(\d+)$", text)
    if simple:
        num, den = int(simple.group(1)), int(simple.group(2))
        if den == 0:
            return None
        return num / den
    try:
        return float(text)
    except ValueError:
        return None


def to_approved_fraction(value: str) -> tuple[str, str | None]:
    """Return (canonical_fraction_or_original, method_or_none)."""
    text = value.strip()
    already = re.match(r"^(\d+)-(\d+)/(\d+)$", text.replace(" ", ""))
    if already:
        return f"{already.group(1)}-{already.group(2)}/{already.group(3)}", "FRACTION"
    simple = re.match(r"^(\d+)/(\d+)$", text.replace(" ", ""))
    if simple:
        return f"{simple.group(1)}/{simple.group(2)}", "FRACTION"

    number = _as_float(text)
    if number is None:
        return text, None
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number))), None

    tolerance, rows = fraction_table()
    whole = int(number)
    frac_part = abs(number) - abs(whole)
    for decimal, fraction in rows:
        if abs(frac_part - decimal) <= tolerance:
            if whole == 0:
                return fraction, "FRACTION"
            return f"{whole}-{fraction}", "FRACTION"
    return text, None


def resolve_lov(
    label: str, value: str | None, classpath: str | None = None
) -> tuple[str | None, str | None]:
    """Deterministic LOV: exact → case/whitespace → approved alias. No LLM, no substring.

    Returns (canonical, 'LOV') on match. If this label has no LOV, returns (value, None).
    If an LOV exists and nothing matches, returns (None, None).
    """
    if value is None or not str(value).strip():
        return None, None
    raw = str(value).strip()
    allowed = allowed_lov_values(label, classpath)
    if allowed is None:
        return raw, None
    if raw in allowed:
        return raw, "LOV"
    key = canonical_lov_key(raw)
    if not key:
        return None, None
    for item in allowed:
        if canonical_lov_key(item) == key:
            return item, "LOV"
    mapped = approved_lov_alias_map(label, classpath).get(key)
    if mapped:
        return mapped, "LOV"
    return None, None


def map_lov(label: str, value: str, classpath: str | None = None) -> tuple[str, str | None]:
    resolved, method = resolve_lov(label, value, classpath)
    if method == "LOV" and resolved:
        return resolved, "LOV"
    return value, None


def normalize_raw(value: str | None, uom: str | None, label: str, classpath: str | None = None) -> ParsedValue:
    raw_value = value.strip() if value and str(value).strip() else None
    raw_uom = uom.strip() if uom and str(uom).strip() else None
    methods: list[str] = []
    if raw_value is None:
        return ParsedValue(None, raw_uom, None, canonical_uom(raw_uom), methods)

    split_value, split_uom = split_value_and_uom(raw_value)
    working = split_value or raw_value
    working_uom = raw_uom or split_uom
    if (split_value and split_value != raw_value) or (split_uom and not raw_uom):
        methods.append("VALUE_UOM_SPLIT")

    fraction_value, fraction_method = to_approved_fraction(working)
    if fraction_method:
        methods.append(fraction_method)
        working = fraction_value

    lov_value, lov_method = map_lov(label, working, classpath)
    if lov_method:
        methods.append(lov_method)
        working = lov_value
    elif working != working.strip() or re.search(r"\s{2,}", working):
        working = re.sub(r"\s+", " ", working).strip()
        methods.append("STRING")

    normalized_uom = canonical_uom(working_uom)
    if normalized_uom and working_uom and canonical_uom(working_uom) != working_uom:
        methods.append("UOM_STANDARD")
    elif normalized_uom and split_uom and canonical_uom(split_uom) == normalized_uom and (
        not raw_uom or canonical_uom(split_uom) != split_uom
    ):
        if "UOM_STANDARD" not in methods:
            methods.append("UOM_STANDARD")

    return ParsedValue(
        raw_value=raw_value,
        raw_uom=raw_uom or split_uom,
        normalized_value=working,
        normalized_uom=normalized_uom,
        methods=methods,
    )


def comparable_key(value: str | None, uom: str | None, label: str, classpath: str | None = None) -> tuple[str, str] | None:
    parsed = normalize_raw(value, uom, label, classpath)
    if not parsed.normalized_value:
        return None
    return (
        parsed.normalized_value.strip().lower(),
        (parsed.normalized_uom or "").lower(),
    )
