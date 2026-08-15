from pydantic import BaseModel, Field, field_validator


STATUS_PASS = "PASS"
STATUS_PARTIAL = "PARTIAL"
STATUS_REVIEW = "REVIEW_REQUIRED"
STATUS_FAIL = "FAIL"

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

ISSUE_MISSING_REQUIRED = "MISSING_REQUIRED"
ISSUE_UOM_INVALID = "UOM_INVALID"
ISSUE_UOM_MISSING = "UOM_MISSING"
ISSUE_LOV_INVALID = "LOV_INVALID"
ISSUE_MISSING_EVIDENCE = "MISSING_EVIDENCE"
ISSUE_SOURCE_CONFLICT = "SOURCE_CONFLICT"
ISSUE_SECONDARY_ONLY = "SECONDARY_SOURCE_ONLY"
ISSUE_MISSING_IDENTITY = "MISSING_IDENTITY"


class ValidationIssue(BaseModel):
    attribute: str
    issue_type: str
    severity: str
    message: str
    requires_review: bool = False
    raw_value: str | None = None
    normalized_value: str | None = None
    allowed_values: list[str] = Field(default_factory=list)
    source: str | None = None
    evidence_text: str | None = None


class ValidationResult(BaseModel):
    product_id: int
    status: str
    completeness_score: float = 0.0
    evidence_coverage: float = 0.0
    missing_attributes: list[str] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    requires_review: bool = False
    approved_for_output: bool = False

    @field_validator("completeness_score", "evidence_coverage", mode="before")
    @classmethod
    def clamp_score(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))
