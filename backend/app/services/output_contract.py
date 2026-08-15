from __future__ import annotations

from app.schemas.final_output import (
    ATTRIBUTE_SLOT_COUNT,
    EMPTY_OUTPUT_VALUE,
    EXPECTED_OUTPUT_COLUMNS,
    FinalProductOutput,
)


def empty_output_row() -> dict[str, str]:
    return {column: EMPTY_OUTPUT_VALUE for column in EXPECTED_OUTPUT_COLUMNS}


def freeze_output_row(values: dict[str, str | None]) -> dict[str, str]:
    missing = [column for column in EXPECTED_OUTPUT_COLUMNS if column not in values]
    if missing:
        raise ValueError(f"Required output column missing: {missing[0]}")
    extra = [column for column in values if column not in EXPECTED_OUTPUT_COLUMNS]
    if extra:
        raise ValueError(f"Unexpected output column: {extra[0]}")
    row = {
        column: EMPTY_OUTPUT_VALUE if values[column] is None else str(values[column])
        for column in EXPECTED_OUTPUT_COLUMNS
    }
    return FinalProductOutput(values=row).as_row()


def attribute_slot_headers(index: int) -> tuple[str, str, str]:
    if index < 1 or index > ATTRIBUTE_SLOT_COUNT:
        raise ValueError(f"Attribute slot {index} is outside 1..{ATTRIBUTE_SLOT_COUNT}")
    return (
        f"ATTRIBUTE_LABEL {index}",
        f"ATTRIBUTE_VALUE {index}",
        f"ATTRIBUTE_UOM {index}",
    )
