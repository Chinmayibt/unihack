import re
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.connection import SessionLocal, get_db
from app.schemas.job import (
    JOB_COMPLETED,
    JobCreateRequest,
    JobErrorOut,
    JobProductList,
    JobProductStages,
    JobProfile,
    JobReport,
    JobSummary,
    ReviewBreakdown,
)
from app.services.jobs import (
    create_job,
    enrich_job_summary,
    get_job,
    get_product_stages,
    job_profile,
    job_report,
    job_review_stats,
    job_to_summary,
    list_job_errors,
    list_job_products,
    list_jobs,
    retry_product,
    run_processing_job,
)
from app.services.output_generate import generate_output

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _run_job_background(job_id: str) -> None:
    db = SessionLocal()
    try:
        run_processing_job(db, job_id)
        db.commit()
    finally:
        db.close()


@router.post("", response_model=JobSummary)
def create_processing_job(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload: JobCreateRequest | None = Body(default=None),
) -> JobSummary:
    payload = payload or JobCreateRequest()
    try:
        job = create_job(db, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.auto_start and job.total_products:
        if settings.TESTING:
            job = run_processing_job(db, job.id)
        else:
            background_tasks.add_task(_run_job_background, job.id)
            job = get_job(db, job.id)
    return enrich_job_summary(db, job_to_summary(job))


@router.get("", response_model=list[JobSummary])
def read_jobs(db: Session = Depends(get_db)) -> list[JobSummary]:
    return [job_to_summary(job) for job in list_jobs(db)]


@router.post("/{job_id}/start", response_model=JobSummary)
def start_processing_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobSummary:
    try:
        job = get_job(db, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if settings.TESTING:
        job = run_processing_job(db, job_id)
    else:
        background_tasks.add_task(_run_job_background, job_id)
    finished = get_job(db, job_id) if not settings.TESTING else job
    return enrich_job_summary(db, job_to_summary(finished))


@router.get("/{job_id}", response_model=JobSummary)
def read_job(job_id: str, db: Session = Depends(get_db)) -> JobSummary:
    try:
        return enrich_job_summary(db, job_to_summary(get_job(db, job_id)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_id}/profile", response_model=JobProfile)
def read_job_profile(job_id: str, db: Session = Depends(get_db)) -> JobProfile:
    try:
        return job_profile(db, get_job(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_id}/review-breakdown", response_model=ReviewBreakdown)
def read_job_review_breakdown(
    job_id: str,
    details: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> ReviewBreakdown:
    try:
        return job_review_stats(db, get_job(db, job_id), details=details)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_id}/report", response_model=JobReport)
def read_job_report(job_id: str, db: Session = Depends(get_db)) -> JobReport:
    try:
        return job_report(get_job(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_id}/products", response_model=JobProductList)
def read_job_products(
    job_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> JobProductList:
    try:
        get_job(db, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    total, items = list_job_products(db, job_id, skip=skip, limit=limit)
    return JobProductList(total=total, items=items)


@router.get("/{job_id}/output.csv")
def download_job_output(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    try:
        job = get_job(db, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = Path(job.output_file) if job.output_file else None
    if path is None or not path.exists():
        if job.status != JOB_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail="Output is available after the job completes.",
            )
        result = generate_output(db, job=job)
        if not result.output_file:
            raise HTTPException(
                status_code=409,
                detail="No eligible rows to write to CSV.",
            )
        job.output_file = result.output_file
        db.commit()
        path = Path(result.output_file)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", job.dataset_name or "job").strip("_")
    filename = f"{safe_name or 'job'}_delivery.csv"
    return FileResponse(path, media_type="text/csv", filename=filename)


@router.get("/{job_id}/errors", response_model=list[JobErrorOut])
def read_job_errors(job_id: str, db: Session = Depends(get_db)) -> list[JobErrorOut]:
    try:
        get_job(db, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list_job_errors(db, job_id)


@router.get("/{job_id}/products/{product_id}/stages", response_model=JobProductStages)
def read_product_stages(
    job_id: str, product_id: int, db: Session = Depends(get_db)
) -> JobProductStages:
    try:
        get_job(db, job_id)
        return get_product_stages(db, job_id, product_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/products/{product_id}/retry", response_model=JobSummary)
def retry_job_product(
    job_id: str, product_id: int, db: Session = Depends(get_db)
) -> JobSummary:
    try:
        job = retry_product(db, job_id, product_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return enrich_job_summary(db, job_to_summary(job))
