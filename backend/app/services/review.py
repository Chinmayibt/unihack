from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import (
    EntityResolutionRecord,
    ProductClassificationRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
    ProductUnderstandingRecord,
    ProductValidationRecord,
    ReviewQueueRecord,
)
from app.models.product import ProductStatus
from app.schemas.normalized_attribute import (
    CONFLICT,
    INPUT_SOURCED,
    MANUFACTURER_SUPPORTED,
    NOT_FOUND,
    SOURCE_INPUT,
    SOURCE_MANUFACTURER,
    STATUS_NORMALIZED,
    STATUS_NOT_FOUND,
)
from app.schemas.review import (
    DECISION_APPROVE_CURRENT,
    DECISION_MARK_UNKNOWN,
    DECISION_REJECT_ATTRIBUTE,
    DECISION_SELECT_CANDIDATE,
    ISSUE_BRAND_CONFLICT,
    ISSUE_LLM_QUOTA_EXHAUSTED,
    ISSUE_LOW_CLASSIFICATION_CONFIDENCE,
    ISSUE_NO_AUTHORITATIVE_SOURCE,
    ISSUE_SOURCE_FETCH_FAILED,
    ReviewCandidate,
    ReviewDetail,
    ReviewProductSummary,
    ReviewQueueItem,
    ReviewQueueList,
    ReviewResolveRequest,
    ReviewResolveResponse,
    ReviewSourceSummary,
    ProcessResponse,
    STATUS_APPROVED,
    STATUS_IN_REVIEW,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_UNKNOWN,
)
from app.schemas.validation import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    ValidationResult,
)
from app.services.entity_resolution import _real_source_brand
from app.services.ingestion import is_missing_brand_value
from app.services.standards import allowed_lov_values
from app.services.value_normalize import comparable_key, normalize_raw


OPEN_STATUSES = {STATUS_PENDING, STATUS_IN_REVIEW}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ReviewDraft:
    product_id: int
    issue_type: str
    severity: str
    reason: str
    attribute: str | None = None
    current_value: str | None = None
    candidate_values: list = field(default_factory=list)
    ai_value: str | None = None
    confidence: float | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    allowed_values: list = field(default_factory=list)
    source: str | None = None
    evidence_text: str | None = None


def delete_pending_reviews(db: Session, product_id: int) -> None:
    db.query(ReviewQueueRecord).filter(
        ReviewQueueRecord.product_id == product_id,
        ReviewQueueRecord.status.in_(list(OPEN_STATUSES)),
    ).delete(synchronize_session=False)


def defer_llm_quota_exhausted(
    db: Session,
    product_id: int,
    *,
    message: str,
    stage: str = "understanding",
) -> ReviewQueueRecord | None:
    """Park a product in review when Groq TPD is exhausted. Do not fabricate understanding."""
    product = db.get(ProductRecord, product_id)
    if product is None:
        return None
    product.status = ProductStatus.REVIEW_REQUIRED.value
    product.updated_at = _utcnow()
    reason = (
        message
        or "Groq daily token quota exhausted. Understanding was not generated."
    )
    existing = (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product_id,
            ReviewQueueRecord.issue_type == ISSUE_LLM_QUOTA_EXHAUSTED,
            ReviewQueueRecord.status.in_(list(OPEN_STATUSES)),
        )
        .one_or_none()
    )
    if existing is not None:
        existing.reason = reason
        existing.diagnostics = {"stage": stage, "quota": "TPD"}
        return existing
    row = ReviewQueueRecord(
        product_id=product_id,
        issue_type=ISSUE_LLM_QUOTA_EXHAUSTED,
        severity=SEVERITY_HIGH,
        attribute=stage.title(),
        reason=reason,
        status=STATUS_PENDING,
        diagnostics={"stage": stage, "quota": "TPD"},
    )
    db.add(row)
    db.flush()
    return row


def defer_source_fetch_failed(
    db: Session,
    product_id: int,
    *,
    message: str,
    source_url: str | None = None,
) -> ReviewQueueRecord | None:
    """Park unavailable external evidence in review without creating a document."""
    product = db.get(ProductRecord, product_id)
    if product is None:
        return None
    product.status = ProductStatus.REVIEW_REQUIRED.value
    product.updated_at = _utcnow()
    reason = message or "The manufacturer source could not be fetched."
    existing = (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product_id,
            ReviewQueueRecord.issue_type == ISSUE_SOURCE_FETCH_FAILED,
            ReviewQueueRecord.status.in_(list(OPEN_STATUSES)),
        )
        .one_or_none()
    )
    diagnostics = {"source_url": source_url} if source_url else {}
    if existing is not None:
        existing.reason = reason
        existing.diagnostics = diagnostics
        return existing
    row = ReviewQueueRecord(
        product_id=product_id,
        issue_type=ISSUE_SOURCE_FETCH_FAILED,
        severity=SEVERITY_HIGH,
        attribute="Manufacturer Source",
        reason=reason,
        status=STATUS_PENDING,
        diagnostics=diagnostics,
    )
    db.add(row)
    db.flush()
    return row


def pending_reviews(db: Session, product_id: int) -> list[ReviewQueueRecord]:
    return (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product_id,
            ReviewQueueRecord.status.in_(list(OPEN_STATUSES)),
        )
        .order_by(ReviewQueueRecord.id)
        .all()
    )


def _as_candidate_dicts(values: list) -> list[dict]:
    rows: list[dict] = []
    for item in values or []:
        if isinstance(item, dict):
            value = item.get("value")
            if value is None:
                continue
            rows.append(
                {
                    "value": str(value),
                    "source": item.get("source"),
                    "evidence_text": item.get("evidence_text"),
                    "source_id": item.get("source_id"),
                    "authority": item.get("authority"),
                }
            )
            continue
        text = str(item).strip()
        if text:
            rows.append({"value": text})
    return rows


def _candidate_strings(values: list) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in _as_candidate_dicts(values):
        value = item["value"]
        key = value.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _issue_key(issue_type: str, attribute: str | None) -> tuple[str, str]:
    return (issue_type, (attribute or "").strip().lower())


def _current_from_attribute(row: ProductNormalizedAttributeRecord | None) -> str | None:
    if row is None:
        return None
    if row.agreement == CONFLICT:
        for candidate in row.candidates or []:
            if isinstance(candidate, dict) and candidate.get("source") == SOURCE_INPUT:
                return candidate.get("value") or row.raw_value
        return row.raw_value
    return row.normalized_value or row.raw_value


def _drafts_from_validation(
    product_id: int,
    validation: ValidationResult,
    attributes: dict[str, ProductNormalizedAttributeRecord],
) -> list[ReviewDraft]:
    drafts: list[ReviewDraft] = []
    for issue in validation.issues:
        if not issue.requires_review:
            continue
        row = attributes.get(issue.attribute) if issue.attribute else None
        current = _current_from_attribute(row)
        candidates = list(row.candidates or []) if row else []
        if issue.allowed_values:
            candidates = list(candidates) + [
                {"value": value, "source": "ALLOWED_LOV"} for value in issue.allowed_values
            ]
        drafts.append(
            ReviewDraft(
                product_id=product_id,
                issue_type=issue.issue_type,
                severity=issue.severity,
                attribute=issue.attribute,
                current_value=current,
                candidate_values=candidates,
                reason=issue.message,
                ai_value=current or (row.raw_value if row else None),
                raw_value=issue.raw_value or (row.raw_value if row else None),
                normalized_value=issue.normalized_value
                or (row.normalized_value if row else None),
                allowed_values=list(issue.allowed_values or []),
                source=issue.source or (row.selected_source if row else None),
                evidence_text=issue.evidence_text or (row.evidence_text if row else None),
            )
        )
    return drafts


def _brand_conflict_draft(db: Session, product: ProductRecord) -> ReviewDraft | None:
    understanding = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product.id)
        .one_or_none()
    )
    brand_row = (
        db.query(EntityResolutionRecord)
        .filter(
            EntityResolutionRecord.product_id == product.id,
            EntityResolutionRecord.entity_type == "brand",
        )
        .one_or_none()
    )
    raw = {
        "e1_brand": product.e1_brand,
        "unilog_brand": product.unilog_brand,
        "dib_brand": product.dib_brand,
    }
    source_brand = _real_source_brand(raw)
    description_brand = understanding.brand_candidate if understanding else None
    if description_brand and is_missing_brand_value(description_brand):
        description_brand = None

    two_real_names = bool(
        source_brand
        and description_brand
        and source_brand.strip().lower() != description_brand.strip().lower()
    )
    method_conflict = bool(brand_row and brand_row.method == "brand_conflict")
    if not two_real_names and not method_conflict:
        return None
    candidates = [item for item in (source_brand, description_brand) if item]
    if not candidates and brand_row and brand_row.candidate:
        candidates = [brand_row.candidate]
    return ReviewDraft(
        product_id=product.id,
        issue_type=ISSUE_BRAND_CONFLICT,
        severity=SEVERITY_HIGH,
        attribute="Brand",
        current_value=source_brand or (brand_row.candidate if brand_row else None),
        candidate_values=candidates,
        reason="Input brand and manufacturer/description brand disagree.",
        ai_value=description_brand or source_brand,
    )


def _classification_draft(db: Session, product: ProductRecord) -> ReviewDraft | None:
    record = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product.id)
        .one_or_none()
    )
    if record is None:
        return None
    if record.confidence >= settings.CLASSIFY_REVIEW_CONFIDENCE:
        return None
    return ReviewDraft(
        product_id=product.id,
        issue_type=ISSUE_LOW_CLASSIFICATION_CONFIDENCE,
        severity=SEVERITY_MEDIUM,
        attribute="Classification",
        current_value=record.classpath,
        candidate_values=[record.classpath] if record.classpath else [],
        reason=f"Classification confidence {record.confidence:.2f} is below the review threshold.",
        ai_value=record.classpath,
        confidence=record.confidence,
    )


def _no_manufacturer_draft(db: Session, product: ProductRecord) -> ReviewDraft | None:
    sources = (
        db.query(ProductSourceRecord)
        .filter(ProductSourceRecord.product_id == product.id)
        .all()
    )
    researched = product.status in {
        ProductStatus.NO_AUTHORITATIVE_SOURCE.value,
        ProductStatus.RESEARCHED.value,
        ProductStatus.INDEXED.value,
        ProductStatus.EXTRACTED.value,
        ProductStatus.INSUFFICIENT_EVIDENCE.value,
        ProductStatus.NORMALIZED.value,
        ProductStatus.VALIDATED.value,
        ProductStatus.PARTIAL.value,
        ProductStatus.FAIL.value,
        ProductStatus.REVIEW_REQUIRED.value,
        ProductStatus.APPROVED.value,
    }
    if product.status == ProductStatus.NO_AUTHORITATIVE_SOURCE.value:
        return ReviewDraft(
            product_id=product.id,
            issue_type=ISSUE_NO_AUTHORITATIVE_SOURCE,
            severity=SEVERITY_HIGH,
            attribute="Manufacturer source",
            current_value=None,
            reason="Manufacturer source was not found.",
        )
    if not researched or not sources:
        return None
    if any(row.source_type == SOURCE_MANUFACTURER for row in sources):
        return None
    return ReviewDraft(
        product_id=product.id,
        issue_type=ISSUE_NO_AUTHORITATIVE_SOURCE,
        severity=SEVERITY_HIGH,
        attribute="Manufacturer source",
        current_value=None,
        reason="Manufacturer source was not found.",
    )


def _quota_exhausted_draft(db: Session, product: ProductRecord) -> ReviewDraft | None:
    understood = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product.id)
        .first()
        is not None
    )
    if understood:
        return None
    row = (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product.id,
            ReviewQueueRecord.issue_type == ISSUE_LLM_QUOTA_EXHAUSTED,
            ReviewQueueRecord.status.in_(list(OPEN_STATUSES)),
        )
        .first()
    )
    if row is None:
        return None
    return ReviewDraft(
        product_id=product.id,
        issue_type=ISSUE_LLM_QUOTA_EXHAUSTED,
        severity=row.severity or SEVERITY_HIGH,
        attribute=row.attribute or "Understanding",
        current_value=row.current_value,
        reason=row.reason,
    )


def collect_review_drafts(db: Session, product_id: int) -> list[ReviewDraft]:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    attributes = {
        row.label: row
        for row in db.query(ProductNormalizedAttributeRecord)
        .filter(ProductNormalizedAttributeRecord.product_id == product_id)
        .all()
    }
    drafts: list[ReviewDraft] = []
    validation_row = (
        db.query(ProductValidationRecord)
        .filter(ProductValidationRecord.product_id == product_id)
        .one_or_none()
    )
    if validation_row is not None:
        validation = ValidationResult(
            product_id=product_id,
            status=validation_row.status,
            completeness_score=validation_row.completeness_score,
            evidence_coverage=validation_row.evidence_coverage,
            missing_attributes=validation_row.missing_attributes or [],
            issues=validation_row.issues or [],
            requires_review=validation_row.requires_review,
            approved_for_output=validation_row.approved_for_output,
        )
        drafts.extend(_drafts_from_validation(product_id, validation, attributes))

    extras = [
        _brand_conflict_draft(db, product),
        _classification_draft(db, product),
        _no_manufacturer_draft(db, product),
        _quota_exhausted_draft(db, product),
    ]
    seen = {_issue_key(item.issue_type, item.attribute) for item in drafts}
    resolved = {
        _issue_key(row.issue_type, row.attribute)
        for row in db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product_id,
            ReviewQueueRecord.status.in_(
                [STATUS_APPROVED, STATUS_REJECTED, STATUS_UNKNOWN]
            ),
        )
        .all()
    }
    drafts = [
        item
        for item in drafts
        if _issue_key(item.issue_type, item.attribute) not in resolved
    ]
    seen = {_issue_key(item.issue_type, item.attribute) for item in drafts}
    for extra in extras:
        if extra is None:
            continue
        key = _issue_key(extra.issue_type, extra.attribute)
        if key in seen or key in resolved:
            continue
        seen.add(key)
        drafts.append(extra)
    return drafts


def sync_review_queue(db: Session, product_id: int) -> list[ReviewQueueRecord]:
    drafts = collect_review_drafts(db, product_id)
    wanted = {_issue_key(item.issue_type, item.attribute) for item in drafts}
    existing = (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product_id,
            ReviewQueueRecord.status.in_(list(OPEN_STATUSES)),
        )
        .all()
    )
    for row in existing:
        if _issue_key(row.issue_type, row.attribute) not in wanted:
            db.delete(row)
    by_key = {
        _issue_key(row.issue_type, row.attribute): row
        for row in existing
        if _issue_key(row.issue_type, row.attribute) in wanted
    }
    created = _utcnow()
    for draft in drafts:
        key = _issue_key(draft.issue_type, draft.attribute)
        payload = {
            "issue_type": draft.issue_type,
            "severity": draft.severity,
            "attribute": draft.attribute,
            "current_value": draft.current_value,
            "candidate_values": _as_candidate_dicts(draft.candidate_values),
            "reason": draft.reason,
            "ai_value": draft.ai_value or draft.current_value,
            "diagnostics": {
                "raw_value": draft.raw_value,
                "normalized_value": draft.normalized_value,
                "allowed_values": draft.allowed_values,
                "source": draft.source,
                "evidence_text": draft.evidence_text,
            },
        }
        row = by_key.get(key)
        if row is None:
            row = ReviewQueueRecord(
                product_id=product_id,
                status=STATUS_PENDING,
                created_at=created,
                **payload,
            )
            db.add(row)
            by_key[key] = row
        else:
            for field_name, value in payload.items():
                setattr(row, field_name, value)
    db.flush()
    pending = pending_reviews(db, product_id)
    product = db.get(ProductRecord, product_id)
    if product is not None and pending:
        product.status = ProductStatus.REVIEW_REQUIRED.value
        product.updated_at = created
    return pending


def quality_gate(db: Session, product_id: int) -> dict:
    pending = sync_review_queue(db, product_id)
    review_ids = [row.id for row in pending]
    return {
        "review_ids": review_ids,
        "review_id": review_ids[0] if review_ids else None,
        "requires_review": bool(review_ids),
    }


def _diagnostics(row: ReviewQueueRecord) -> dict:
    payload = getattr(row, "diagnostics", None) or {}
    return payload if isinstance(payload, dict) else {}


def enrich_lov_diagnostics(db: Session, row: ReviewQueueRecord) -> dict:
    """Fill LOV fields from stored diagnostics, or from the normalized row for older queue items."""
    payload = _diagnostics(row)
    if row.issue_type != "LOV_INVALID":
        return payload
    if payload.get("allowed_values") and payload.get("normalized_value"):
        return payload
    attr = None
    if row.attribute:
        attr = (
            db.query(ProductNormalizedAttributeRecord)
            .filter(
                ProductNormalizedAttributeRecord.product_id == row.product_id,
                ProductNormalizedAttributeRecord.label == row.attribute,
            )
            .one_or_none()
        )
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == row.product_id)
        .one_or_none()
    )
    classpath = classification.classpath if classification else None
    allowed = allowed_lov_values(row.attribute or "", classpath) or []
    return {
        "raw_value": payload.get("raw_value") or (attr.raw_value if attr else None),
        "normalized_value": (
            payload.get("normalized_value")
            or (attr.normalized_value if attr else None)
            or row.current_value
        ),
        "allowed_values": payload.get("allowed_values") or allowed,
        "source": payload.get("source") or (attr.selected_source if attr else None),
        "evidence_text": payload.get("evidence_text") or (attr.evidence_text if attr else None),
    }


def list_review_queue(
    db: Session, status: str | None = STATUS_PENDING, product_id: int | None = None
) -> ReviewQueueList:
    query = db.query(ReviewQueueRecord)
    if status:
        query = query.filter(ReviewQueueRecord.status == status)
    if product_id is not None:
        query = query.filter(ReviewQueueRecord.product_id == product_id)
    rows = query.order_by(ReviewQueueRecord.id).all()
    items: list[ReviewQueueItem] = []
    for row in rows:
        product = db.get(ProductRecord, row.product_id)
        diag = enrich_lov_diagnostics(db, row)
        items.append(
            ReviewQueueItem(
                id=row.id,
                product_id=row.product_id,
                mpn=product.mpn if product else None,
                issue_type=row.issue_type,
                severity=row.severity,
                attribute=row.attribute,
                current_value=row.current_value,
                reason=row.reason,
                status=row.status,
                raw_value=diag.get("raw_value"),
                normalized_value=diag.get("normalized_value") or row.current_value,
                allowed_values=list(diag.get("allowed_values") or []),
                source=diag.get("source"),
                evidence_text=diag.get("evidence_text"),
            )
        )
    return ReviewQueueList(total=len(items), items=items)


def _classification_payload(record: ProductClassificationRecord | None) -> dict | None:
    if record is None:
        return None
    return {
        "department": record.department,
        "class_name": record.class_name,
        "fine": record.fine,
        "classpath": record.classpath,
        "confidence": record.confidence,
        "method": record.method,
        "status": record.status,
    }


def get_review(review_id: int, db: Session) -> ReviewDetail:
    row = db.get(ReviewQueueRecord, review_id)
    if row is None:
        raise LookupError(f"Review {review_id} not found")
    product = db.get(ProductRecord, row.product_id)
    if product is None:
        raise LookupError(f"Product {row.product_id} not found")
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product.id)
        .one_or_none()
    )
    understanding = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product.id)
        .one_or_none()
    )
    sources = (
        db.query(ProductSourceRecord)
        .filter(ProductSourceRecord.product_id == product.id)
        .order_by(ProductSourceRecord.authority_score.desc())
        .all()
    )
    candidates = [ReviewCandidate.model_validate(item) for item in _as_candidate_dicts(row.candidate_values)]
    evidence = [item.evidence_text for item in candidates if item.evidence_text]
    confidence = None
    if classification is not None and row.issue_type == ISSUE_LOW_CLASSIFICATION_CONFIDENCE:
        confidence = classification.confidence
    diag = enrich_lov_diagnostics(db, row)
    return ReviewDetail(
        id=row.id,
        product_id=row.product_id,
        issue_type=row.issue_type,
        severity=row.severity,
        attribute=row.attribute,
        current_value=row.current_value,
        candidate_values=candidates,
        evidence=evidence,
        sources=[
            ReviewSourceSummary(
                id=source.id,
                url=source.url,
                title=source.title,
                source_type=source.source_type,
                authority_score=source.authority_score,
            )
            for source in sources
        ],
        confidence=confidence,
        reason=row.reason,
        status=row.status,
        assigned_to=row.assigned_to,
        ai_value=row.ai_value,
        final_value=row.final_value,
        decision=row.decision,
        selected_source=row.selected_source,
        reviewed_by=row.reviewed_by,
        review_reason=row.review_reason,
        raw_value=diag.get("raw_value"),
        normalized_value=diag.get("normalized_value") or row.current_value,
        allowed_values=list(diag.get("allowed_values") or []),
        source=diag.get("source") or row.selected_source,
        evidence_text=diag.get("evidence_text"),
        product=ReviewProductSummary(
            id=product.id,
            mpn=product.mpn,
            description=product.description,
            brand=(
                understanding.brand_candidate
                if understanding
                else product.e1_brand
            ),
            manufacturer=product.manufacturer,
            status=product.status,
            classification=_classification_payload(classification),
        ),
    )


def _values_match(left: str | None, right: str | None, label: str, classpath: str | None) -> bool:
    if not left or not right:
        return False
    if left.strip().lower() == right.strip().lower():
        return True
    left_key = comparable_key(left, None, label, classpath)
    right_key = comparable_key(right, None, label, classpath)
    return bool(left_key and right_key and left_key == right_key)


def _match_candidate(
    candidates: list[dict],
    selected_value: str | None,
    selected_source: str | None,
    label: str,
    classpath: str | None,
) -> dict | None:
    rows = _as_candidate_dicts(candidates)
    if selected_source:
        sourced = [item for item in rows if (item.get("source") or "").upper() == selected_source.upper()]
        if selected_value:
            matched = [
                item
                for item in sourced
                if _values_match(item.get("value"), selected_value, label, classpath)
            ]
            if matched:
                return matched[0]
        if len(sourced) == 1:
            return sourced[0]
        if sourced and not selected_value:
            return sourced[0]
    if selected_value:
        for item in rows:
            if _values_match(item.get("value"), selected_value, label, classpath):
                return item
    return None


def _apply_human_decision(
    db: Session,
    review: ReviewQueueRecord,
    request: ReviewResolveRequest,
) -> str | None:
    if not review.attribute:
        return request.selected_value
    row = (
        db.query(ProductNormalizedAttributeRecord)
        .filter(
            ProductNormalizedAttributeRecord.product_id == review.product_id,
            ProductNormalizedAttributeRecord.label == review.attribute,
        )
        .one_or_none()
    )
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == review.product_id)
        .one_or_none()
    )
    classpath = classification.classpath if classification else None
    if row is None:
        return request.selected_value

    if row.ai_value is None:
        row.ai_value = review.ai_value or review.current_value or row.raw_value or row.normalized_value

    if request.decision == DECISION_APPROVE_CURRENT:
        final = row.normalized_value or row.raw_value or review.current_value
        row.human_value = final
        row.review_decision = request.decision
        row.reviewed_by = request.reviewed_by
        row.review_reason = request.review_reason
        if row.agreement == CONFLICT and row.normalized_value:
            row.agreement = (
                MANUFACTURER_SUPPORTED
                if (row.selected_source or "").upper() == SOURCE_MANUFACTURER
                else INPUT_SOURCED
            )
            row.status = STATUS_NORMALIZED
        return final

    if request.decision == DECISION_SELECT_CANDIDATE:
        matched = _match_candidate(
            row.candidates or review.candidate_values or [],
            request.selected_value,
            request.selected_source,
            review.attribute,
            classpath,
        )
        chosen_value = (matched or {}).get("value") or request.selected_value
        if not chosen_value:
            raise ValueError("SELECT_CANDIDATE requires selected_value or selected_source")
        parsed = normalize_raw(chosen_value, (matched or {}).get("uom"), review.attribute, classpath)
        row.raw_value = row.raw_value or row.ai_value
        row.normalized_value = parsed.normalized_value
        if parsed.normalized_uom:
            row.normalized_uom = parsed.normalized_uom
        if parsed.raw_uom and not row.raw_uom:
            row.raw_uom = parsed.raw_uom
        row.selected_source = (
            request.selected_source
            or (matched or {}).get("source")
            or row.selected_source
        )
        if matched and matched.get("evidence_text"):
            row.evidence_text = matched.get("evidence_text")
        if matched and matched.get("source_id"):
            row.source_id = matched.get("source_id")
        row.human_value = parsed.normalized_value or chosen_value
        row.review_decision = request.decision
        row.reviewed_by = request.reviewed_by
        row.review_reason = request.review_reason
        row.agreement = (
            MANUFACTURER_SUPPORTED
            if (row.selected_source or "").upper() == SOURCE_MANUFACTURER
            else INPUT_SOURCED
        )
        row.status = STATUS_NORMALIZED
        method = "+".join(parsed.methods) if parsed.methods else None
        if method:
            row.normalization_method = (
                f"{row.normalization_method}+HUMAN" if row.normalization_method else "HUMAN"
            )
        else:
            row.normalization_method = (
                f"{row.normalization_method}+HUMAN" if row.normalization_method else "HUMAN"
            )
        return row.human_value

    row.human_value = None
    row.normalized_value = None
    row.review_decision = request.decision
    row.reviewed_by = request.reviewed_by
    row.review_reason = request.review_reason
    row.agreement = NOT_FOUND
    row.status = STATUS_NOT_FOUND if request.decision == DECISION_REJECT_ATTRIBUTE else "UNKNOWN"
    row.selected_source = None
    return None


def _finalize_product(db: Session, product_id: int) -> None:
    remaining = pending_reviews(db, product_id)
    product = db.get(ProductRecord, product_id)
    if product is None:
        return
    if remaining:
        product.status = ProductStatus.REVIEW_REQUIRED.value
        product.updated_at = _utcnow()
        return
    from app.services.validation import validate_product

    try:
        result = validate_product(product_id, db)
    except LookupError:
        product.status = ProductStatus.APPROVED.value
        product.updated_at = _utcnow()
        return
    if pending_reviews(db, product_id):
        product.status = ProductStatus.REVIEW_REQUIRED.value
    elif result.approved_for_output:
        product.status = ProductStatus.APPROVED.value
    product.updated_at = _utcnow()


def resolve_review(
    review_id: int, request: ReviewResolveRequest, db: Session
) -> ReviewResolveResponse:
    row = db.get(ReviewQueueRecord, review_id)
    if row is None:
        raise LookupError(f"Review {review_id} not found")
    if row.status not in OPEN_STATUSES:
        raise ValueError(f"Review {review_id} is already {row.status}")

    final_value = _apply_human_decision(db, row, request)
    now = _utcnow()
    if request.decision in {DECISION_APPROVE_CURRENT, DECISION_SELECT_CANDIDATE}:
        row.status = STATUS_APPROVED
    elif request.decision == DECISION_MARK_UNKNOWN:
        row.status = STATUS_UNKNOWN
    else:
        row.status = STATUS_REJECTED
    row.decision = request.decision
    row.selected_source = request.selected_source or row.selected_source
    row.reviewed_by = request.reviewed_by
    row.assigned_to = request.reviewed_by
    row.review_reason = request.review_reason
    row.final_value = final_value
    if row.ai_value is None:
        row.ai_value = row.current_value
    row.resolved_at = now
    db.flush()

    _finalize_product(db, row.product_id)
    product = db.get(ProductRecord, row.product_id)
    remaining = pending_reviews(db, row.product_id)
    return ReviewResolveResponse(
        review_id=row.id,
        product_id=row.product_id,
        attribute=row.attribute,
        final_value=final_value,
        decision=request.decision,
        selected_source=row.selected_source,
        reviewed_by=request.reviewed_by,
        review_reason=request.review_reason,
        product_status=product.status if product else ProductStatus.REVIEW_REQUIRED.value,
        remaining_reviews=len(remaining),
        paused=bool(remaining),
    )


def process_response_from_state(product_id: int, state: dict, db: Session) -> ProcessResponse:
    from app.services.validation import get_validation

    product = db.get(ProductRecord, product_id)
    review_ids = list(state.get("review_ids") or [])
    validation = None
    if state.get("validation"):
        validation = ValidationResult.model_validate(state["validation"])
    else:
        try:
            validation = get_validation(product_id, db)
        except LookupError:
            validation = None
    requires_review = bool(review_ids) or bool(state.get("requires_review"))
    status = (
        ProductStatus.REVIEW_REQUIRED.value
        if requires_review and product
        else (product.status if product else ProductStatus.FAIL.value)
    )
    approved = bool(validation and validation.approved_for_output and not requires_review)
    return ProcessResponse(
        product_id=product_id,
        status=status,
        approved_for_output=approved,
        requires_review=requires_review,
        review_id=state.get("review_id") or (review_ids[0] if review_ids else None),
        review_ids=review_ids,
        paused=requires_review,
        validation=validation,
    )
