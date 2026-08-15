from pydantic import BaseModel, Field, field_validator


STATUS_EXTRACTED = "EXTRACTED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


class ProductAttribute(BaseModel):
    label: str
    value: str | None = None
    uom: str | None = None
    source_id: int | None = None
    document_id: int | None = None
    page: int | None = None
    evidence_text: str | None = None
    confidence: float = 0.0
    status: str = STATUS_NOT_FOUND
    retrieval_score: float = 0.0

    @field_validator("confidence", "retrieval_score", mode="before")
    @classmethod
    def clamp_score(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class AttributeTemplateItem(BaseModel):
    label: str
    query: str
    required: bool = False
    expects_uom: bool = False
    uom_family: str | None = None


class LLMExtractedSlot(BaseModel):
    label: str
    value: str | None = None
    uom: str | None = None
    evidence_text: str | None = None
    supported: bool = False
    extraction_certainty: float = 0.0

    @field_validator("extraction_certainty", mode="before")
    @classmethod
    def clamp_certainty(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class LLMAttributeExtraction(BaseModel):
    attributes: list[LLMExtractedSlot] = Field(default_factory=list)


class ExtractionMetrics(BaseModel):
    extraction_total_ms: float = 0.0
    retrieval_ms: float = 0.0
    embedding_ms: float = 0.0
    vector_search_ms: float = 0.0
    llm_ms: float = 0.0
    llm_request_ms: float = 0.0
    llm_wait_ms: float = 0.0
    llm_cooldown_ms: float = 0.0
    llm_attempts: int = 0
    persistence_ms: float = 0.0
    embedding_call_count: int = 0
    vector_search_count: int = 0
    llm_call_count: int = 0
    attribute_count: int = 0


class AttributeExtractionResponse(BaseModel):
    product_id: int
    status: str
    classpath: str | None = None
    attributes: list[ProductAttribute] = Field(default_factory=list)
    metrics: ExtractionMetrics = Field(default_factory=ExtractionMetrics)
