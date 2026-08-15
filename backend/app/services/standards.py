from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060\u00ad"), None)
_DASH_TO_SPACE = dict.fromkeys(
    map(ord, "-\u2010\u2011\u2012\u2013\u2014\u2212\u2043"), " "
)

REFERENCE_DIR = Path(__file__).resolve().parents[3] / "data" / "reference"


def _load_json(name: str) -> dict | list:
    path = REFERENCE_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def uom_alias_map() -> dict[str, str]:
    data = _load_json("uom_standards.json")
    mapping: dict[str, str] = {}
    for row in data.get("units") or []:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        mapping[code.lower()] = code
        for alias in row.get("aliases") or []:
            key = str(alias).strip().lower()
            if key:
                mapping[key] = code
    return mapping


@lru_cache(maxsize=1)
def uom_aliases_longest() -> list[str]:
    aliases = sorted(uom_alias_map().keys(), key=len, reverse=True)
    return [alias for alias in aliases if alias]


@lru_cache(maxsize=1)
def fraction_table() -> tuple[float, list[tuple[float, str]]]:
    data = _load_json("decimal_fractions.json")
    tolerance = float(data.get("tolerance") or 0.0005)
    rows = [
        (float(item["decimal"]), str(item["fraction"]))
        for item in data.get("mappings") or []
        if item.get("fraction") is not None
    ]
    rows.sort(key=lambda item: item[0])
    return tolerance, rows


@lru_cache(maxsize=1)
def lov_table() -> dict[str, list[dict]]:
    data = _load_json("lov.json")
    return data.get("attributes") or {}


@lru_cache(maxsize=1)
def lov_alias_rows() -> list[dict]:
    data = _load_json("lov_aliases.json")
    rows = data.get("aliases") if isinstance(data, dict) else data
    return [row for row in (rows or []) if isinstance(row, dict)]


@lru_cache(maxsize=1)
def taxonomy_rows() -> list[dict]:
    data = _load_json("taxonomy.json")
    return data if isinstance(data, list) else []


def canonical_lov_key(value: str | None) -> str:
    """Comparison key only. Does not change the stored canonical LOV string.

    Fold case, Unicode compatibility, zero-width chars, hyphen/dash variants, and
    whitespace. Semantic aliases are a later step — this is not a fuzzy matcher.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.translate(_ZERO_WIDTH)
    text = text.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    text = text.translate(_DASH_TO_SPACE)
    return " ".join(text.strip().lower().split())


def canonical_uom(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = str(raw).strip().lower()
    if not key:
        return None
    return uom_alias_map().get(key)


UOM_FAMILIES: dict[str, set[str]] = {
    "length": {"in", "ft", "mm", "cm"},
    "electrical_potential": {"V"},
    "electrical_current": {"A"},
    "sound": {"dBA"},
    "count": {"EA", "PK"},
}


def uoms_for_family(family: str | None) -> set[str] | None:
    if not family:
        return None
    return UOM_FAMILIES.get(family)


def allowed_lov_values(label: str, classpath: str | None) -> list[str] | None:
    if label.strip().lower() == "product type":
        canonical, _aliases = taxonomy_product_type(classpath)
        return [canonical] if canonical else None
    entries = lov_table().get(label)
    if not entries:
        return None
    return [str(item.get("canonical")) for item in entries if item.get("canonical")]


def taxonomy_product_type(classpath: str | None) -> tuple[str | None, list[str]]:
    needle = (classpath or "").strip()
    for row in taxonomy_rows():
        if (row.get("classpath") or "").strip() == needle:
            canonical = row.get("fine")
            aliases = [canonical, *(row.get("aliases") or [])]
            return canonical, [item for item in aliases if item]
    return None, []


def _related_lov_labels(label: str) -> set[str]:
    key = label.strip().lower()
    if key in {"material", "abrasive material"}:
        return {"material", "abrasive material"}
    return {key}


def approved_lov_alias_map(label: str, classpath: str | None) -> dict[str, str]:
    """alias canonical_lov_key → allowed-list canonical. Exact keys only; no substring."""
    allowed = allowed_lov_values(label, classpath)
    if not allowed:
        return {}
    allowed_set = set(allowed)
    mapping: dict[str, str] = {}

    def _add(raw: str | None, canonical: str | None) -> None:
        if not raw or not canonical or canonical not in allowed_set:
            return
        key = canonical_lov_key(raw)
        if key and key not in mapping:
            mapping[key] = canonical

    for item in allowed:
        _add(item, item)
    labels = _related_lov_labels(label)
    for attr, entries in lov_table().items():
        if attr.strip().lower() not in labels:
            continue
        for entry in entries:
            canonical = str(entry.get("canonical") or "").strip()
            _add(canonical, canonical)
            for alias in entry.get("aliases") or []:
                _add(str(alias), canonical)
    if label.strip().lower() == "product type":
        canonical, aliases = taxonomy_product_type(classpath)
        _add(canonical, canonical)
        for alias in aliases:
            _add(str(alias), canonical)
    for row in lov_alias_rows():
        attr = str(row.get("attribute") or "").strip().lower()
        if attr not in labels and not (
            label.strip().lower() == "product type" and attr == "product type"
        ):
            continue
        _add(str(row.get("raw_value") or ""), str(row.get("canonical_value") or "").strip())
    return mapping
