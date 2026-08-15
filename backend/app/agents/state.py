from typing import TypedDict


class ProductState(TypedDict):
    product_id: int
    raw_product: dict
    understanding: dict
    entity_resolution: dict
    classification: dict
    sources: list[dict]
    index_result: dict
    evidence: list[dict]
    attributes: list[dict]
    normalized_attributes: list[dict]
    validation: dict
    extraction_metrics: dict
    research_metrics: dict
    review_ids: list[int]
    review_id: int | None
    confidence: float
    errors: list[str]
    requires_review: bool


def empty_product_state(product_id: int) -> ProductState:
    return {
        "product_id": product_id,
        "raw_product": {},
        "understanding": {},
        "entity_resolution": {},
        "classification": {},
        "sources": [],
        "index_result": {},
        "evidence": [],
        "attributes": [],
        "normalized_attributes": [],
        "validation": {},
        "extraction_metrics": {},
        "research_metrics": {},
        "review_ids": [],
        "review_id": None,
        "confidence": 0.0,
        "errors": [],
        "requires_review": False,
    }
