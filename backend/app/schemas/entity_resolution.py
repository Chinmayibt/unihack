from pydantic import BaseModel, Field, field_validator


class EntityMatch(BaseModel):
    candidate: str | None = None
    canonical: str | None = None
    confidence: float = 0.0
    method: str
    status: str

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class EntityResolution(BaseModel):
    product_id: int
    status: str
    brand: EntityMatch
    manufacturer: EntityMatch
    brand_conflict: bool = False
    conflict_resolved: bool = False
