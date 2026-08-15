from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import build_validate_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.validation import ValidationResult
from app.services.validation import get_validation

router = APIRouter(tags=["validation"])


@router.post("/products/{product_id}/validate", response_model=ValidationResult)
def validate_one(product_id: int, db: Session = Depends(get_db)) -> ValidationResult:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_validate_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        status = 404 if "not found" in message.lower() or "not been" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    return get_validation(product_id, db)


@router.get("/products/{product_id}/validation", response_model=ValidationResult)
def read_validation(product_id: int, db: Session = Depends(get_db)) -> ValidationResult:
    try:
        return get_validation(product_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
