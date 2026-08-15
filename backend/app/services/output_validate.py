from __future__ import annotations

from app.schemas.final_output import (
    ATTRIBUTE_SLOT_COUNT,
    EXPECTED_OUTPUT_COLUMNS,
    REQUIRED_OUTPUT_FIELDS,
)
from app.services.attribute_templates import template_for_classpath
from app.services.output_contract import attribute_slot_headers
from app.services.standards import allowed_lov_values, canonical_uom, uoms_for_family
from app.services.value_normalize import resolve_lov


class OutputContractError(ValueError):
    pass


def validate_headers(headers: list[str]) -> None:
    if list(headers) != list(EXPECTED_OUTPUT_COLUMNS):
        raise OutputContractError("Generated headers do not match the frozen expected-output contract")


def _validate_required(row: dict[str, str]) -> None:
    for field in REQUIRED_OUTPUT_FIELDS:
        if not (row.get(field) or "").strip():
            raise OutputContractError(f"Required field {field} is empty")


def _validate_attribute_slots(row: dict[str, str], classpath: str | None) -> None:
    template = template_for_classpath(classpath)
    by_label = {item.label: item for item in template}
    for index in range(1, ATTRIBUTE_SLOT_COUNT + 1):
        label_key, value_key, uom_key = attribute_slot_headers(index)
        label = (row.get(label_key) or "").strip()
        value = (row.get(value_key) or "").strip()
        uom = (row.get(uom_key) or "").strip()
        if not label:
            if value or uom:
                raise OutputContractError(f"{value_key} is populated without a label")
            continue
        if value:
            allowed = allowed_lov_values(label, classpath)
            if allowed is not None:
                resolved, method = resolve_lov(label, value, classpath)
                if method != "LOV" or resolved not in allowed:
                    raise OutputContractError(f"{label} value {value!r} is not an allowed LOV value")
        if uom:
            approved = canonical_uom(uom)
            if approved is None:
                raise OutputContractError(f"{label} UOM {uom!r} is not an approved unit")
            spec = by_label.get(label)
            family = uoms_for_family(spec.uom_family) if spec else None
            if family is not None and approved not in family:
                raise OutputContractError(f"{label} UOM {uom!r} is not valid for its unit family")


def validate_output_row(row: dict[str, str]) -> None:
    validate_headers(list(row.keys()))
    _validate_required(row)
    _validate_attribute_slots(row, row.get("Classpath") or None)


def validate_output_rows(rows: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    for row in rows:
        validate_output_row(row)
        mpn = (row.get("Mfg_Part_Num") or "").strip()
        if mpn in seen:
            raise OutputContractError(f"Duplicate output row for MPN {mpn}")
        seen.add(mpn)
