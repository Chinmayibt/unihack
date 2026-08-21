import json
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import IngestionJob
from app.schemas.product import ProductIntakeItem, UploadResponse
from app.services.ingestion import (
    MissingColumnError,
    ingest_csv,
    ingest_json_bytes,
    ingest_json_payload,
)

router = APIRouter(tags=["ingestion"])


def _is_csv(filename: str | None) -> bool:
    if not filename:
        return False
    return filename.lower().endswith(".csv")


def _is_json(filename: str | None) -> bool:
    if not filename:
        return False
    lower = filename.lower()
    return lower.endswith(".json") or lower.endswith(".jsonl")


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if not _is_csv(file.filename):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    contents = await file.read()
    if not contents.strip():
        raise HTTPException(status_code=400, detail="CSV file is empty")

    try:
        return ingest_csv(contents, file.filename or "upload.csv", db)
    except MissingColumnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload/json", response_model=UploadResponse)
async def upload_json_body(
    request: Request,
    db: Session = Depends(get_db),
) -> UploadResponse:
    try:
        payload: Any = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Body must be valid JSON") from exc
    try:
        return ingest_json_payload(payload, "inline.json", db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload/json/file", response_model=UploadResponse)
async def upload_json_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if not _is_json(file.filename):
        raise HTTPException(status_code=400, detail="File must be JSON (.json)")
    contents = await file.read()
    if not contents.strip():
        raise HTTPException(status_code=400, detail="JSON file is empty")
    try:
        return ingest_json_bytes(contents, file.filename or "upload.json", db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload/product", response_model=UploadResponse)
def upload_single_product(
    payload: ProductIntakeItem,
    db: Session = Depends(get_db),
) -> UploadResponse:
    try:
        return ingest_json_payload(payload.to_csv_row(), "single-product.json", db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ingestion-jobs/{job_id}", response_model=UploadResponse)
def get_job(job_id: str, db: Session = Depends(get_db)) -> UploadResponse:
    job = db.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    errors = json.loads(job.errors_json) if job.errors_json else []
    return UploadResponse(
        status=job.status,
        job_id=job.id,
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        missing_mpn=job.missing_mpn,
        missing_description=job.missing_description,
        duplicate_mpns=job.duplicate_mpns,
        missing_manufacturer=job.missing_manufacturer,
        missing_brand=job.missing_brand,
        errors=errors,
    )
