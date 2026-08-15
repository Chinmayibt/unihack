from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMProductUnderstanding(BaseModel):
    """Strict structured output the Understanding Agent must return.

    Does not include source fields or brand_conflict — those are derived
    deterministically so the model cannot overwrite source truth.
    """

    product_type: str | None = Field(
        default=None,
        description="Likely product type from the description, e.g. Sanding Belt. Null if unclear.",
    )
    brand_candidate: str | None = Field(
        default=None,
        description="Brand name appearing in the description, if any. Not a canonical brand.",
    )
    manufacturer_candidate: str | None = Field(
        default=None,
        description="Manufacturer candidate from Part_Manuf / description. Strip trailing codes if obvious.",
    )
    category_candidates: list[str] = Field(
        default_factory=list,
        description="Possible categories. Candidates only, not a final classification.",
    )
    extracted_terms: list[str] = Field(
        default_factory=list,
        description="Meaningful terms explicitly present in the input.",
    )
    candidate_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Attributes explicitly present in the input, e.g. width, length, quantity.",
    )
    confidence: float = Field(
        default=0.0,
        description="Confidence that the interpretation is supported by the input only, from 0 to 1.",
    )
    reasoning_summary: str | None = Field(
        default=None,
        description="One or two sentences explaining what was taken from the input.",
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class ProductUnderstanding(LLMProductUnderstanding):
    """Phase 2 understanding record. Candidates, not validated facts."""

    mpn: str
    source_brand: str | None = None
    source_manufacturer: str | None = None
    brand_conflict: bool = False


class UnderstandResponse(BaseModel):
    product_id: int
    status: str
    understanding: ProductUnderstanding


class BatchUnderstandResponse(BaseModel):
    status: str
    total: int
    processed: int
    succeeded: int
    failed: int
    results: list[UnderstandResponse] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class UnderstandingRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    status: str
    understanding: ProductUnderstanding
