from pydantic import BaseModel, Field, field_validator

from app.schemas.validation import ValidationResult


STATUS_PENDING = "PENDING"
STATUS_IN_REVIEW = "IN_REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_UNKNOWN = "UNKNOWN"

REVIEW_STATUSES = (
    STATUS_PENDING,
    STATUS_IN_REVIEW,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_UNKNOWN,
)

DECISION_APPROVE_CURRENT = "APPROVE_CURRENT"
DECISION_SELECT_CANDIDATE = "SELECT_CANDIDATE"
DECISION_REJECT_ATTRIBUTE = "REJECT_ATTRIBUTE"
DECISION_MARK_UNKNOWN = "MARK_UNKNOWN"

REVIEW_DECISIONS = (
    DECISION_APPROVE_CURRENT,
    DECISION_SELECT_CANDIDATE,
    DECISION_REJECT_ATTRIBUTE,
    DECISION_MARK_UNKNOWN,
)

ISSUE_SOURCE_CONFLICT = "SOURCE_CONFLICT"
ISSUE_LOV_INVALID = "LOV_INVALID"
ISSUE_UOM_INVALID = "UOM_INVALID"
ISSUE_SECONDARY_ONLY = "SECONDARY_SOURCE_ONLY"
ISSUE_MISSING_EVIDENCE = "MISSING_EVIDENCE"
ISSUE_MISSING_REQUIRED = "MISSING_REQUIRED"
ISSUE_MISSING_IDENTITY = "MISSING_IDENTITY"
ISSUE_BRAND_CONFLICT = "BRAND_CONFLICT"
ISSUE_LOW_CLASSIFICATION_CONFIDENCE = "LOW_CLASSIFICATION_CONFIDENCE"
ISSUE_NO_AUTHORITATIVE_SOURCE = "NO_AUTHORITATIVE_SOURCE"
ISSUE_LLM_QUOTA_EXHAUSTED = "LLM_QUOTA_EXHAUSTED"


class ReviewIssue(BaseModel):
    product_id: int
    issue_type: str
    severity: str
    attribute: str | None = None
    current_value: str | None = None
    candidate_values: list[str] = Field(default_factory=list)
    reason: str
    status: str = STATUS_PENDING


class ReviewCandidate(BaseModel):
    value: str
    source: str | None = None
    evidence_text: str | None = None
    source_id: int | None = None
    authority: float | None = None


class ReviewQueueItem(BaseModel):
    id: int
    product_id: int
    mpn: str | None = None
    issue_type: str
    severity: str
    attribute: str | None = None
    current_value: str | None = None
    reason: str
    status: str
    raw_value: str | None = None
    normalized_value: str | None = None
    allowed_values: list[str] = Field(default_factory=list)
    source: str | None = None
    evidence_text: str | None = None


class ReviewQueueList(BaseModel):
    total: int
    items: list[ReviewQueueItem] = Field(default_factory=list)


class ReviewProductSummary(BaseModel):
    id: int
    mpn: str
    description: str
    brand: str | None = None
    manufacturer: str | None = None
    status: str
    classification: dict | None = None


class ReviewSourceSummary(BaseModel):
    id: int
    url: str
    title: str | None = None
    source_type: str
    authority_score: float = 0.0


class ReviewDetail(BaseModel):
    id: int
    product_id: int
    issue_type: str
    severity: str
    attribute: str | None = None
    current_value: str | None = None
    candidate_values: list[ReviewCandidate] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    sources: list[ReviewSourceSummary] = Field(default_factory=list)
    confidence: float | None = None
    reason: str
    status: str
    assigned_to: str | None = None
    ai_value: str | None = None
    final_value: str | None = None
    decision: str | None = None
    selected_source: str | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    allowed_values: list[str] = Field(default_factory=list)
    source: str | None = None
    evidence_text: str | None = None
    product: ReviewProductSummary


class ReviewResolveRequest(BaseModel):
    decision: str
    selected_value: str | None = None
    selected_source: str | None = None
    reviewed_by: str = "reviewer"
    review_reason: str | None = None

    @field_validator("decision")
    @classmethod
    def known_decision(cls, value: str) -> str:
        decision = str(value).strip().upper().replace(" ", "_")
        aliases = {
            "APPROVE": DECISION_APPROVE_CURRENT,
            "SELECT": DECISION_SELECT_CANDIDATE,
            "REJECT": DECISION_REJECT_ATTRIBUTE,
            "UNKNOWN": DECISION_MARK_UNKNOWN,
            "MARK_AS_UNKNOWN": DECISION_MARK_UNKNOWN,
        }
        decision = aliases.get(decision, decision)
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"decision must be one of {', '.join(REVIEW_DECISIONS)}")
        return decision


class ReviewResolveResponse(BaseModel):
    review_id: int
    product_id: int
    attribute: str | None = None
    final_value: str | None = None
    decision: str
    selected_source: str | None = None
    reviewed_by: str
    review_reason: str | None = None
    product_status: str
    remaining_reviews: int = 0
    paused: bool = False


class ProcessResponse(BaseModel):
    product_id: int
    status: str
    approved_for_output: bool = False
    requires_review: bool = False
    review_id: int | None = None
    review_ids: list[int] = Field(default_factory=list)
    paused: bool = False
    validation: ValidationResult | None = None
