from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import (
    ProductClassificationRecord,
    ProductRecord,
    ProductUnderstandingRecord,
    TaxonomyRecord,
)
from app.models.product import ProductStatus
from app.schemas.classification import ClassificationResponse, ClassificationResult
from app.services.entity_normalize import normalize_entity_name
from app.services.master_data import seed_master_data
from app.services.text_display import preserve_display_text
from app.services.cache_store import get_cached_classification, put_cached_classification

# Taxonomy-match confidence, not extraction certainty.
TAXONOMY_MATCH_EXACT = 0.92
TAXONOMY_MATCH_NORMALIZED = 0.90
TAXONOMY_MATCH_KEYWORD = 0.88
NO_MATCH_THRESHOLD = 0.4

STATUS_CLASSIFIED = "CLASSIFIED"
STATUS_REVIEW = "REVIEW_REQUIRED"

_METHOD_RANK = {
    "exact": 5,
    "normalized_exact": 4,
    "alias_containment": 3,
    "rapidfuzz": 2,
    "keyword": 1,
}


@dataclass
class ScoredTaxonomy:
    node: TaxonomyRecord
    score: float
    method: str


def _plural_close(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return a.rstrip("s") == b or b.rstrip("s") == a or a.rstrip("s") == b.rstrip("s")


def _identity_labels(node: TaxonomyRecord) -> list[str]:
    """Fine type and aliases only. Parent department/class must not win the match."""
    labels = [node.fine, *(node.aliases or [])]
    return [normalize_entity_name(label) for label in labels if label]


def _query_parts(raw_product: dict, understanding: dict) -> list[str]:
    """Product identity only. Do not include category_candidates — those are often
    department names like 'Abrasives' that used to match every sibling node.
    """
    parts: list[str] = []
    for value in (
        understanding.get("product_type"),
        *(understanding.get("extracted_terms") or []),
        raw_product.get("description"),
        raw_product.get("mpn"),
    ):
        if value and str(value).strip():
            parts.append(str(value).strip())
    return parts


def _alias_contained(label_norm: str, blob: str) -> bool:
    """Require a specific alias/fine phrase. Skip short tokens like 'led' or 'disc'."""
    if not label_norm or not blob:
        return False
    if label_norm not in blob:
        return False
    return len(label_norm) >= 8 or len(label_norm.split()) >= 2


def score_taxonomy_node(
    product_type: str | None,
    query_text: str,
    node: TaxonomyRecord,
) -> ScoredTaxonomy:
    labels = _identity_labels(node)
    type_norm = normalize_entity_name(product_type)
    blob = " ".join(
        part for part in (type_norm, normalize_entity_name(query_text)) if part
    )

    if type_norm:
        for label_norm in labels:
            if type_norm == label_norm:
                return ScoredTaxonomy(node=node, score=TAXONOMY_MATCH_EXACT, method="exact")
        for label_norm in labels:
            if _plural_close(type_norm, label_norm):
                return ScoredTaxonomy(node=node, score=TAXONOMY_MATCH_NORMALIZED, method="normalized_exact")
        for label_norm in labels:
            if _alias_contained(label_norm, type_norm):
                return ScoredTaxonomy(
                    node=node, score=TAXONOMY_MATCH_NORMALIZED, method="alias_containment"
                )

    best = 0.0
    method = "rapidfuzz"
    for label_norm in labels:
        if not label_norm:
            continue
        if _alias_contained(label_norm, blob):
            best = max(best, TAXONOMY_MATCH_KEYWORD)
            method = "keyword"
        if type_norm:
            ratio = fuzz.token_set_ratio(type_norm, label_norm) / 100.0
            if ratio >= TAXONOMY_MATCH_NORMALIZED:
                best = max(best, min(ratio, TAXONOMY_MATCH_KEYWORD))
                method = "rapidfuzz"
    return ScoredTaxonomy(node=node, score=round(best, 4), method=method)


def _taxonomy_labels(node: TaxonomyRecord) -> list[str]:
    labels = [node.fine, node.class_name, node.department, *(node.aliases or [])]
    if node.classpath:
        labels.extend(part.strip() for part in node.classpath.split(">") if part.strip())
    return [label for label in labels if label]


def classification_reasoning(
    classpath: str | None,
    product_type: str | None,
    method: str,
    known_labels: list[str] | None = None,
) -> str:
    display = preserve_display_text(product_type, known_labels) or "n/a"
    return (
        f"Matched allowed taxonomy '{classpath}' from product type "
        f"'{display}' using {method}."
    )


def _status_for_confidence(confidence: float) -> str:
    if confidence >= settings.CLASSIFY_HIGH_CONFIDENCE:
        return STATUS_CLASSIFIED
    return STATUS_REVIEW


def classify_against_taxonomy(
    raw_product: dict,
    understanding: dict,
    nodes: list[TaxonomyRecord],
) -> ClassificationResult:
    if not nodes:
        return ClassificationResult(
            product_id=int(raw_product.get("id") or 0),
            method="missing_taxonomy",
            status=STATUS_REVIEW,
            reasoning_summary="No taxonomy reference data is loaded.",
        )

    query_parts = _query_parts(raw_product, understanding)
    query_text = " ".join(query_parts)
    product_type = preserve_display_text(understanding.get("product_type"))
    type_key = normalize_entity_name(product_type)
    cached = get_cached_classification(type_key) if type_key else None
    if cached:
        cached = dict(cached)
        cached["product_id"] = int(raw_product.get("id") or 0)
        return ClassificationResult.model_validate(cached)

    scored = [
        score_taxonomy_node(product_type, query_text, node) for node in nodes
    ]
    scored.sort(
        key=lambda item: (item.score, _METHOD_RANK.get(item.method, 0)),
        reverse=True,
    )
    best = scored[0]

    if best.score < NO_MATCH_THRESHOLD:
        return ClassificationResult(
            product_id=int(raw_product.get("id") or 0),
            confidence=best.score,
            method="no_match",
            status=STATUS_REVIEW,
            reasoning_summary="No allowed taxonomy node was close enough to the product understanding.",
        )

    node = best.node
    confidence = best.score
    status = _status_for_confidence(confidence)
    display_type = preserve_display_text(product_type, _taxonomy_labels(node))
    result = ClassificationResult(
        product_id=int(raw_product.get("id") or 0),
        department=node.department,
        class_name=node.class_name,
        fine=node.fine,
        classpath=node.classpath,
        confidence=confidence,
        method=best.method,
        status=status,
        reasoning_summary=classification_reasoning(
            node.classpath, display_type, best.method, _taxonomy_labels(node)
        ),
    )
    if type_key and best.method in {"exact", "normalized_exact", "alias_containment"}:
        payload = result.model_dump()
        payload.pop("product_id", None)
        put_cached_classification(type_key, payload)
    return result


def persist_classification(db: Session, result: ClassificationResult) -> None:
    product = db.get(ProductRecord, result.product_id)
    if product is None:
        raise LookupError(f"Product {result.product_id} not found")

    record = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == result.product_id)
        .one_or_none()
    )
    fields = {
        "department": result.department,
        "class_name": result.class_name,
        "fine": result.fine,
        "classpath": result.classpath,
        "confidence": result.confidence,
        "method": result.method,
        "status": result.status,
        "reasoning_summary": result.reasoning_summary,
    }
    if record is None:
        db.add(ProductClassificationRecord(product_id=result.product_id, **fields))
    else:
        for key, value in fields.items():
            setattr(record, key, value)

    later_statuses = {
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
    if product.status not in later_statuses:
        product.status = (
            ProductStatus.CLASSIFIED.value
            if result.status == STATUS_CLASSIFIED
            else ProductStatus.REVIEW_REQUIRED.value
        )
    db.flush()


def classify_product(
    product: ProductRecord,
    raw_product: dict,
    understanding: dict,
    db: Session,
) -> ClassificationResult:
    seed_master_data(db)
    nodes = db.query(TaxonomyRecord).all()
    result = classify_against_taxonomy(raw_product, understanding, nodes)
    result.product_id = product.id
    persist_classification(db, result)
    return result


def get_classification(product_id: int, db: Session) -> ClassificationResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    record = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product_id)
        .one_or_none()
    )
    if record is None:
        raise LookupError(f"Product {product_id} has not been classified yet")
    understanding = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product_id)
        .one_or_none()
    )
    known_labels = [
        record.fine,
        record.class_name,
        record.department,
        *(part.strip() for part in (record.classpath or "").split(">") if part.strip()),
    ]
    product_type = understanding.product_type if understanding else None
    reasoning = classification_reasoning(
        record.classpath, product_type, record.method, known_labels
    )
    if record.method in {"no_match", "missing_taxonomy"}:
        reasoning = record.reasoning_summary
    result = ClassificationResult(
        product_id=product_id,
        department=record.department,
        class_name=record.class_name,
        fine=record.fine,
        classpath=record.classpath,
        confidence=record.confidence,
        method=record.method,
        status=record.status,
        reasoning_summary=reasoning,
    )
    return ClassificationResponse(
        product_id=product_id,
        status=record.status,
        classification=result,
    )


def understanding_dict(record: ProductUnderstandingRecord) -> dict:
    return {
        "product_type": record.product_type,
        "brand_candidate": record.brand_candidate,
        "manufacturer_candidate": record.manufacturer_candidate,
        "category_candidates": record.category_candidates or [],
        "extracted_terms": record.extracted_terms or [],
        "candidate_attributes": record.candidate_attributes or {},
        "source_brand": record.source_brand,
        "source_manufacturer": record.source_manufacturer,
        "brand_conflict": record.brand_conflict,
    }
