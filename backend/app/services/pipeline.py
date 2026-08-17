from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from app.agents.graph import (
    build_classification_graph,
    build_extract_graph,
    build_index_graph,
    build_normalize_graph,
    build_research_graph,
    build_resolution_graph,
    build_understanding_graph,
    build_validate_graph,
)
from app.agents.state import empty_product_state
from app.core.config import settings
from app.database.models import (
    EntityResolutionRecord,
    ProcessingErrorRecord,
    ProductAttributeRecord,
    ProductClassificationRecord,
    ProductDocumentRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
    ProductStageRun,
    ProductUnderstandingRecord,
    ProductValidationRecord,
)
from app.models.product import ProductStatus
from app.schemas.job import (
    ITEM_APPROVED,
    ITEM_FAILED,
    ITEM_PARTIAL,
    ITEM_REVIEW,
    PIPELINE_STAGES,
    STAGE_COMPLETED,
    STAGE_FAILED,
    STAGE_RUNNING,
    STAGE_SKIPPED,
)
from app.schemas.source import SOURCE_MANUFACTURER
from app.services.llm_retry import classify_llm_error, is_daily_token_limit
from app.services.review import (
    defer_llm_quota_exhausted,
    defer_source_fetch_failed,
    pending_reviews,
    sync_review_queue,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StageOutcome:
    status: str
    llm_calls: int = 0
    search_calls: int = 0
    documents_retrieved: int = 0
    chunks_retrieved: int = 0
    attributes_extracted: int = 0
    skipped: bool = False
    metrics: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    item_status: str
    duration_ms: float = 0.0
    llm_calls: int = 0
    search_calls: int = 0
    documents_retrieved: int = 0
    chunks_retrieved: int = 0
    attributes_extracted: int = 0
    error: str | None = None


class SourceFetchFailedError(RuntimeError):
    def __init__(self, source_url: str | None):
        self.source_url = source_url
        super().__init__(
            f"Manufacturer website fetch failed{f' for {source_url}' if source_url else ''}"
        )


def _invoke(build_graph, db: Session, product_id: int) -> dict:
    graph = build_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        raise RuntimeError(errors[0])
    return result


def _has_manufacturer_source(db: Session, product_id: int) -> bool:
    return (
        db.query(ProductSourceRecord)
        .filter(
            ProductSourceRecord.product_id == product_id,
            ProductSourceRecord.source_type == SOURCE_MANUFACTURER,
        )
        .first()
        is not None
    )


def stage_already_complete(db: Session, product_id: int, stage: str) -> bool:
    if stage == "understanding":
        return (
            db.query(ProductUnderstandingRecord)
            .filter(ProductUnderstandingRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "entity_resolution":
        return (
            db.query(EntityResolutionRecord)
            .filter(EntityResolutionRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "classification":
        return (
            db.query(ProductClassificationRecord)
            .filter(ProductClassificationRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "research":
        product = db.get(ProductRecord, product_id)
        if product and product.status == ProductStatus.NO_AUTHORITATIVE_SOURCE.value:
            return True
        return (
            db.query(ProductSourceRecord)
            .filter(ProductSourceRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "rag":
        if not _has_manufacturer_source(db, product_id):
            return True
        return (
            db.query(ProductDocumentRecord)
            .filter(ProductDocumentRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "extraction":
        if (
            db.query(ProductDocumentRecord)
            .filter(ProductDocumentRecord.product_id == product_id)
            .first()
            is None
        ):
            return True
        return (
            db.query(ProductAttributeRecord)
            .filter(ProductAttributeRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "normalization":
        if (
            db.query(ProductAttributeRecord)
            .filter(ProductAttributeRecord.product_id == product_id)
            .first()
            is None
        ):
            return True
        return (
            db.query(ProductNormalizedAttributeRecord)
            .filter(ProductNormalizedAttributeRecord.product_id == product_id)
            .first()
            is not None
        )
    if stage == "validation":
        if (
            db.query(ProductNormalizedAttributeRecord)
            .filter(ProductNormalizedAttributeRecord.product_id == product_id)
            .first()
            is None
        ):
            return True
        return (
            db.query(ProductValidationRecord)
            .filter(ProductValidationRecord.product_id == product_id)
            .first()
            is not None
        )
    return False


def _get_stage_run(db: Session, job_id: str, product_id: int, stage: str) -> ProductStageRun:
    row = (
        db.query(ProductStageRun)
        .filter(
            ProductStageRun.job_id == job_id,
            ProductStageRun.product_id == product_id,
            ProductStageRun.stage == stage,
        )
        .one_or_none()
    )
    if row is None:
        row = ProductStageRun(
            job_id=job_id,
            product_id=product_id,
            stage=stage,
            status="PENDING",
        )
        db.add(row)
        db.flush()
    return row


def _run_stage_body(db: Session, product_id: int, stage: str) -> StageOutcome:
    if stage == "understanding":
        _invoke(build_understanding_graph, db, product_id)
        return StageOutcome(status=STAGE_COMPLETED, llm_calls=1)
    if stage == "entity_resolution":
        _invoke(build_resolution_graph, db, product_id)
        return StageOutcome(status=STAGE_COMPLETED)
    if stage == "classification":
        _invoke(build_classification_graph, db, product_id)
        return StageOutcome(status=STAGE_COMPLETED)
    if stage == "research":
        result = _invoke(build_research_graph, db, product_id)
        metrics = result.get("research_metrics") or {}
        search_calls = int(metrics.get("queries_attempted") or 0)
        return StageOutcome(
            status=STAGE_COMPLETED,
            search_calls=search_calls,
            metrics=metrics,
        )
    if stage == "rag":
        if not _has_manufacturer_source(db, product_id):
            return StageOutcome(status=STAGE_SKIPPED, skipped=True)
        result = _invoke(build_index_graph, db, product_id)
        payload = result.get("index_result") or {}
        status = payload.get("status")
        if status == "FETCH_FAILED":
            raise SourceFetchFailedError(payload.get("source_url"))
        if status == "NO_MANUFACTURER_SOURCE":
            return StageOutcome(status=STAGE_SKIPPED, skipped=True)
        return StageOutcome(
            status=STAGE_COMPLETED,
            documents_retrieved=int(payload.get("documents_processed") or 0),
            chunks_retrieved=int(payload.get("chunks_created") or 0),
            metrics={
                "fetch_ms": float(payload.get("fetch_ms") or 0.0),
                "extract_ms": float(payload.get("extract_ms") or 0.0),
                "chunk_ms": float(payload.get("chunk_ms") or 0.0),
                "embedding_ms": float(payload.get("embedding_ms") or payload.get("embed_ms") or 0.0),
                "qdrant_ms": float(payload.get("qdrant_ms") or 0.0),
            },
        )
    if stage == "extraction":
        if (
            db.query(ProductDocumentRecord)
            .filter(ProductDocumentRecord.product_id == product_id)
            .first()
            is None
        ):
            return StageOutcome(status=STAGE_SKIPPED, skipped=True)
        result = _invoke(build_extract_graph, db, product_id)
        attributes = result.get("attributes") or []
        extracted = sum(1 for item in attributes if item.get("status") == "EXTRACTED")
        metrics = result.get("extraction_metrics") or {}
        return StageOutcome(
            status=STAGE_COMPLETED,
            llm_calls=int(metrics.get("llm_call_count") or 1),
            attributes_extracted=extracted,
            metrics=metrics,
        )
    if stage == "normalization":
        if (
            db.query(ProductAttributeRecord)
            .filter(ProductAttributeRecord.product_id == product_id)
            .first()
            is None
        ):
            return StageOutcome(status=STAGE_SKIPPED, skipped=True)
        _invoke(build_normalize_graph, db, product_id)
        return StageOutcome(status=STAGE_COMPLETED)
    if stage == "validation":
        if (
            db.query(ProductNormalizedAttributeRecord)
            .filter(ProductNormalizedAttributeRecord.product_id == product_id)
            .first()
            is None
        ):
            sync_review_queue(db, product_id)
            return StageOutcome(status=STAGE_SKIPPED, skipped=True)
        _invoke(build_validate_graph, db, product_id)
        return StageOutcome(status=STAGE_COMPLETED)
    raise RuntimeError(f"Unknown stage {stage}")


def _record_error(
    db: Session,
    job_id: str,
    product_id: int,
    stage: str,
    exc: Exception,
    retry_count: int,
    *,
    status: str = "FAILED",
) -> None:
    db.add(
        ProcessingErrorRecord(
            job_id=job_id,
            product_id=product_id,
            stage=stage,
            error_type=classify_llm_error(exc),
            error_message=str(exc),
            retry_count=retry_count,
            status=status,
        )
    )


def _is_llm_quota_exhausted(stage: str, exc: Exception) -> bool:
    return stage in {"understanding", "extraction"} and is_daily_token_limit(exc)


def _skip_remaining_stages(
    db: Session,
    job_id: str,
    product_id: int,
    after: str,
    *,
    reason: str,
) -> None:
    seen = False
    for stage in PIPELINE_STAGES:
        if stage == after:
            seen = True
            continue
        if not seen:
            continue
        run = _get_stage_run(db, job_id, product_id, stage)
        if run.status in {STAGE_COMPLETED, STAGE_SKIPPED}:
            continue
        run.status = STAGE_SKIPPED
        run.error_message = reason
        run.completed_at = _utcnow()


def _item_status_for_product(db: Session, product_id: int) -> str:
    product = db.get(ProductRecord, product_id)
    if product is None:
        return ITEM_FAILED
    if pending_reviews(db, product_id) or product.status == ProductStatus.REVIEW_REQUIRED.value:
        return ITEM_REVIEW
    if product.status == ProductStatus.FAIL.value:
        return ITEM_FAILED
    if product.status == ProductStatus.NO_AUTHORITATIVE_SOURCE.value:
        return ITEM_REVIEW
    if product.status in {ProductStatus.APPROVED.value, ProductStatus.VALIDATED.value}:
        return ITEM_APPROVED
    if product.status == ProductStatus.PARTIAL.value:
        return ITEM_PARTIAL
    return ITEM_PARTIAL if product.status not in {ProductStatus.INGESTED.value} else ITEM_FAILED


def process_product_pipeline(db: Session, job_id: str, product_id: int) -> PipelineResult:
    started = perf_counter()
    totals = PipelineResult(item_status=ITEM_FAILED)
    for stage in PIPELINE_STAGES:
        run = _get_stage_run(db, job_id, product_id, stage)
        if stage_already_complete(db, product_id, stage) and run.status != STAGE_FAILED:
            if run.status not in {STAGE_COMPLETED, STAGE_SKIPPED}:
                run.status = STAGE_SKIPPED
                run.completed_at = _utcnow()
            db.flush()
            continue
        attempt = 0
        last_error: Exception | None = None
        while attempt <= settings.JOB_MAX_RETRIES:
            run.status = STAGE_RUNNING
            run.started_at = run.started_at or _utcnow()
            db.flush()
            stage_started = perf_counter()
            try:
                outcome = _run_stage_body(db, product_id, stage)
                run.status = outcome.status
                run.duration_ms = round((perf_counter() - stage_started) * 1000, 3)
                run.llm_calls = outcome.llm_calls
                run.search_calls = outcome.search_calls
                run.retry_count = attempt
                run.error_message = None
                run.completed_at = _utcnow()
                if outcome.metrics:
                    run.metrics = dict(outcome.metrics)
                totals.llm_calls += outcome.llm_calls
                totals.search_calls += outcome.search_calls
                totals.documents_retrieved += outcome.documents_retrieved
                totals.chunks_retrieved += outcome.chunks_retrieved
                totals.attributes_extracted += outcome.attributes_extracted
                db.commit()
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                db.rollback()
                run = _get_stage_run(db, job_id, product_id, stage)
                run.status = STAGE_FAILED
                run.retry_count = attempt
                run.error_message = str(exc)
                run.duration_ms = round((perf_counter() - stage_started) * 1000, 3)
                run.completed_at = _utcnow()
                if _is_llm_quota_exhausted(stage, exc):
                    defer_llm_quota_exhausted(db, product_id, message=str(exc), stage=stage)
                    _record_error(
                        db, job_id, product_id, stage, exc, attempt, status="DEFERRED"
                    )
                    _skip_remaining_stages(
                        db,
                        job_id,
                        product_id,
                        after=stage,
                        reason=f"Skipped: LLM quota exhausted during {stage}",
                    )
                    db.commit()
                    totals.duration_ms = round((perf_counter() - started) * 1000, 3)
                    totals.item_status = _item_status_for_product(db, product_id)
                    totals.error = str(exc)
                    return totals
                if isinstance(exc, SourceFetchFailedError):
                    defer_source_fetch_failed(
                        db,
                        product_id,
                        message=str(exc),
                        source_url=exc.source_url,
                    )
                    _record_error(db, job_id, product_id, stage, exc, attempt, status="DEFERRED")
                    _skip_remaining_stages(
                        db,
                        job_id,
                        product_id,
                        after=stage,
                        reason="Skipped: manufacturer source fetch failed",
                    )
                    db.commit()
                    totals.duration_ms = round((perf_counter() - started) * 1000, 3)
                    totals.item_status = _item_status_for_product(db, product_id)
                    totals.error = str(exc)
                    return totals
                _record_error(db, job_id, product_id, stage, exc, attempt)
                db.commit()
                attempt += 1
        if last_error is not None:
            totals.duration_ms = round((perf_counter() - started) * 1000, 3)
            totals.item_status = ITEM_FAILED
            totals.error = str(last_error)
            return totals
    totals.duration_ms = round((perf_counter() - started) * 1000, 3)
    totals.item_status = _item_status_for_product(db, product_id)
    return totals


def product_stage_map(db: Session, job_id: str, product_id: int) -> dict[str, str]:
    rows = (
        db.query(ProductStageRun)
        .filter(
            ProductStageRun.job_id == job_id,
            ProductStageRun.product_id == product_id,
        )
        .all()
    )
    by_stage = {row.stage: row.status for row in rows}
    result = {}
    for stage in PIPELINE_STAGES:
        if stage in by_stage:
            result[stage] = by_stage[stage]
        elif stage_already_complete(db, product_id, stage):
            result[stage] = STAGE_COMPLETED
        else:
            result[stage] = "PENDING"
    return result
