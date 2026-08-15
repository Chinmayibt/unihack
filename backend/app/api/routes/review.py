from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.review import (
    STATUS_PENDING,
    ReviewDetail,
    ReviewQueueList,
    ReviewResolveRequest,
    ReviewResolveResponse,
)
from app.services.review import get_review, list_review_queue, resolve_review

router = APIRouter(prefix="/review-queue", tags=["review"])


@router.get("", response_model=ReviewQueueList)
def read_review_queue(
    status: str | None = Query(default=STATUS_PENDING),
    product_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ReviewQueueList:
    return list_review_queue(db, status=status, product_id=product_id)


@router.get("/{review_id}", response_model=ReviewDetail)
def read_review(review_id: int, db: Session = Depends(get_db)) -> ReviewDetail:
    try:
        return get_review(review_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{review_id}/resolve", response_model=ReviewResolveResponse)
def resolve_one(
    review_id: int, payload: ReviewResolveRequest, db: Session = Depends(get_db)
) -> ReviewResolveResponse:
    try:
        result = resolve_review(review_id, payload, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc
    db.commit()
    return result
