from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import build_classification_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.classification import ClassificationResponse, ClassificationResult
from app.services.classification import get_classification

router = APIRouter(tags=["classification"])


@router.post("/products/{product_id}/classify", response_model=ClassificationResponse)
def classify_one(product_id: int, db: Session = Depends(get_db)) -> ClassificationResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_classification_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        status = 404 if "not been understood" in message.lower() or "not found" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    classification = ClassificationResult.model_validate(result["classification"])
    return ClassificationResponse(
        product_id=product_id,
        status=classification.status,
        classification=classification,
    )


@router.get("/products/{product_id}/classification", response_model=ClassificationResponse)
def read_classification(
    product_id: int, db: Session = Depends(get_db)
) -> ClassificationResponse:
    try:
        return get_classification(product_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
