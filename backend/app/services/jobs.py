from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.connection import SessionLocal
from app.database.models import (
    ProcessingErrorRecord,
    ProcessingJobItem,
    ProcessingJobRecord,
    ProductAttributeRecord,
    ProductClassificationRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductStageRun,
    ProductValidationRecord,
    ReviewQueueRecord,
)
from app.models.product import ProductStatus
from app.schemas.job import (
    ITEM_APPROVED,
    ITEM_FAILED,
    ITEM_PARTIAL,
    ITEM_PENDING,
    ITEM_REVIEW,
    ITEM_RUNNING,
    ITEM_SKIPPED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    STAGE_FAILED,
    STAGE_SKIPPED,
    JobCreateRequest,
    JobErrorOut,
    JobProductOut,
    JobProductStages,
    JobProfile,
    JobReport,
    JobStageStatus,
    JobSummary,
    ReviewBreakdown,
    StageTiming,
)
from app.schemas.review import STATUS_PENDING as REVIEW_PENDING
from app.schemas.validation import ISSUE_LOV_INVALID
from app.services.ingestion import ingest_csv
from app.services.output_generate import generate_output
from app.services.pipeline import process_product_pipeline, product_stage_map
from app.services.review import enrich_lov_diagnostics
from app.services.cache_store import clear_classification_cache

INPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "input"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _progress(job: ProcessingJobRecord) -> float:
    if not job.total_products:
        return 0.0
    return round(100.0 * job.processed_products / job.total_products, 1)


def throughput_products_per_minute(avg_processing_ms: float, worker_count: int) -> float:
    """Implied throughput from mean item duration, not wall clock since started_at."""
    if not avg_processing_ms:
        return 0.0
    return round(60000.0 / float(avg_processing_ms) * max(1, int(worker_count or 1)), 2)


def job_to_summary(job: ProcessingJobRecord) -> JobSummary:
    metrics = job.metrics or {}
    return JobSummary(
        job_id=job.id,
        status=job.status,
        dataset_name=job.dataset_name,
        total=job.total_products,
        processed=job.processed_products,
        approved=job.approved_products,
        partial=job.partial_products,
        review_required=job.review_products,
        failed=job.failed_products,
        progress=_progress(job),
        worker_count=job.worker_count,
        output_file=job.output_file,
        avg_processing_ms=float(metrics.get("avg_processing_ms") or 0.0),
        products_per_minute=float(metrics.get("products_per_minute") or 0.0),
        success_rate=float(metrics.get("success_rate") or 0.0),
        evidence_coverage=float(metrics.get("evidence_coverage") or 0.0),
        completeness=float(metrics.get("completeness") or 0.0),
        started_at=_iso(job.started_at),
        completed_at=_iso(job.completed_at),
        created_at=_iso(job.created_at),
    )


def job_stage_timings(db: Session, job_id: str) -> dict[str, float]:
    rows = db.query(ProductStageRun).filter(ProductStageRun.job_id == job_id).all()
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if row.duration_ms:
            buckets.setdefault(row.stage, []).append(row.duration_ms)
    return {
        stage: round(sum(values) / len(values) / 1000.0, 3)
        for stage, values in buckets.items()
    }


def job_review_breakdown(db: Session, job_id: str) -> dict[str, int]:
    product_ids = [
        item.product_id
        for item in db.query(ProcessingJobItem).filter(ProcessingJobItem.job_id == job_id).all()
    ]
    if not product_ids:
        return {}
    rows = (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id.in_(product_ids),
            ReviewQueueRecord.status.in_([REVIEW_PENDING, "IN_REVIEW"]),
        )
        .all()
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.issue_type] = counts.get(row.issue_type, 0) + 1
    return counts


def enrich_job_summary(db: Session, summary: JobSummary) -> JobSummary:
    summary.stage_timings = job_stage_timings(db, summary.job_id)
    summary.review_breakdown = job_review_breakdown(db, summary.job_id)
    return summary


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _median(values: list[float]) -> float:
    return _percentile(values, 50.0)


def _breakdown_averages(items: list[ProductStageRun]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for item in items:
        if not item.duration_ms:
            continue
        metrics = getattr(item, "metrics", None) or {}
        for key, value in metrics.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            buckets.setdefault(key, []).append(number)
    return {
        key: round(sum(values) / len(values), 1)
        for key, values in buckets.items()
        if values
    }


def build_stage_timing(stage: str, items: list[ProductStageRun]) -> StageTiming:
    """Percentiles use timed executions only. count_total includes skips."""
    timed = [item.duration_ms for item in items if item.duration_ms]
    skipped = sum(1 for item in items if item.status == STAGE_SKIPPED)
    failed = sum(1 for item in items if item.status == STAGE_FAILED)
    avg_ms = round(sum(timed) / len(timed), 1) if timed else 0.0
    return StageTiming(
        stage=stage,
        count=len(items),
        count_total=len(items),
        count_timed=len(timed),
        count_skipped=skipped,
        count_failed=failed,
        failed=failed,
        avg_ms=avg_ms,
        p50_ms=round(_percentile(timed, 50), 1),
        p95_ms=round(_percentile(timed, 95), 1),
        p99_ms=round(_percentile(timed, 99), 1),
        max_ms=round(max(timed), 1) if timed else 0.0,
        avg_s=round(avg_ms / 1000.0, 3),
        breakdown=_breakdown_averages(items),
    )


def job_profile(db: Session, job: ProcessingJobRecord) -> JobProfile:
    rows = db.query(ProductStageRun).filter(ProductStageRun.job_id == job.id).all()
    by_stage: dict[str, list[ProductStageRun]] = {}
    for row in rows:
        by_stage.setdefault(row.stage, []).append(row)
    stages = [build_stage_timing(stage, items) for stage, items in by_stage.items()]
    stages.sort(key=lambda item: item.avg_ms, reverse=True)
    sample = next(
        (
            item.product_id
            for item in db.query(ProcessingJobItem)
            .filter(
                ProcessingJobItem.job_id == job.id,
                ProcessingJobItem.status != ITEM_PENDING,
            )
            .order_by(ProcessingJobItem.id)
            .all()
            if item.status != ITEM_RUNNING
        ),
        None,
    )
    sample_stages: dict[str, float] = {}
    if sample is not None:
        for row in rows:
            if row.product_id == sample and row.duration_ms:
                sample_stages[row.stage] = round(row.duration_ms / 1000.0, 3)
    return JobProfile(
        job_id=job.id,
        total=job.total_products,
        processed=job.processed_products,
        avg_processing_ms=float((job.metrics or {}).get("avg_processing_ms") or 0.0),
        stages=stages,
        sample_product_id=sample,
        sample_stages=sample_stages,
    )


def job_review_stats(db: Session, job: ProcessingJobRecord, *, details: bool = False) -> ReviewBreakdown:
    product_ids = [
        item.product_id
        for item in db.query(ProcessingJobItem).filter(ProcessingJobItem.job_id == job.id).all()
    ]
    if not product_ids:
        return ReviewBreakdown(job_id=job.id)
    rows = (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id.in_(product_ids),
            ReviewQueueRecord.status.in_([REVIEW_PENDING, "IN_REVIEW"]),
        )
        .all()
    )
    by_issue: dict[str, int] = {}
    products_by_issue: dict[str, set[int]] = {}
    by_attribute: dict[str, int] = {}
    lov_by_attribute: dict[str, int] = {}
    detail_rows: list[dict] = []
    for row in rows:
        by_issue[row.issue_type] = by_issue.get(row.issue_type, 0) + 1
        products_by_issue.setdefault(row.issue_type, set()).add(row.product_id)
        if row.attribute:
            by_attribute[row.attribute] = by_attribute.get(row.attribute, 0) + 1
        if row.issue_type == "LOV_INVALID" and row.attribute:
            lov_by_attribute[row.attribute] = lov_by_attribute.get(row.attribute, 0) + 1
        if details and row.issue_type == "LOV_INVALID":
            product = db.get(ProductRecord, row.product_id)
            diag = enrich_lov_diagnostics(db, row)
            detail_rows.append(
                {
                    "product_id": row.product_id,
                    "mpn": product.mpn if product else None,
                    "attribute": row.attribute,
                    "raw_value": diag.get("raw_value"),
                    "normalized_value": diag.get("normalized_value") or row.current_value,
                    "allowed_values": diag.get("allowed_values") or [],
                    "source": diag.get("source"),
                    "evidence_text": diag.get("evidence_text"),
                    "reason": row.reason,
                }
            )
    return ReviewBreakdown(
        job_id=job.id,
        total_items=len(rows),
        total_products=len({row.product_id for row in rows}),
        by_issue_type=by_issue,
        products_by_issue_type={key: len(value) for key, value in products_by_issue.items()},
        by_attribute=by_attribute,
        lov_invalid_by_attribute=lov_by_attribute,
        details=detail_rows,
    )


def format_job_report(job: ProcessingJobRecord) -> str:
    summary = job_to_summary(job)
    avg_s = (summary.avg_processing_ms / 1000.0) if summary.avg_processing_ms else 0.0
    return (
        "┌──────────────────────────────┐\n"
        "│      JOB SUMMARY             │\n"
        "├──────────────────────────────┤\n"
        f"│ Products           {summary.total:>8}  │\n"
        f"│ Approved           {summary.approved:>8}  │\n"
        f"│ Partial            {summary.partial:>8}  │\n"
        f"│ Human Review       {summary.review_required:>8}  │\n"
        f"│ Failed             {summary.failed:>8}  │\n"
        f"│ Success Rate       {summary.success_rate * 100:>7.1f}%  │\n"
        f"│ Avg Processing     {avg_s:>7.2f}s  │\n"
        f"│ Evidence Coverage  {summary.evidence_coverage * 100:>7.1f}%  │\n"
        "└──────────────────────────────┘"
    )


def job_report(job: ProcessingJobRecord) -> JobReport:
    summary = job_to_summary(job)
    return JobReport(
        job_id=job.id,
        products=summary.total,
        approved=summary.approved,
        partial=summary.partial,
        human_review=summary.review_required,
        failed=summary.failed,
        success_rate=summary.success_rate,
        avg_processing_ms=summary.avg_processing_ms,
        products_per_minute=summary.products_per_minute,
        evidence_coverage=summary.evidence_coverage,
        completeness=summary.completeness,
        output_file=summary.output_file,
        summary=format_job_report(job),
    )


def _eligible_products(db: Session, product_ids: list[int] | None, limit: int | None) -> list[ProductRecord]:
    excluded = {ProductStatus.INVALID.value}
    if product_ids:
        rows = (
            db.query(ProductRecord)
            .filter(ProductRecord.id.in_(product_ids))
            .all()
        )
        by_id = {row.id: row for row in rows}
        ordered = [by_id[pid] for pid in product_ids if pid in by_id]
        # Explicit intake (single product / re-upload) must still be processable
        # even when the MPN already exists and was marked DUPLICATE_CANDIDATE.
        eligible = [row for row in ordered if row.status not in excluded]
    else:
        excluded.add(ProductStatus.DUPLICATE_CANDIDATE.value)
        rows = db.query(ProductRecord).order_by(ProductRecord.id).all()
        eligible = [row for row in rows if row.status not in excluded]
    if limit:
        eligible = eligible[:limit]
    return eligible


def _ingest_input_file(db: Session, filename: str) -> None:
    safe_name = Path(filename).name
    path = (INPUT_DIR / safe_name).resolve()
    if path.parent != INPUT_DIR.resolve() or not path.exists():
        raise FileNotFoundError(f"Input file not found: {safe_name}")
    ingest_csv(path.read_bytes(), safe_name, db)


DEFAULT_INPUT_FILE = "Unihack_Sample_Dataset_Input.csv"


def create_job(db: Session, request: JobCreateRequest) -> ProcessingJobRecord:
    existing = db.query(ProductRecord).count()
    input_file = request.input_file
    if not input_file and existing == 0 and not settings.TESTING:
        candidate = INPUT_DIR / DEFAULT_INPUT_FILE
        if candidate.exists():
            input_file = DEFAULT_INPUT_FILE
    if input_file and (request.force_ingest or existing == 0):
        _ingest_input_file(db, input_file)
    products = _eligible_products(db, request.product_ids, request.limit)
    if not products:
        raise ValueError("No eligible products to process")
    if input_file:
        dataset_name = Path(input_file).name
    elif len(products) == 1:
        dataset_name = products[0].mpn
    else:
        dataset_name = "existing-products"
    workers = request.worker_count or (1 if settings.TESTING else settings.JOB_WORKERS)
    job = ProcessingJobRecord(
        id=str(uuid.uuid4()),
        dataset_name=dataset_name,
        status=JOB_QUEUED,
        total_products=len(products),
        worker_count=max(1, workers),
        generate_output=request.generate_output,
        metrics={},
        created_at=_utcnow(),
    )
    db.add(job)
    db.flush()
    for product in products:
        db.add(
            ProcessingJobItem(
                job_id=job.id,
                product_id=product.id,
                status=ITEM_PENDING,
            )
        )
    db.commit()
    db.refresh(job)
    return job


def refresh_wrong_classpath_items(db: Session, job: ProcessingJobRecord) -> int:
    """Re-run classification→extraction when the classpath/template is untrustworthy.

    Product Type LOV_INVALID is often a wrong template, not a missing alias.
    Legacy `keyword` matches scored department/class names (e.g. Abrasives) and
    collapsed every abrasive onto Sanding Belts. Those must be reclassified.
    """
    clear_classification_cache()
    product_ids = [
        item.product_id
        for item in db.query(ProcessingJobItem).filter(ProcessingJobItem.job_id == job.id).all()
    ]
    if not product_ids:
        return 0
    type_lov_ids = {
        row.product_id
        for row in db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id.in_(product_ids),
            ReviewQueueRecord.issue_type == ISSUE_LOV_INVALID,
            ReviewQueueRecord.attribute == "Product Type",
            ReviewQueueRecord.status.in_([REVIEW_PENDING, "IN_REVIEW"]),
        )
        .all()
    }
    keyword_ids = {
        row.product_id
        for row in db.query(ProductClassificationRecord)
        .filter(
            ProductClassificationRecord.product_id.in_(product_ids),
            ProductClassificationRecord.method == "keyword",
        )
        .all()
    }
    target_ids = type_lov_ids | keyword_ids
    if not target_ids:
        return 0
    db.query(ProductValidationRecord).filter(
        ProductValidationRecord.product_id.in_(target_ids)
    ).delete(synchronize_session=False)
    db.query(ProductNormalizedAttributeRecord).filter(
        ProductNormalizedAttributeRecord.product_id.in_(target_ids)
    ).delete(synchronize_session=False)
    db.query(ProductAttributeRecord).filter(
        ProductAttributeRecord.product_id.in_(target_ids)
    ).delete(synchronize_session=False)
    db.query(ProductClassificationRecord).filter(
        ProductClassificationRecord.product_id.in_(target_ids)
    ).delete(synchronize_session=False)
    runs = (
        db.query(ProductStageRun)
        .filter(
            ProductStageRun.job_id == job.id,
            ProductStageRun.product_id.in_(target_ids),
            ProductStageRun.stage.in_(
                ["classification", "extraction", "normalization", "validation"]
            ),
        )
        .all()
    )
    for run in runs:
        run.status = "PENDING"
        run.error_message = None
        run.completed_at = None
        run.duration_ms = 0.0
    items = (
        db.query(ProcessingJobItem)
        .filter(
            ProcessingJobItem.job_id == job.id,
            ProcessingJobItem.product_id.in_(target_ids),
            ProcessingJobItem.status.in_(
                [ITEM_REVIEW, ITEM_PARTIAL, ITEM_APPROVED, ITEM_FAILED]
            ),
        )
        .all()
    )
    for item in items:
        item.status = ITEM_PENDING
        item.completed_at = None
    db.flush()
    return len(target_ids)


def refresh_stale_lov_items(db: Session, job: ProcessingJobRecord) -> int:
    """Re-run normalize+validate for products with pending LOV_INVALID reviews.

    Does not re-extract or re-research. Canonical LOV matching is deterministic, so
    this is how a mapping fix applies to products already in HITL.
    """
    product_ids = [
        item.product_id
        for item in db.query(ProcessingJobItem).filter(ProcessingJobItem.job_id == job.id).all()
    ]
    if not product_ids:
        return 0
    lov_ids = {
        row.product_id
        for row in db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id.in_(product_ids),
            ReviewQueueRecord.issue_type == ISSUE_LOV_INVALID,
            ReviewQueueRecord.status.in_([REVIEW_PENDING, "IN_REVIEW"]),
        )
        .all()
    }
    classified_ids = {
        row.product_id
        for row in db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id.in_(product_ids))
        .all()
    }
    lov_ids &= classified_ids
    if not lov_ids:
        return 0
    db.query(ProductValidationRecord).filter(
        ProductValidationRecord.product_id.in_(lov_ids)
    ).delete(synchronize_session=False)
    db.query(ProductNormalizedAttributeRecord).filter(
        ProductNormalizedAttributeRecord.product_id.in_(lov_ids)
    ).delete(synchronize_session=False)
    runs = (
        db.query(ProductStageRun)
        .filter(
            ProductStageRun.job_id == job.id,
            ProductStageRun.product_id.in_(lov_ids),
            ProductStageRun.stage.in_(["normalization", "validation"]),
        )
        .all()
    )
    for run in runs:
        run.status = "PENDING"
        run.error_message = None
        run.completed_at = None
        run.duration_ms = 0.0
    items = (
        db.query(ProcessingJobItem)
        .filter(
            ProcessingJobItem.job_id == job.id,
            ProcessingJobItem.product_id.in_(lov_ids),
            ProcessingJobItem.status.in_([ITEM_REVIEW, ITEM_PARTIAL, ITEM_APPROVED]),
        )
        .all()
    )
    for item in items:
        item.status = ITEM_PENDING
        item.completed_at = None
    db.flush()
    return len(lov_ids)


def _refresh_job_counts(db: Session, job: ProcessingJobRecord) -> None:
    items = db.query(ProcessingJobItem).filter(ProcessingJobItem.job_id == job.id).all()
    terminal = {ITEM_APPROVED, ITEM_PARTIAL, ITEM_REVIEW, ITEM_FAILED, ITEM_SKIPPED}
    job.processed_products = sum(1 for item in items if item.status in terminal)
    job.approved_products = sum(1 for item in items if item.status == ITEM_APPROVED)
    job.partial_products = sum(1 for item in items if item.status == ITEM_PARTIAL)
    job.review_products = sum(1 for item in items if item.status == ITEM_REVIEW)
    job.failed_products = sum(1 for item in items if item.status == ITEM_FAILED)
    durations = [item.duration_ms for item in items if item.duration_ms]
    validations = (
        db.query(ProductValidationRecord)
        .filter(ProductValidationRecord.product_id.in_([item.product_id for item in items] or [0]))
        .all()
    )
    coverage = [row.evidence_coverage for row in validations]
    completeness = [row.completeness_score for row in validations]
    processed = job.processed_products
    success = job.approved_products + job.partial_products + job.review_products
    avg_ms = round(sum(durations) / len(durations), 3) if durations else 0.0
    products_per_minute = throughput_products_per_minute(avg_ms, job.worker_count)
    job.metrics = {
        "avg_processing_ms": avg_ms,
        "products_per_minute": products_per_minute,
        "success_rate": round(success / processed, 4) if processed else 0.0,
        "evidence_coverage": round(sum(coverage) / len(coverage), 4) if coverage else 0.0,
        "completeness": round(sum(completeness) / len(completeness), 4) if completeness else 0.0,
    }


def _process_item(db: Session, job_id: str, product_id: int) -> None:
    item = (
        db.query(ProcessingJobItem)
        .filter(
            ProcessingJobItem.job_id == job_id,
            ProcessingJobItem.product_id == product_id,
        )
        .one()
    )
    item.status = ITEM_RUNNING
    db.commit()
    result = process_product_pipeline(db, job_id, product_id)
    item = (
        db.query(ProcessingJobItem)
        .filter(
            ProcessingJobItem.job_id == job_id,
            ProcessingJobItem.product_id == product_id,
        )
        .one()
    )
    item.status = result.item_status
    item.duration_ms = result.duration_ms
    item.llm_calls = result.llm_calls
    item.search_calls = result.search_calls
    item.documents_retrieved = result.documents_retrieved
    item.chunks_retrieved = result.chunks_retrieved
    item.attributes_extracted = result.attributes_extracted
    item.completed_at = _utcnow()
    db.commit()


def _process_item_isolated(job_id: str, product_id: int) -> None:
    db = SessionLocal()
    try:
        _process_item(db, job_id, product_id)
    except Exception as exc:
        db.rollback()
        item = (
            db.query(ProcessingJobItem)
            .filter(
                ProcessingJobItem.job_id == job_id,
                ProcessingJobItem.product_id == product_id,
            )
            .one_or_none()
        )
        if item is not None:
            item.status = ITEM_FAILED
            item.completed_at = _utcnow()
        db.add(
            ProcessingErrorRecord(
                job_id=job_id,
                product_id=product_id,
                stage="pipeline",
                error_type=type(exc).__name__,
                error_message=str(exc),
                status="FAILED",
            )
        )
        db.commit()
    finally:
        db.close()


def run_processing_job(db: Session, job_id: str) -> ProcessingJobRecord:
    job = db.get(ProcessingJobRecord, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    job.status = JOB_RUNNING
    job.started_at = job.started_at or _utcnow()
    refresh_wrong_classpath_items(db, job)
    refresh_stale_lov_items(db, job)
    db.commit()

    items = (
        db.query(ProcessingJobItem)
        .filter(
            ProcessingJobItem.job_id == job_id,
            ProcessingJobItem.status.in_([ITEM_PENDING, ITEM_FAILED, ITEM_RUNNING]),
        )
        .order_by(ProcessingJobItem.id)
        .all()
    )
    product_ids = [item.product_id for item in items]
    workers = 1 if settings.TESTING else max(1, job.worker_count)

    try:
        if workers == 1:
            for product_id in product_ids:
                try:
                    _process_item(db, job_id, product_id)
                except Exception as exc:
                    db.rollback()
                    item = (
                        db.query(ProcessingJobItem)
                        .filter(
                            ProcessingJobItem.job_id == job_id,
                            ProcessingJobItem.product_id == product_id,
                        )
                        .one_or_none()
                    )
                    if item is not None:
                        item.status = ITEM_FAILED
                        item.completed_at = _utcnow()
                    db.add(
                        ProcessingErrorRecord(
                            job_id=job_id,
                            product_id=product_id,
                            stage="pipeline",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            status="FAILED",
                        )
                    )
                    db.commit()
                job = db.get(ProcessingJobRecord, job_id)
                if job is not None:
                    _refresh_job_counts(db, job)
                    db.commit()
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_process_item_isolated, job_id, product_id)
                    for product_id in product_ids
                ]
                for future in as_completed(futures):
                    future.result()
                    job = db.get(ProcessingJobRecord, job_id)
                    if job is not None:
                        _refresh_job_counts(db, job)
                        db.commit()
        job = db.get(ProcessingJobRecord, job_id)
        if job is not None:
            job.status = JOB_COMPLETED
            job.completed_at = _utcnow()
            _refresh_job_counts(db, job)
            db.commit()
        job = db.get(ProcessingJobRecord, job_id)
        if job is not None and job.generate_output:
            output = generate_output(db, job=job)
            job.output_file = output.output_file
            db.commit()
    except Exception:
        job = db.get(ProcessingJobRecord, job_id)
        if job is not None:
            job.status = JOB_FAILED
            job.completed_at = _utcnow()
            _refresh_job_counts(db, job)
            db.commit()
        raise
    return db.get(ProcessingJobRecord, job_id)


def retry_product(db: Session, job_id: str, product_id: int) -> ProcessingJobRecord:
    item = (
        db.query(ProcessingJobItem)
        .filter(
            ProcessingJobItem.job_id == job_id,
            ProcessingJobItem.product_id == product_id,
        )
        .one_or_none()
    )
    if item is None:
        raise LookupError(f"Product {product_id} is not in job {job_id}")
    item.status = ITEM_PENDING
    item.completed_at = None
    failed_runs = (
        db.query(ProductStageRun)
        .filter(
            ProductStageRun.job_id == job_id,
            ProductStageRun.product_id == product_id,
            ProductStageRun.status == "FAILED",
        )
        .all()
    )
    for run in failed_runs:
        run.status = "PENDING"
        run.error_message = None
    db.commit()
    _process_item(db, job_id, product_id)
    job = db.get(ProcessingJobRecord, job_id)
    if job is not None:
        _refresh_job_counts(db, job)
        db.commit()
    return job


def list_jobs(db: Session) -> list[ProcessingJobRecord]:
    return (
        db.query(ProcessingJobRecord)
        .order_by(ProcessingJobRecord.created_at.desc())
        .all()
    )


def get_job(db: Session, job_id: str) -> ProcessingJobRecord:
    job = db.get(ProcessingJobRecord, job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")
    return job


def list_job_products(
    db: Session, job_id: str, skip: int = 0, limit: int = 100
) -> tuple[int, list[JobProductOut]]:
    query = (
        db.query(ProcessingJobItem, ProductRecord)
        .join(ProductRecord, ProductRecord.id == ProcessingJobItem.product_id)
        .filter(ProcessingJobItem.job_id == job_id)
    )
    total = query.count()
    rows = (
        query.order_by(ProcessingJobItem.id)
        .offset(max(0, skip))
        .limit(max(1, min(limit, 500)))
        .all()
    )
    items = [
        JobProductOut(
            product_id=product.id,
            mpn=product.mpn,
            description=product.description,
            item_status=item.status,
            product_status=product.status,
            brand=product.e1_brand,
            manufacturer=product.manufacturer,
        )
        for item, product in rows
    ]
    return total, items


def list_job_errors(db: Session, job_id: str) -> list[JobErrorOut]:
    rows = (
        db.query(ProcessingErrorRecord)
        .filter(ProcessingErrorRecord.job_id == job_id)
        .order_by(ProcessingErrorRecord.id)
        .all()
    )
    return [
        JobErrorOut(
            id=row.id,
            product_id=row.product_id,
            stage=row.stage,
            error_type=row.error_type,
            error_message=row.error_message,
            retry_count=row.retry_count,
            status=row.status,
            created_at=_iso(row.created_at),
        )
        for row in rows
    ]


def get_product_stages(db: Session, job_id: str, product_id: int) -> JobProductStages:
    rows = (
        db.query(ProductStageRun)
        .filter(
            ProductStageRun.job_id == job_id,
            ProductStageRun.product_id == product_id,
        )
        .all()
    )
    details = [
        JobStageStatus(
            stage=row.stage,
            status=row.status,
            duration_ms=row.duration_ms,
            retry_count=row.retry_count,
            llm_calls=row.llm_calls,
            search_calls=row.search_calls,
            error_message=row.error_message,
            metrics=dict(getattr(row, "metrics", None) or {}),
        )
        for row in rows
    ]
    return JobProductStages(
        product_id=product_id,
        stages=product_stage_map(db, job_id, product_id),
        details=details,
    )
