from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class Evidence(BaseModel):
    """Traceable retrieved evidence. Not an extracted attribute."""

    text: str
    evidence_text: str
    score: float
    source: str
    url: str
    page: int | None = None
    source_id: int | None = None
    document_id: int | None = None
    source_type: str | None = None
    retrieval_score: float = 0.0

    @field_validator("score", "retrieval_score", mode="before")
    @classmethod
    def clamp_score(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class SearchResponse(BaseModel):
    product_id: int
    query: str
    results: list[Evidence] = Field(default_factory=list)
    embedding_ms: float = 0.0
    vector_search_ms: float = 0.0
    embedding_call_count: int = 0
    vector_search_count: int = 0
