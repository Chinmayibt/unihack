from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import build_research_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.source import ProductSource, ResearchResponse
from app.services.research import get_sources, sources_to_response

router = APIRouter(tags=["research"])


@router.post("/products/{product_id}/research", response_model=ResearchResponse)
def research_product(product_id: int, db: Session = Depends(get_db)) -> ResearchResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_research_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        status = 404 if "not been understood" in message.lower() or "not found" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    sources = [ProductSource.model_validate(item) for item in (result.get("sources") or [])]
    return sources_to_response(product_id, sources, metrics=result.get("research_metrics"))


@router.get("/products/{product_id}/sources", response_model=ResearchResponse)
def read_sources(product_id: int, db: Session = Depends(get_db)) -> ResearchResponse:
    try:
        return get_sources(product_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
