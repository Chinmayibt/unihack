from pydantic import BaseModel, Field, field_validator


SOURCE_INPUT = "INPUT"
SOURCE_MANUFACTURER = "MANUFACTURER"
SOURCE_DISTRIBUTOR = "AUTHORIZED_DISTRIBUTOR"
SOURCE_RETAILER = "RETAILER"
SOURCE_MARKETPLACE = "MARKETPLACE"
SOURCE_OTHER = "OTHER"

AGREEMENT = "AGREEMENT"
MANUFACTURER_SUPPORTED = "MANUFACTURER_SUPPORTED"
INPUT_SOURCED = "INPUT_SOURCED"
SECONDARY_SOURCE_ONLY = "SECONDARY_SOURCE_ONLY"
CONFLICT = "CONFLICT"
NOT_FOUND = "NOT_FOUND"

STATUS_NORMALIZED = "NORMALIZED"
STATUS_UNCHANGED = "UNCHANGED"
STATUS_CONFLICT = "CONFLICT"
STATUS_SECONDARY = "SECONDARY_SOURCE_ONLY"
STATUS_NOT_FOUND = "NOT_FOUND"

SELECTABLE_SOURCES = {SOURCE_INPUT, SOURCE_MANUFACTURER}


class EvidenceCandidate(BaseModel):
    value: str
    uom: str | None = None
    source: str
    authority: float = 0.0
    source_id: int | None = None
    evidence_text: str | None = None

    @field_validator("authority", mode="before")
    @classmethod
    def clamp_authority(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class NormalizedAttribute(BaseModel):
    label: str
    raw_value: str | None = None
    normalized_value: str | None = None
    raw_uom: str | None = None
    normalized_uom: str | None = None
    source_id: int | None = None
    evidence_text: str | None = None
    selected_source: str | None = None
    agreement: str = NOT_FOUND
    candidates: list[EvidenceCandidate] = Field(default_factory=list)
    normalization_method: str | None = None
    status: str = STATUS_NOT_FOUND
    ai_value: str | None = None
    human_value: str | None = None
    review_decision: str | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None


class NormalizationResponse(BaseModel):
    product_id: int
    status: str
    classpath: str | None = None
    completeness: str = "PARTIAL"
    missing_attributes: list[str] = Field(default_factory=list)
    requires_review: bool = False
    attributes: list[NormalizedAttribute] = Field(default_factory=list)
