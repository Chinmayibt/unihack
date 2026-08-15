from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import build_index_graph
from app.agents.state import empty_product_state
from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.document import IndexResponse
from app.schemas.evidence import SearchRequest, SearchResponse
from app.services.retrieval import search_product_evidence

router = APIRouter(tags=["rag"])


@router.post("/products/{product_id}/index", response_model=IndexResponse)
def index_product(product_id: int, db: Session = Depends(get_db)) -> IndexResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    graph = build_index_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        message = errors[0]
        status = 404 if "not found" in message.lower() or "not been" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)

    db.commit()
    payload = result.get("index_result") or {}
    return IndexResponse.model_validate(payload)


@router.post("/products/{product_id}/search", response_model=SearchResponse)
def search_product(
    product_id: int,
    body: SearchRequest,
    db: Session = Depends(get_db),
) -> SearchResponse:
    try:
        return search_product_evidence(product_id, body.query, db, top_k=body.top_k)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
