from pydantic import BaseModel, Field, field_validator


class ClassificationResult(BaseModel):
    product_id: int
    department: str | None = None
    class_name: str | None = None
    fine: str | None = None
    classpath: str | None = None
    confidence: float = 0.0
    method: str
    status: str
    reasoning_summary: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class ClassificationResponse(BaseModel):
    product_id: int
    status: str
    classification: ClassificationResult


class LLMClassificationChoice(BaseModel):
    classpath: str | None = Field(
        default=None,
        description="Must be copied exactly from the provided candidate list, or null if none fit.",
    )
    confidence: float = Field(default=0.0, ge=0, le=1)
    reasoning_summary: str | None = None
