from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.product_understanding import MissingLLMConfigError
from app.database.connection import get_db
from app.schemas.understanding import BatchUnderstandResponse, UnderstandResponse
from app.services.understanding import (
    LlmQuotaExhaustedError,
    ProductNotFoundError,
    UnderstandingNotFoundError,
    get_understanding,
    understand_product,
    understand_products,
)

router = APIRouter(prefix="/products", tags=["understanding"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProductNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, UnderstandingNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MissingLLMConfigError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, LlmQuotaExhaustedError):
        return HTTPException(
            status_code=409,
            detail={
                "issue_type": "LLM_QUOTA_EXHAUSTED",
                "message": str(exc),
            },
        )
    return HTTPException(status_code=502, detail=str(exc))


@router.post("/understand", response_model=BatchUnderstandResponse)
def understand_batch(
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=1000),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> BatchUnderstandResponse:
    try:
        return understand_products(db, skip=skip, limit=limit, force=force)
    except MissingLLMConfigError as exc:
        raise _http_error(exc) from exc


@router.post("/{product_id}/understand", response_model=UnderstandResponse)
def understand_one(
    product_id: int, db: Session = Depends(get_db)
) -> UnderstandResponse:
    try:
        return understand_product(product_id, db)
    except (ProductNotFoundError, MissingLLMConfigError, LlmQuotaExhaustedError, RuntimeError) as exc:
        raise _http_error(exc) from exc


@router.get("/{product_id}/understanding", response_model=UnderstandResponse)
def read_understanding(
    product_id: int, db: Session = Depends(get_db)
) -> UnderstandResponse:
    try:
        return get_understanding(product_id, db)
    except (ProductNotFoundError, UnderstandingNotFoundError) as exc:
        raise _http_error(exc) from exc
