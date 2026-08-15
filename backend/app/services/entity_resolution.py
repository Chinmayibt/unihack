from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database.models import (
    BrandRecord,
    EntityResolutionRecord,
    ManufacturerRecord,
    ProductClassificationRecord,
    ProductRecord,
    ProductUnderstandingRecord,
)
from app.models.product import ProductStatus
from app.schemas.entity_resolution import EntityMatch, EntityResolution
from app.services.entity_matching import (
    STATUS_RESOLVED,
    STATUS_REVIEW,
    CatalogEntry,
    match_against_catalog,
)
from app.services.entity_normalize import is_missing_entity
from app.services.ingestion import is_missing_brand_value
from app.services.master_data import seed_master_data
from app.services.text_display import preserve_display_text


class ProductNotFoundError(LookupError):
    pass


class UnderstandingNotFoundError(LookupError):
    pass


class ResolutionNotFoundError(LookupError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _catalog_from_brands(rows: list[BrandRecord]) -> list[CatalogEntry]:
    return [
        CatalogEntry(
            canonical_name=row.canonical_name,
            normalized_name=row.normalized_name,
            aliases=row.aliases or [],
        )
        for row in rows
    ]


def _catalog_from_manufacturers(rows: list[ManufacturerRecord]) -> list[CatalogEntry]:
    return [
        CatalogEntry(
            canonical_name=row.canonical_name,
            normalized_name=row.normalized_name,
            aliases=row.aliases or [],
        )
        for row in rows
    ]


def _real_source_brand(raw_product: dict) -> str | None:
    for key in ("e1_brand", "unilog_brand", "dib_brand"):
        value = raw_product.get(key)
        if value and not is_missing_brand_value(value):
            return value
    return None


def _source_vs_description_conflict(raw_product: dict, understanding: dict) -> bool:
    if understanding.get("brand_conflict"):
        return True
    source_brand = _real_source_brand(raw_product)
    description_brand = understanding.get("brand_candidate")
    if description_brand and is_missing_brand_value(description_brand):
        description_brand = None
    if description_brand and not source_brand:
        return True
    if (
        source_brand
        and description_brand
        and source_brand.strip().lower() != description_brand.strip().lower()
    ):
        return True
    return False


def resolve_brand(raw_product: dict, understanding: dict, catalog: list[CatalogEntry]) -> EntityMatch:
    source_brand = _real_source_brand(raw_product)
    description_brand = understanding.get("brand_candidate")
    if description_brand and is_missing_brand_value(description_brand):
        description_brand = None

    source_match = (
        match_against_catalog(source_brand, catalog)
        if source_brand
        else None
    )
    description_match = (
        match_against_catalog(description_brand, catalog)
        if description_brand
        else None
    )

    if source_brand and description_brand:
        source_canonical = source_match.canonical if source_match else None
        description_canonical = description_match.canonical if description_match else None
        if (
            source_canonical
            and description_canonical
            and source_canonical.lower() != description_canonical.lower()
        ):
            return EntityMatch(
                candidate=description_brand,
                canonical=None,
                confidence=0.55,
                method="brand_conflict",
                status=STATUS_REVIEW,
            )
        if description_match and description_match.status == STATUS_RESOLVED:
            if not source_canonical or source_canonical.lower() == description_match.canonical.lower():
                return description_match.model_copy(update={"method": "description_match"})
        if source_match and source_match.status == STATUS_RESOLVED:
            return source_match
        return description_match or source_match or EntityMatch(
            candidate=description_brand,
            canonical=None,
            confidence=0.71,
            method="unknown_entity",
            status=STATUS_REVIEW,
        )

    if description_brand and not source_brand:
        match = description_match or match_against_catalog(description_brand, catalog)
        if match.status == STATUS_RESOLVED:
            return match.model_copy(update={"method": "description_match"})
        return match

    if source_brand:
        return source_match or match_against_catalog(source_brand, catalog)

    placeholder = (
        raw_product.get("e1_brand")
        or raw_product.get("unilog_brand")
        or raw_product.get("dib_brand")
    )
    return EntityMatch(
        candidate=placeholder,
        canonical=None,
        confidence=0.2,
        method="missing",
        status=STATUS_REVIEW,
    )


def resolve_manufacturer(
    raw_product: dict, understanding: dict, catalog: list[CatalogEntry]
) -> EntityMatch:
    candidate = understanding.get("manufacturer_candidate") or raw_product.get("manufacturer")
    if is_missing_entity(candidate):
        return EntityMatch(
            candidate=None,
            canonical=None,
            confidence=0.0,
            method="missing",
            status=STATUS_REVIEW,
        )
    return match_against_catalog(candidate, catalog)


def build_entity_resolution(
    product: ProductRecord,
    raw_product: dict,
    understanding: dict,
    db: Session,
) -> EntityResolution:
    seed_master_data(db)
    brand_catalog = _catalog_from_brands(db.query(BrandRecord).all())
    manufacturer_catalog = _catalog_from_manufacturers(db.query(ManufacturerRecord).all())

    brand = resolve_brand(raw_product, understanding, brand_catalog)
    manufacturer = resolve_manufacturer(raw_product, understanding, manufacturer_catalog)
    product_status = (
        ProductStatus.RESOLVED.value
        if brand.status == STATUS_RESOLVED and manufacturer.status == STATUS_RESOLVED
        else ProductStatus.REVIEW_REQUIRED.value
    )
    brand_conflict = _source_vs_description_conflict(raw_product, understanding) or (
        brand.method == "brand_conflict"
    )
    conflict_resolved = bool(
        brand_conflict and brand.status == STATUS_RESOLVED and brand.canonical
    )
    return EntityResolution(
        product_id=product.id,
        status=product_status,
        brand=brand,
        manufacturer=manufacturer,
        brand_conflict=brand_conflict,
        conflict_resolved=conflict_resolved,
    )


def persist_entity_resolution(db: Session, result: EntityResolution) -> None:
    product = db.get(ProductRecord, result.product_id)
    if product is None:
        raise ProductNotFoundError(f"Product {result.product_id} not found")

    for entity_type, match in (("brand", result.brand), ("manufacturer", result.manufacturer)):
        record = (
            db.query(EntityResolutionRecord)
            .filter(
                EntityResolutionRecord.product_id == result.product_id,
                EntityResolutionRecord.entity_type == entity_type,
            )
            .one_or_none()
        )
        fields = {
            "candidate": match.candidate,
            "canonical": match.canonical,
            "confidence": match.confidence,
            "method": match.method,
            "status": match.status,
            "brand_conflict": result.brand_conflict,
            "conflict_resolved": result.conflict_resolved,
        }
        if record is None:
            db.add(
                EntityResolutionRecord(
                    product_id=result.product_id,
                    entity_type=entity_type,
                    **fields,
                )
            )
        else:
            for key, value in fields.items():
                setattr(record, key, value)

    classified = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == result.product_id)
        .one_or_none()
    )
    later_statuses = {
        ProductStatus.CLASSIFIED.value,
        ProductStatus.RESEARCHED.value,
        ProductStatus.NO_AUTHORITATIVE_SOURCE.value,
        ProductStatus.INDEXED.value,
        ProductStatus.EXTRACTED.value,
        ProductStatus.INSUFFICIENT_EVIDENCE.value,
        ProductStatus.NORMALIZED.value,
        ProductStatus.VALIDATED.value,
        ProductStatus.PARTIAL.value,
        ProductStatus.FAIL.value,
        ProductStatus.APPROVED.value,
    }
    if classified is None and product.status not in later_statuses:
        product.status = result.status
    product.updated_at = _utcnow()
    db.flush()


def _understanding_dict(record: ProductUnderstandingRecord) -> dict:
    return {
        "product_type": preserve_display_text(record.product_type),
        "brand_candidate": preserve_display_text(record.brand_candidate),
        "manufacturer_candidate": preserve_display_text(record.manufacturer_candidate),
        "category_candidates": record.category_candidates or [],
        "extracted_terms": record.extracted_terms or [],
        "candidate_attributes": record.candidate_attributes or {},
        "source_brand": record.source_brand,
        "source_manufacturer": record.source_manufacturer,
        "brand_conflict": record.brand_conflict,
    }


def resolve_product(product_id: int, db: Session, raw_product: dict, understanding: dict) -> EntityResolution:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise ProductNotFoundError(f"Product {product_id} not found")
    result = build_entity_resolution(product, raw_product, understanding, db)
    persist_entity_resolution(db, result)
    return result


def get_entities(product_id: int, db: Session) -> EntityResolution:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise ProductNotFoundError(f"Product {product_id} not found")

    rows = (
        db.query(EntityResolutionRecord)
        .filter(EntityResolutionRecord.product_id == product_id)
        .all()
    )
    if not rows:
        raise ResolutionNotFoundError(
            f"Product {product_id} has not been resolved yet"
        )

    by_type = {row.entity_type: row for row in rows}

    def to_match(row: EntityResolutionRecord | None, entity_type: str) -> EntityMatch:
        if row is None:
            return EntityMatch(
                candidate=None,
                canonical=None,
                confidence=0.0,
                method="missing",
                status=STATUS_REVIEW,
            )
        return EntityMatch(
            candidate=row.candidate,
            canonical=row.canonical,
            confidence=row.confidence,
            method=row.method,
            status=row.status,
        )

    brand = to_match(by_type.get("brand"), "brand")
    manufacturer = to_match(by_type.get("manufacturer"), "manufacturer")
    flag_row = by_type.get("brand") or rows[0]
    status = (
        ProductStatus.RESOLVED.value
        if brand.status == STATUS_RESOLVED and manufacturer.status == STATUS_RESOLVED
        else ProductStatus.REVIEW_REQUIRED.value
    )
    return EntityResolution(
        product_id=product_id,
        status=status,
        brand=brand,
        manufacturer=manufacturer,
        brand_conflict=bool(getattr(flag_row, "brand_conflict", False)),
        conflict_resolved=bool(getattr(flag_row, "conflict_resolved", False)),
    )
