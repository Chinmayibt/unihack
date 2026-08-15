from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database.models import (
    ProductClassificationRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductValidationRecord,
)
from app.models.product import ProductStatus
from app.schemas.normalized_attribute import (
    CONFLICT,
    NormalizedAttribute,
    SECONDARY_SOURCE_ONLY,
)
from app.schemas.validation import (
    ISSUE_LOV_INVALID,
    ISSUE_MISSING_EVIDENCE,
    ISSUE_MISSING_IDENTITY,
    ISSUE_MISSING_REQUIRED,
    ISSUE_SECONDARY_ONLY,
    ISSUE_SOURCE_CONFLICT,
    ISSUE_UOM_INVALID,
    ISSUE_UOM_MISSING,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    STATUS_REVIEW,
    ValidationIssue,
    ValidationResult,
)
from app.services.attribute_templates import template_for_classpath
from app.services.quality import is_populated, missing_attribute_labels
from app.services.standards import allowed_lov_values, canonical_uom, uoms_for_family
from app.services.value_normalize import resolve_lov


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def delete_validation(db: Session, product_id: int) -> None:
    db.query(ProductValidationRecord).filter(
        ProductValidationRecord.product_id == product_id
    ).delete(synchronize_session=False)


def _has_provenance(item: NormalizedAttribute) -> bool:
    if not is_populated(item):
        return False
    return bool(item.selected_source) and bool(
        item.evidence_text or item.source_id or item.selected_source == "INPUT"
    )


def _uom_issue(item: NormalizedAttribute, spec) -> ValidationIssue | None:
    uom = item.normalized_uom
    if uom:
        approved = canonical_uom(uom)
        family = uoms_for_family(spec.uom_family) if spec else None
        if approved is None or (family is not None and approved not in family):
            return ValidationIssue(
                attribute=item.label,
                issue_type=ISSUE_UOM_INVALID,
                severity=SEVERITY_HIGH,
                message=f"UOM {uom!r} is not an approved unit for {item.label}.",
                requires_review=True,
            )
        return None
    if spec and spec.expects_uom and is_populated(item):
        return ValidationIssue(
            attribute=item.label,
            issue_type=ISSUE_UOM_MISSING,
            severity=SEVERITY_MEDIUM,
            message=f"{item.label} is populated but has no approved UOM.",
            requires_review=False,
        )
    return None


def _lov_issue(item: NormalizedAttribute, classpath: str | None) -> ValidationIssue | None:
    if not is_populated(item):
        return None
    allowed = allowed_lov_values(item.label, classpath)
    if allowed is None:
        return None
    resolved, method = resolve_lov(item.label, item.normalized_value, classpath)
    if method == "LOV" and resolved:
        item.normalized_value = resolved
        return None
    return ValidationIssue(
        attribute=item.label,
        issue_type=ISSUE_LOV_INVALID,
        severity=SEVERITY_HIGH,
        message=(
            f"Normalized value {item.normalized_value!r} does not match approved LOV "
            f"for {item.label}."
        ),
        requires_review=True,
        raw_value=item.raw_value,
        normalized_value=item.normalized_value,
        allowed_values=allowed,
        source=item.selected_source,
        evidence_text=item.evidence_text,
    )


def evaluate_attributes(
    product_id: int,
    classpath: str | None,
    attributes: list[NormalizedAttribute],
    *,
    classified: bool,
) -> ValidationResult:
    template = template_for_classpath(classpath)
    by_label = {item.label: item for item in attributes}
    issues: list[ValidationIssue] = []

    if not classified or not classpath:
        issues.append(
            ValidationIssue(
                attribute="Classification",
                issue_type=ISSUE_MISSING_IDENTITY,
                severity=SEVERITY_HIGH,
                message="Product classification is missing.",
                requires_review=True,
            )
        )

    missing = missing_attribute_labels(attributes, template)
    required_missing = [item.label for item in template if item.required and item.label in missing]
    for label in required_missing:
        item = by_label.get(label)
        if item is not None and item.agreement == CONFLICT:
            continue
        issues.append(
            ValidationIssue(
                attribute=label,
                issue_type=ISSUE_MISSING_REQUIRED,
                severity=SEVERITY_HIGH,
                message=f"Required attribute {label} is missing.",
                requires_review=True,
            )
        )

    for spec in template:
        item = by_label.get(spec.label)
        if item is None:
            continue
        if item.agreement == CONFLICT:
            issues.append(
                ValidationIssue(
                    attribute=item.label,
                    issue_type=ISSUE_SOURCE_CONFLICT,
                    severity=SEVERITY_HIGH,
                    message="Input and manufacturer values disagree.",
                    requires_review=True,
                )
            )
            continue
        if item.agreement == SECONDARY_SOURCE_ONLY:
            issues.append(
                ValidationIssue(
                    attribute=item.label,
                    issue_type=ISSUE_SECONDARY_ONLY,
                    severity=SEVERITY_MEDIUM,
                    message="Only low-authority source evidence was found.",
                    requires_review=True,
                )
            )
            continue
        if is_populated(item) and not _has_provenance(item):
            issues.append(
                ValidationIssue(
                    attribute=item.label,
                    issue_type=ISSUE_MISSING_EVIDENCE,
                    severity=SEVERITY_HIGH,
                    message=f"{item.label} is populated without source evidence.",
                    requires_review=True,
                )
            )
        uom_issue = _uom_issue(item, spec)
        if uom_issue:
            issues.append(uom_issue)
        lov_issue = _lov_issue(item, classpath)
        if lov_issue:
            issues.append(lov_issue)

    populated = [item for item in attributes if is_populated(item)]
    evidenced = [item for item in populated if _has_provenance(item)]
    completeness = round(len(populated) / len(template), 4) if template else 0.0
    coverage = round(len(evidenced) / len(populated), 4) if populated else 0.0
    requires_review = any(issue.requires_review for issue in issues)
    identity_fail = any(issue.issue_type == ISSUE_MISSING_IDENTITY for issue in issues)
    conflict_labels = {
        issue.attribute for issue in issues if issue.issue_type == ISSUE_SOURCE_CONFLICT
    }
    required_unresolved = [
        label for label in required_missing if label not in conflict_labels
    ]

    if identity_fail or required_unresolved:
        status = STATUS_FAIL
    elif requires_review:
        status = STATUS_REVIEW
    elif missing:
        status = STATUS_PARTIAL
    else:
        status = STATUS_PASS

    return ValidationResult(
        product_id=product_id,
        status=status,
        completeness_score=completeness,
        evidence_coverage=coverage,
        missing_attributes=missing,
        issues=issues,
        requires_review=requires_review,
        approved_for_output=status in {STATUS_PASS, STATUS_PARTIAL},
    )


def persist_validation(db: Session, result: ValidationResult) -> None:
    product = db.get(ProductRecord, result.product_id)
    if product is None:
        raise LookupError(f"Product {result.product_id} not found")
    delete_validation(db, result.product_id)
    created = _utcnow()
    db.add(
        ProductValidationRecord(
            product_id=result.product_id,
            status=result.status,
            completeness_score=result.completeness_score,
            evidence_coverage=result.evidence_coverage,
            missing_attributes=result.missing_attributes,
            issues=[issue.model_dump() for issue in result.issues],
            requires_review=result.requires_review,
            approved_for_output=result.approved_for_output,
            created_at=created,
        )
    )
    status_map = {
        STATUS_PASS: ProductStatus.VALIDATED.value,
        STATUS_PARTIAL: ProductStatus.PARTIAL.value,
        STATUS_REVIEW: ProductStatus.REVIEW_REQUIRED.value,
        STATUS_FAIL: ProductStatus.FAIL.value,
    }
    product.status = status_map.get(result.status, ProductStatus.PARTIAL.value)
    product.updated_at = created
    db.flush()
    from app.services.review import sync_review_queue

    sync_review_queue(db, result.product_id)


def validate_product(product_id: int, db: Session) -> ValidationResult:
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
        raise LookupError(f"Product {product_id} has not been normalized yet")
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
        )
        for row in rows
    ]
    result = evaluate_attributes(
        product_id,
        classification.classpath if classification else None,
        attributes,
        classified=classification is not None,
    )
    by_label = {item.label: item for item in attributes}
    for row in rows:
        updated = by_label.get(row.label)
        if updated is None or updated.normalized_value == row.normalized_value:
            continue
        row.normalized_value = updated.normalized_value
        method = row.normalization_method or ""
        if updated.normalized_value and "LOV" not in method:
            row.normalization_method = f"{method}+LOV" if method else "LOV"
    persist_validation(db, result)
    return result


def get_validation(product_id: int, db: Session) -> ValidationResult:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    record = (
        db.query(ProductValidationRecord)
        .filter(ProductValidationRecord.product_id == product_id)
        .one_or_none()
    )
    if record is None:
        raise LookupError(f"Product {product_id} has not been validated yet")
    return ValidationResult(
        product_id=product_id,
        status=record.status,
        completeness_score=record.completeness_score,
        evidence_coverage=record.evidence_coverage,
        missing_attributes=record.missing_attributes or [],
        issues=record.issues or [],
        requires_review=record.requires_review,
        approved_for_output=record.approved_for_output,
    )
