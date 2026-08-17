from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import build_extract_graph, build_normalize_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.attribute import AttributeExtractionResponse, ExtractionMetrics
from app.schemas.normalized_attribute import NormalizationResponse
from app.services.attribute_extraction import get_attributes
from app.services.attribute_normalization import get_normalized_attributes
from app.services.llm_retry import is_daily_token_limit
from app.services.review import defer_llm_quota_exhausted

router = APIRouter(tags=["attributes"])


@router.post(
    "/products/{product_id}/attributes/extract",
    response_model=AttributeExtractionResponse,
)
def extract_product_attribute_values(
    product_id: int, db: Session = Depends(get_db)
) -> AttributeExtractionResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_extract_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        lowered = message.lower()
        if is_daily_token_limit(message):
            defer_llm_quota_exhausted(db, product_id, message=message, stage="extraction")
            db.commit()
            raise HTTPException(
                status_code=409,
                detail={"issue_type": "LLM_QUOTA_EXHAUSTED", "message": message},
            )
        status = (
            404
            if "not found" in lowered or "not been indexed" in lowered
            else 502
        )
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    saved = get_attributes(product_id, db)
    metrics = result.get("extraction_metrics") or {}
    if metrics:
        saved.metrics = ExtractionMetrics.model_validate(metrics)
    return saved


@router.get("/products/{product_id}/attributes", response_model=AttributeExtractionResponse)
def read_attributes(
    product_id: int, db: Session = Depends(get_db)
) -> AttributeExtractionResponse:
    try:
        return get_attributes(product_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/products/{product_id}/attributes/normalize",
    response_model=NormalizationResponse,
)
def normalize_product_attribute_values(
    product_id: int, db: Session = Depends(get_db)
) -> NormalizationResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_normalize_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        status = 404 if "not found" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    return get_normalized_attributes(product_id, db)


@router.get(
    "/products/{product_id}/attributes/normalized",
    response_model=NormalizationResponse,
)
def read_normalized_attributes(
    product_id: int, db: Session = Depends(get_db)
) -> NormalizationResponse:
    try:
        return get_normalized_attributes(product_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
