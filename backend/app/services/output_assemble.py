from __future__ import annotations

from sqlalchemy.orm import Session

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
from app.schemas.final_output import (
    ATTRIBUTE_SLOT_COUNT,
    EMPTY_OUTPUT_VALUE,
    NAMED_DIMENSIONS,
    AttributeProvenance,
    FinalProductEnvelope,
    FinalProductInternal,
)
from app.schemas.normalized_attribute import NOT_FOUND
from app.schemas.review import STATUS_APPROVED, STATUS_REJECTED, STATUS_UNKNOWN
from app.schemas.source import SOURCE_MANUFACTURER
from app.schemas.validation import STATUS_PASS, ValidationResult
from app.services.attribute_templates import template_for_classpath
from app.services.output_contract import (
    attribute_slot_headers,
    empty_output_row,
    freeze_output_row,
)
from app.services.review import pending_reviews


def _text(value: object | None) -> str:
    if value is None:
        return EMPTY_OUTPUT_VALUE
    text = str(value).strip()
    return text if text else EMPTY_OUTPUT_VALUE


def _join(*parts: object) -> str:
    items = [_text(part) for part in parts]
    return " ".join(item for item in items if item)


def _attr_value(row: ProductNormalizedAttributeRecord | None) -> str:
    if row is None:
        return EMPTY_OUTPUT_VALUE
    if row.agreement == NOT_FOUND or not row.normalized_value:
        return EMPTY_OUTPUT_VALUE
    return _text(row.normalized_value)


def _attr_uom(row: ProductNormalizedAttributeRecord | None) -> str:
    if row is None or not _attr_value(row):
        return EMPTY_OUTPUT_VALUE
    return _text(row.normalized_uom)


def _by_type(rows: list[EntityResolutionRecord]) -> dict[str, EntityResolutionRecord]:
    return {row.entity_type: row for row in rows}


def _validation_result(record: ProductValidationRecord | None) -> ValidationResult | None:
    if record is None:
        return None
    return ValidationResult(
        product_id=record.product_id,
        status=record.status,
        completeness_score=record.completeness_score,
        evidence_coverage=record.evidence_coverage,
        missing_attributes=record.missing_attributes or [],
        issues=record.issues or [],
        requires_review=record.requires_review,
        approved_for_output=record.approved_for_output,
    )


def _has_human_review(db: Session, product_id: int) -> bool:
    return (
        db.query(ReviewQueueRecord)
        .filter(
            ReviewQueueRecord.product_id == product_id,
            ReviewQueueRecord.status.in_(
                [STATUS_APPROVED, STATUS_REJECTED, STATUS_UNKNOWN]
            ),
        )
        .first()
        is not None
    )


def eligibility_for_csv(
    product: ProductRecord,
    validation: ValidationResult | None,
    pending_count: int,
) -> tuple[bool, str]:
    if pending_count or product.status == ProductStatus.REVIEW_REQUIRED.value:
        return False, "review_pending"
    if product.status == ProductStatus.FAIL.value or (
        validation is not None and validation.status == "FAIL"
    ):
        return False, "failed"
    if validation is not None and validation.approved_for_output:
        if product.status == ProductStatus.APPROVED.value or validation.status == STATUS_PASS:
            return True, "approved"
        return True, "partial"
    if product.status in {
        ProductStatus.APPROVED.value,
        ProductStatus.VALIDATED.value,
        ProductStatus.PARTIAL.value,
    }:
        bucket = (
            "approved"
            if product.status in {ProductStatus.APPROVED.value, ProductStatus.VALIDATED.value}
            else "partial"
        )
        return True, bucket
    return False, "not_ready"


def _source_urls(sources: list[ProductSourceRecord]) -> tuple[str, list[str]]:
    manufacturer = [
        row
        for row in sources
        if row.source_type == SOURCE_MANUFACTURER and _text(row.url)
    ]
    manufacturer.sort(key=lambda row: (-(row.authority_score or 0), -(row.relevance_score or 0)))
    mfr_url = _text(manufacturer[0].url) if manufacturer else EMPTY_OUTPUT_VALUE
    refs: list[str] = []
    seen = {mfr_url} if mfr_url else set()
    ranked = sorted(
        sources,
        key=lambda row: (-(row.authority_score or 0), -(row.relevance_score or 0), row.id),
    )
    for row in ranked:
        url = _text(row.url)
        if not url or url in seen:
            continue
        seen.add(url)
        refs.append(url)
        if len(refs) == 5:
            break
    return mfr_url, refs


def _document_links(sources: list[ProductSourceRecord]) -> dict[str, str]:
    mapping = {
        "SPECIFICATION": "Specification Sheet",
        "INSTALLATION_MANUAL": "Instruction/Installation Manual",
        "CATALOG": "Catalog",
        "TECHNICAL_DOCUMENT": "Technical Bulletin",
    }
    links: dict[str, str] = {}
    for row in sources:
        column = mapping.get(row.content_type or "")
        if column and column not in links and _text(row.url):
            links[column] = _text(row.url)
    return links


def _descriptions(
    product: ProductRecord,
    brand: str,
    manufacturer: str,
    by_label: dict[str, ProductNormalizedAttributeRecord],
) -> dict[str, str]:
    product_name = _attr_value(by_label.get("Product Type"))
    width = _join(_attr_value(by_label.get("Width")), _attr_uom(by_label.get("Width")))
    length = _join(_attr_value(by_label.get("Length")), _attr_uom(by_label.get("Length")))
    size = EMPTY_OUTPUT_VALUE
    if width and length:
        size = f"{width} x {length}"
    elif width:
        size = width
    application = _attr_value(by_label.get("Application"))
    short_desc = _join(brand, product_name, product.mpn, size)
    return {
        "Product Name": product_name,
        "Application": application,
        "INVOICE_DESC": _text(product.description),
        "MOBILE_DESC": _join(manufacturer, brand, product_name, product.mpn),
        "SHORT_DESC": short_desc,
        "RETAIL_DESC": _join(brand, product_name, size),
        "LONG_DESC1": _join(short_desc, application),
    }


def assemble_output(product_id: int, db: Session) -> FinalProductEnvelope:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")

    understanding = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product_id)
        .one_or_none()
    )
    entities = (
        db.query(EntityResolutionRecord)
        .filter(EntityResolutionRecord.product_id == product_id)
        .all()
    )
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product_id)
        .one_or_none()
    )
    sources = (
        db.query(ProductSourceRecord)
        .filter(ProductSourceRecord.product_id == product_id)
        .all()
    )
    attributes = (
        db.query(ProductNormalizedAttributeRecord)
        .filter(ProductNormalizedAttributeRecord.product_id == product_id)
        .order_by(ProductNormalizedAttributeRecord.id)
        .all()
    )
    validation_row = (
        db.query(ProductValidationRecord)
        .filter(ProductValidationRecord.product_id == product_id)
        .one_or_none()
    )
    validation = _validation_result(validation_row)
    pending_count = len(pending_reviews(db, product_id))
    eligible, reason = eligibility_for_csv(product, validation, pending_count)
    reviewed = _has_human_review(db, product_id)

    by_entity = _by_type(entities)
    brand_row = by_entity.get("brand")
    manufacturer_row = by_entity.get("manufacturer")
    brand = _text(
        (brand_row.canonical if brand_row and brand_row.canonical else None)
        or (understanding.brand_candidate if understanding else None)
    )
    manufacturer = _text(
        (manufacturer_row.canonical if manufacturer_row and manufacturer_row.canonical else None)
        or (understanding.manufacturer_candidate if understanding else None)
        or product.manufacturer
    )
    classpath = classification.classpath if classification else None
    by_label = {row.label: row for row in attributes}
    source_by_id = {row.id: row for row in sources}

    provenance = [
        AttributeProvenance(
            label=row.label,
            final_value=row.normalized_value,
            normalized_uom=row.normalized_uom,
            raw_value=row.raw_value,
            selected_source=row.selected_source,
            source_id=row.source_id,
            source_url=(
                _text(source_by_id[row.source_id].url) or None
                if row.source_id in source_by_id
                else None
            ),
            evidence_text=row.evidence_text,
            agreement=row.agreement,
            ai_value=row.ai_value,
            human_value=row.human_value,
            review_decision=row.review_decision,
            reviewed_by=row.reviewed_by,
            review_reason=row.review_reason,
        )
        for row in attributes
    ]

    template = template_for_classpath(classpath)
    if len(template) > ATTRIBUTE_SLOT_COUNT:
        raise ValueError(
            f"Classpath {classpath!r} has {len(template)} attributes; max is {ATTRIBUTE_SLOT_COUNT}"
        )

    values = empty_output_row()
    mfr_url, refs = _source_urls(sources)
    values["MFR URL"] = mfr_url
    for index, url in enumerate(refs, start=1):
        values[f"Ref URL {index}"] = url
    values["Dept"] = _text(classification.department if classification else None)
    values["Class"] = _text(classification.class_name if classification else None)
    values["Fine"] = _text(classification.fine if classification else None)
    values["Mfg_Part_Num"] = _text(product.mpn)
    values["Part_Desc"] = _text(product.description)
    values["E1_Brand"] = _text(product.e1_brand)
    values["Unilog_Brand"] = _text(product.unilog_brand)
    values["DIB_Brand"] = _text(product.dib_brand)
    values["Part_Manuf"] = _text(product.manufacturer)
    values["MANUFACTURER_NAME"] = manufacturer
    values["BRAND_NAME"] = brand
    values["MANUFACTURER_PART_NUMBER"] = _text(product.mpn)
    values["Classpath"] = _text(classpath)

    for spec_index, spec in enumerate(template, start=1):
        label_key, value_key, uom_key = attribute_slot_headers(spec_index)
        row = by_label.get(spec.label)
        values[label_key] = spec.label
        values[value_key] = _attr_value(row)
        values[uom_key] = _attr_uom(row)

    leftover = [
        row
        for row in attributes
        if row.label not in {spec.label for spec in template} and _attr_value(row)
    ]
    next_slot = len(template) + 1
    for row in leftover:
        if next_slot > ATTRIBUTE_SLOT_COUNT:
            raise ValueError("Too many attributes to fit the expected output slots")
        label_key, value_key, uom_key = attribute_slot_headers(next_slot)
        values[label_key] = row.label
        values[value_key] = _attr_value(row)
        values[uom_key] = _attr_uom(row)
        next_slot += 1

    for label, (value_col, uom_col) in NAMED_DIMENSIONS.items():
        row = by_label.get(label)
        values[value_col] = _attr_value(row)
        values[uom_col] = _attr_uom(row)

    quantity = by_label.get("Quantity")
    values["Selling Qty"] = _attr_value(quantity)
    values["Selling UOM"] = _attr_uom(quantity)
    values.update(_descriptions(product, brand, manufacturer, by_label))
    values.update(_document_links(sources))

    output = freeze_output_row(values)
    assembled = FinalProductInternal(
        input_identity={
            "mpn": product.mpn,
            "description": product.description,
            "e1_brand": product.e1_brand,
            "unilog_brand": product.unilog_brand,
            "dib_brand": product.dib_brand,
            "manufacturer": product.manufacturer,
        },
        resolved_entities={
            "brand": brand or None,
            "manufacturer": manufacturer or None,
        },
        classification=(
            {
                "department": classification.department,
                "class_name": classification.class_name,
                "fine": classification.fine,
                "classpath": classification.classpath,
                "confidence": classification.confidence,
                "status": classification.status,
            }
            if classification
            else None
        ),
        attributes=[
            {
                "label": row.label,
                "normalized_value": row.normalized_value,
                "normalized_uom": row.normalized_uom,
                "status": row.status,
            }
            for row in attributes
        ],
        provenance=provenance,
        validation=validation,
    )
    approved = bool(validation and validation.approved_for_output and eligible)
    return FinalProductEnvelope(
        product_id=product.id,
        mpn=product.mpn,
        processing_status=product.status,
        reviewed=reviewed,
        approved_for_output=approved,
        eligible_for_csv=eligible,
        eligibility_reason=reason,
        assembled=assembled,
        output=output,
    )
