from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.validation import ValidationResult

REFERENCE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "expected_output_columns.json"
)


def _load_expected_columns() -> tuple[list[str], int, str]:
    if not REFERENCE_PATH.exists():
        raise RuntimeError(f"Expected output contract is missing: {REFERENCE_PATH}")
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    columns = [str(item) for item in (data.get("columns") or [])]
    if not columns:
        raise RuntimeError("Expected output contract has no columns")
    if len(columns) != len(set(columns)):
        raise RuntimeError("Expected output contract has duplicate headers")
    slots = int(data.get("attribute_slots") or 50)
    empty = str(data.get("empty_value", ""))
    return columns, slots, empty


EXPECTED_OUTPUT_COLUMNS, ATTRIBUTE_SLOT_COUNT, EMPTY_OUTPUT_VALUE = _load_expected_columns()

REQUIRED_OUTPUT_FIELDS = ("Mfg_Part_Num", "Part_Desc")

STATUS_COMPLETED = "COMPLETED"
STATUS_OUTPUT_FAILED = "OUTPUT_GENERATION_FAILED"

NAMED_DIMENSIONS = {
    "Width": ("WIDTH", "WIDTH_UOM"),
    "Length": ("LENGTH", "LENGTH_UOM"),
    "Height": ("HEIGHT", "HEIGHT_UOM"),
    "Weight": ("WEIGHT", "WEIGHT_UOM"),
    "Volume": ("VOLUME", "VOLUME_UOM"),
}


class AttributeProvenance(BaseModel):
    label: str
    final_value: str | None = None
    normalized_uom: str | None = None
    raw_value: str | None = None
    selected_source: str | None = None
    source_id: int | None = None
    source_url: str | None = None
    evidence_text: str | None = None
    agreement: str | None = None
    ai_value: str | None = None
    human_value: str | None = None
    review_decision: str | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None


class FinalProductInternal(BaseModel):
    input_identity: dict = Field(default_factory=dict)
    resolved_entities: dict = Field(default_factory=dict)
    classification: dict | None = None
    attributes: list[dict] = Field(default_factory=list)
    provenance: list[AttributeProvenance] = Field(default_factory=list)
    validation: ValidationResult | None = None


class FinalProductOutput(BaseModel):
    """One expected-output CSV row. Keys must match the frozen header contract."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, str]

    @model_validator(mode="after")
    def exact_headers(self) -> "FinalProductOutput":
        keys = list(self.values.keys())
        if keys != list(EXPECTED_OUTPUT_COLUMNS):
            missing = [col for col in EXPECTED_OUTPUT_COLUMNS if col not in self.values]
            extra = [col for col in keys if col not in EXPECTED_OUTPUT_COLUMNS]
            raise ValueError(
                "Final output headers do not match the frozen contract"
                + (f"; missing={missing[:8]}" if missing else "")
                + (f"; extra={extra[:8]}" if extra else "")
            )
        for column, value in self.values.items():
            if value is None:
                raise ValueError(f"Column {column!r} is None; use the approved empty representation")
            if not isinstance(value, str):
                raise ValueError(f"Column {column!r} must be a string")
        return self

    def as_row(self) -> dict[str, str]:
        return {column: self.values[column] for column in EXPECTED_OUTPUT_COLUMNS}


class FinalProductEnvelope(BaseModel):
    product_id: int
    mpn: str
    processing_status: str
    reviewed: bool = False
    approved_for_output: bool = False
    eligible_for_csv: bool = False
    eligibility_reason: str = "not_ready"
    assembled: FinalProductInternal
    output: dict[str, str]
    errors: list[str] = Field(default_factory=list)


class OutputGenerateResponse(BaseModel):
    status: str
    total_products: int = 0
    approved: int = 0
    partial: int = 0
    review_pending: int = 0
    skipped: int = 0
    output_file: str | None = None
    job_id: str | None = None
    errors: list[str] = Field(default_factory=list)
