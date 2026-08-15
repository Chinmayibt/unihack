from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database.models import (
    ProductAttributeRecord,
    ProductClassificationRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
)
from app.models.product import ProductStatus
from app.schemas.normalized_attribute import (
    CONFLICT,
    NOT_FOUND,
    SECONDARY_SOURCE_ONLY,
    STATUS_CONFLICT,
    STATUS_NORMALIZED,
    STATUS_NOT_FOUND,
    STATUS_SECONDARY,
    STATUS_UNCHANGED,
    NormalizationResponse,
    NormalizedAttribute,
)
from app.services.attribute_templates import template_for_classpath
from app.services.evidence_consolidation import consolidate_product
from app.services.quality import completeness_status, missing_attribute_labels, needs_review
from app.services.validation import delete_validation
from app.services.value_normalize import normalize_raw


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def delete_normalized_attributes(db: Session, product_id: int) -> None:
    from app.services.review import delete_pending_reviews

    delete_validation(db, product_id)
    delete_pending_reviews(db, product_id)
    db.query(ProductNormalizedAttributeRecord).filter(
        ProductNormalizedAttributeRecord.product_id == product_id
    ).delete(synchronize_session=False)


def _response(
    product_id: int, classpath: str | None, attributes: list[NormalizedAttribute], status: str
) -> NormalizationResponse:
    template = template_for_classpath(classpath)
    missing = missing_attribute_labels(attributes, template)
    review = needs_review(attributes)
    return NormalizationResponse(
        product_id=product_id,
        status=status,
        classpath=classpath,
        completeness=completeness_status(missing, review),
        missing_attributes=missing,
        requires_review=review,
        attributes=attributes,
    )


def _status_for(agreement: str, methods: list[str], normalized_value: str | None) -> str:
    if agreement == CONFLICT:
        return STATUS_CONFLICT
    if agreement == SECONDARY_SOURCE_ONLY:
        return STATUS_SECONDARY
    if agreement == NOT_FOUND or not normalized_value:
        return STATUS_NOT_FOUND
    if methods:
        return STATUS_NORMALIZED
    return STATUS_UNCHANGED


def persist_normalized(
    db: Session, product_id: int, attributes: list[NormalizedAttribute]
) -> None:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    delete_normalized_attributes(db, product_id)
    created = _utcnow()
    for item in attributes:
        db.add(
            ProductNormalizedAttributeRecord(
                product_id=product_id,
                label=item.label,
                raw_value=item.raw_value,
                normalized_value=item.normalized_value,
                raw_uom=item.raw_uom,
                normalized_uom=item.normalized_uom,
                source_id=item.source_id,
                evidence_text=item.evidence_text,
                selected_source=item.selected_source,
                agreement=item.agreement,
                candidates=[candidate.model_dump() for candidate in item.candidates],
                normalization_method=item.normalization_method,
                status=item.status,
                ai_value=item.ai_value,
                human_value=item.human_value,
                review_decision=item.review_decision,
                reviewed_by=item.reviewed_by,
                review_reason=item.review_reason,
                created_at=created,
            )
        )
    normalized = any(
        item.status in {STATUS_NORMALIZED, STATUS_UNCHANGED} for item in attributes
    )
    if normalized:
        product.status = ProductStatus.NORMALIZED.value
    product.updated_at = created
    db.flush()


def normalize_product_attributes(product_id: int, db: Session) -> NormalizationResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product_id)
        .one_or_none()
    )
    classpath = classification.classpath if classification else None
    extracted = (
        db.query(ProductAttributeRecord)
        .filter(ProductAttributeRecord.product_id == product_id)
        .order_by(ProductAttributeRecord.id)
        .all()
    )
    sources = (
        db.query(ProductSourceRecord)
        .filter(ProductSourceRecord.product_id == product_id)
        .all()
    )
    consolidated = consolidate_product(product, classpath, extracted, sources)
    attributes: list[NormalizedAttribute] = []
    for label, candidates, selected, agreement in consolidated:
        if selected is None:
            attributes.append(
                NormalizedAttribute(
                    label=label,
                    candidates=candidates,
                    agreement=agreement,
                    status=_status_for(agreement, [], None),
                    raw_value=candidates[0].value if candidates else None,
                    raw_uom=candidates[0].uom if candidates else None,
                    evidence_text=candidates[0].evidence_text if candidates else None,
                    source_id=candidates[0].source_id if candidates else None,
                    selected_source=candidates[0].source if candidates and agreement == SECONDARY_SOURCE_ONLY else None,
                )
            )
            continue
        parsed = normalize_raw(selected.value, selected.uom, label, classpath)
        method = "+".join(parsed.methods) if parsed.methods else None
        attributes.append(
            NormalizedAttribute(
                label=label,
                raw_value=parsed.raw_value,
                normalized_value=parsed.normalized_value,
                raw_uom=parsed.raw_uom,
                normalized_uom=parsed.normalized_uom,
                source_id=selected.source_id,
                evidence_text=selected.evidence_text,
                selected_source=selected.source,
                agreement=agreement,
                candidates=candidates,
                normalization_method=method,
                status=_status_for(agreement, parsed.methods, parsed.normalized_value),
            )
        )
    persist_normalized(db, product_id, attributes)
    overall = (
        STATUS_NORMALIZED
        if any(item.status in {STATUS_NORMALIZED, STATUS_UNCHANGED} for item in attributes)
        else ProductStatus.INSUFFICIENT_EVIDENCE.value
    )
    return _response(product_id, classpath, attributes, overall)


def get_normalized_attributes(product_id: int, db: Session) -> NormalizationResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    rows = (
        db.query(ProductNormalizedAttributeRecord)
        .filter(ProductNormalizedAttributeRecord.product_id == product_id)
        .order_by(ProductNormalizedAttributeRecord.id)
        .all()
    )
    if not rows:
        raise LookupError(f"Product {product_id} has no normalized attributes yet")
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product_id)
        .one_or_none()
    )
    attributes = [
        NormalizedAttribute(
            label=row.label,
            raw_value=row.raw_value,
            normalized_value=row.normalized_value,
            raw_uom=row.raw_uom,
            normalized_uom=row.normalized_uom,
            source_id=row.source_id,
            evidence_text=row.evidence_text,
            selected_source=row.selected_source,
            agreement=row.agreement,
            candidates=row.candidates or [],
            normalization_method=row.normalization_method,
            status=row.status,
            ai_value=row.ai_value,
            human_value=row.human_value,
            review_decision=row.review_decision,
            reviewed_by=row.reviewed_by,
            review_reason=row.review_reason,
        )
        for row in rows
    ]
    overall = (
        STATUS_NORMALIZED
        if any(item.status in {STATUS_NORMALIZED, STATUS_UNCHANGED} for item in attributes)
        else ProductStatus.INSUFFICIENT_EVIDENCE.value
    )
    return _response(
        product_id,
        classification.classpath if classification else None,
        attributes,
        overall,
    )
