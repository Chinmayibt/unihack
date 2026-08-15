from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import build_resolution_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.entity_resolution import EntityResolution
from app.services.entity_resolution import (
    ProductNotFoundError,
    ResolutionNotFoundError,
    get_entities,
)
from app.services.master_data import seed_master_data

router = APIRouter(tags=["entity-resolution"])


@router.post("/products/{product_id}/resolve", response_model=EntityResolution)
def resolve_product_entities(
    product_id: int, db: Session = Depends(get_db)
) -> EntityResolution:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_resolution_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        status = 404 if "not been understood" in message.lower() or "not found" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    return EntityResolution.model_validate(result["entity_resolution"])


@router.get("/products/{product_id}/entities", response_model=EntityResolution)
def read_entities(product_id: int, db: Session = Depends(get_db)) -> EntityResolution:
    try:
        return get_entities(product_id, db)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResolutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/master/seed")
def seed_entities(db: Session = Depends(get_db)) -> dict[str, int]:
    counts = seed_master_data(db)
    db.commit()
    return counts
