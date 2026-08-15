from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.graph import build_process_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.product import ProductResponse
from app.schemas.review import ProcessResponse
from app.services.review import process_response_from_state

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
def list_products(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[ProductRecord]:
    return (
        db.query(ProductRecord)
        .order_by(ProductRecord.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)) -> ProductRecord:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/{product_id}/process", response_model=ProcessResponse)
def process_product(product_id: int, db: Session = Depends(get_db)) -> ProcessResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_process_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        lowered = message.lower()
        status = (
            404
            if "not found" in lowered or "not been" in lowered
            else 502
        )
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    return process_response_from_state(product_id, result, db)
