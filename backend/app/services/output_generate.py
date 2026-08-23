from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import (
    ProcessingJobItem,
    ProcessingJobRecord,
    ProductRecord,
)
from app.schemas.final_output import (
    EXPECTED_OUTPUT_COLUMNS,
    STATUS_COMPLETED,
    STATUS_OUTPUT_FAILED,
    OutputGenerateResponse,
)
from app.schemas.job import JOB_COMPLETED, JOB_PAUSED, JOB_QUEUED, JOB_RUNNING
from app.services.output_assemble import assemble_output
from app.services.output_validate import OutputContractError, validate_headers, validate_output_rows

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "output"
OUTPUT_REQUIRES_COMPLETED_JOB = "Output generation requires a COMPLETED job."
_IN_FLIGHT_STATUSES = {JOB_QUEUED, JOB_RUNNING, JOB_PAUSED}


class OutputNotReadyError(RuntimeError):
    def __init__(
        self,
        message: str = OUTPUT_REQUIRES_COMPLETED_JOB,
        *,
        job_id: str | None = None,
        job_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.job_status = job_status


def default_output_path() -> Path:
    name = (
        "test_unihack_delivery_format.csv"
        if settings.TESTING
        else "unihack_delivery_format.csv"
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / name


def _assert_job_ready_for_output(job: ProcessingJobRecord) -> None:
    if job.status != JOB_COMPLETED:
        raise OutputNotReadyError(
            OUTPUT_REQUIRES_COMPLETED_JOB,
            job_id=job.id,
            job_status=job.status,
        )
    if job.total_products <= 0 or job.processed_products < job.total_products:
        raise OutputNotReadyError(
            OUTPUT_REQUIRES_COMPLETED_JOB,
            job_id=job.id,
            job_status=job.status,
        )


def resolve_output_job(db: Session, job_id: str | None = None) -> ProcessingJobRecord:
    if job_id:
        job = db.get(ProcessingJobRecord, job_id)
        if job is None:
            raise LookupError(f"Job {job_id} not found")
        _assert_job_ready_for_output(job)
        return job

    in_flight = (
        db.query(ProcessingJobRecord)
        .filter(ProcessingJobRecord.status.in_(list(_IN_FLIGHT_STATUSES)))
        .order_by(ProcessingJobRecord.created_at.desc())
        .first()
    )
    if in_flight is not None:
        raise OutputNotReadyError(
            OUTPUT_REQUIRES_COMPLETED_JOB,
            job_id=in_flight.id,
            job_status=in_flight.status,
        )

    job = (
        db.query(ProcessingJobRecord)
        .filter(ProcessingJobRecord.status == JOB_COMPLETED)
        .order_by(
            ProcessingJobRecord.completed_at.desc(),
            ProcessingJobRecord.created_at.desc(),
        )
        .first()
    )
    if job is None:
        raise OutputNotReadyError(OUTPUT_REQUIRES_COMPLETED_JOB)
    _assert_job_ready_for_output(job)
    return job


def _products_for_output(
    db: Session, job: ProcessingJobRecord | None
) -> list[ProductRecord]:
    if job is None:
        return db.query(ProductRecord).order_by(ProductRecord.id).all()
    item_ids = [
        row.product_id
        for row in db.query(ProcessingJobItem)
        .filter(ProcessingJobItem.job_id == job.id)
        .order_by(ProcessingJobItem.id)
        .all()
    ]
    if not item_ids:
        return []
    by_id = {
        row.id: row
        for row in db.query(ProductRecord).filter(ProductRecord.id.in_(item_ids)).all()
    }
    return [by_id[product_id] for product_id in item_ids if product_id in by_id]


def generate_output(
    db: Session,
    output_path: Path | None = None,
    *,
    job: ProcessingJobRecord | None = None,
) -> OutputGenerateResponse:
    path = output_path or default_output_path()
    products = _products_for_output(db, job)
    approved = 0
    partial = 0
    review_pending = 0
    skipped = 0
    rows: list[dict[str, str]] = []
    errors: list[str] = []

    for product in products:
        try:
            envelope = assemble_output(product.id, db)
        except Exception as exc:
            errors.append(f"Product {product.id}: {exc}")
            skipped += 1
            continue
        if envelope.eligibility_reason == "review_pending":
            review_pending += 1
            skipped += 1
            continue
        if not envelope.eligible_for_csv:
            skipped += 1
            continue
        if envelope.eligibility_reason == "approved":
            approved += 1
        elif envelope.eligibility_reason == "partial":
            partial += 1
        rows.append(envelope.output)

    if errors:
        return OutputGenerateResponse(
            status=STATUS_OUTPUT_FAILED,
            total_products=len(products),
            approved=approved,
            partial=partial,
            review_pending=review_pending,
            skipped=skipped,
            job_id=job.id if job is not None else None,
            errors=errors,
        )

    try:
        validate_headers(list(EXPECTED_OUTPUT_COLUMNS))
        validate_output_rows(rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(EXPECTED_OUTPUT_COLUMNS),
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)
        written_headers = []
        with path.open(newline="", encoding="utf-8") as handle:
            written_headers = list(csv.reader(handle))[0] if path.stat().st_size else []
        validate_headers(written_headers)
    except (OutputContractError, ValueError, OSError) as exc:
        if path.exists():
            path.unlink()
        return OutputGenerateResponse(
            status=STATUS_OUTPUT_FAILED,
            total_products=len(products),
            approved=approved,
            partial=partial,
            review_pending=review_pending,
            skipped=skipped,
            job_id=job.id if job is not None else None,
            errors=[str(exc)],
        )

    return OutputGenerateResponse(
        status=STATUS_COMPLETED,
        total_products=len(products),
        approved=approved,
        partial=partial,
        review_pending=review_pending,
        skipped=skipped,
        output_file=str(path),
        job_id=job.id if job is not None else None,
    )
