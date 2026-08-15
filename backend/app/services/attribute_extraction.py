from __future__ import annotations

import re
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from app.agents.attribute_extraction import invoke_attribute_llm
from app.agents.understanding_logic import appears_in_input
from app.core.config import settings
from app.database.models import (
    ProductAttributeRecord,
    ProductClassificationRecord,
    ProductDocumentRecord,
    ProductRecord,
)
from app.models.product import ProductStatus
from app.schemas.attribute import (
    STATUS_EXTRACTED,
    STATUS_NOT_FOUND,
    AttributeExtractionResponse,
    ExtractionMetrics,
    LLMAttributeExtraction,
    LLMExtractedSlot,
    ProductAttribute,
)
from app.schemas.evidence import Evidence
from app.schemas.source import SOURCE_MANUFACTURER
from app.services.attribute_normalization import delete_normalized_attributes
from app.services.attribute_templates import template_for_classpath
from app.services.llm_retry import last_llm_call_metrics, reset_llm_call_metrics
from app.services.retrieval import search_product_evidence
from app.services.standards import approved_lov_alias_map, canonical_lov_key
from app.services.value_parse import parse_input_candidates


INPUT_STRONG_LABELS = {"Width", "Length", "Quantity", "Grit", "Diameter", "Size"}
_SPEC_TYPE_CODE = re.compile(r"^type\s*-?\s*\d+[a-z]?$", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def evidence_confidence(
    *,
    source_type: str | None,
    retrieval_score: float,
    exactness: float,
) -> float:
    authority = 1.0 if source_type == SOURCE_MANUFACTURER else 0.5
    score = 0.45 * authority + 0.25 * max(0.0, retrieval_score) + 0.30 * exactness
    return round(min(1.0, max(0.0, score)), 4)


def _exactness(value: str, evidence_text: str) -> float:
    if not value or not evidence_text:
        return 0.0
    if value.lower() in evidence_text.lower():
        return 0.95
    if appears_in_input(value, evidence_text):
        return 0.85
    return 0.0


def _evidence_supports_value(value: str, blob: str) -> bool:
    """Reject values that only appear as a substring of an MPN or similar token."""
    if not appears_in_input(value, blob):
        return False
    stripped = value.strip()
    if stripped.isdigit():
        pattern = rf"(?<![A-Za-z0-9]){re.escape(stripped)}(?![A-Za-z0-9])"
        return re.search(pattern, blob) is not None
    return True


def _best_supporting_hit(value: str | None, hits: list[Evidence]) -> Evidence | None:
    if not hits:
        return None
    if not value:
        return hits[0]
    for hit in hits:
        blob = hit.evidence_text or hit.text or ""
        if appears_in_input(value, blob):
            return hit
    return None


def _slot_for_label(result: LLMAttributeExtraction, label: str) -> LLMExtractedSlot | None:
    for slot in result.attributes:
        if slot.label.strip().lower() == label.strip().lower():
            return slot
    return None


def _is_spec_type_code(value: str | None) -> bool:
    return bool(value and _SPEC_TYPE_CODE.fullmatch(value.strip()))


def product_type_from_title(description: str, classpath: str | None) -> str | None:
    """Map a title phrase onto an approved Product Type alias. Never maps 'Type 1' itself."""
    blob = canonical_lov_key(description)
    if not blob:
        return None
    mapping = approved_lov_alias_map("Product Type", classpath)
    matches = [
        (len(alias), canonical)
        for alias, canonical in mapping.items()
        if alias and alias in blob and not _is_spec_type_code(alias)
    ]
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _format_blocks(blocks: list[dict], product_description: str = "") -> str:
    seen: set[str] = set()
    unique_hits: list[Evidence] = []
    for block in blocks:
        for hit in block.get("hits") or []:
            key = (hit.evidence_text or hit.text or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_hits.append(hit)
    if unique_hits:
        evidence = "\n---\n".join(
            f"[score={hit.retrieval_score:.3f} source={hit.source_type or 'unknown'}]\n{hit.evidence_text}"
            for hit in unique_hits
        )
    else:
        evidence = "(no retrieved evidence)"
    lines = [
        "Shared retrieved evidence:",
        evidence,
        "",
    ]
    if product_description.strip():
        lines.extend(
            [
                "Product title/description (input evidence):",
                product_description.strip(),
                "",
            ]
        )
    lines.extend(
        [
            "Extract a slot for every allowed attribute label. Do not add extra labels.",
            "Attributes:",
        ]
    )
    for block in blocks:
        extra = ""
        candidate = block.get("input_candidate") or {}
        if candidate.get("value"):
            extra = (
                f" Input candidate: {candidate.get('value')} {candidate.get('uom') or ''}"
                f" (from {candidate.get('evidence_text')!r}). Prefer manufacturer evidence if present."
            )
        lines.append(f"- {block['label']}: {block['query']}.{extra}")
    return "\n".join(lines)


def retrieve_attribute_evidence(
    product_id: int,
    db: Session,
    top_k: int | None = None,
) -> tuple[str | None, list[dict], dict]:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product_id)
        .one_or_none()
    )
    classpath = classification.classpath if classification else None
    template = template_for_classpath(classpath)
    input_found = parse_input_candidates(product.description or "")
    limit = top_k or settings.ATTRIBUTE_EVIDENCE_TOP_K
    query_parts = [product.mpn]
    if classification and classification.fine:
        query_parts.append(classification.fine)
    for item in template:
        if item.label in INPUT_STRONG_LABELS and item.label in input_found:
            continue
        query_parts.append(item.query)
    retrieval_started = perf_counter()
    shared_hits: list[Evidence] = []
    search_metrics = {
        "embedding_ms": 0.0,
        "vector_search_ms": 0.0,
        "embedding_call_count": 0,
        "vector_search_count": 0,
    }
    try:
        search = search_product_evidence(
            product_id,
            " ".join(part for part in query_parts if part),
            db,
            top_k=max(limit, 8),
        )
        shared_hits = search.results
        search_metrics = {
            "embedding_ms": search.embedding_ms,
            "vector_search_ms": search.vector_search_ms,
            "embedding_call_count": search.embedding_call_count,
            "vector_search_count": search.vector_search_count,
        }
    except LookupError:
        shared_hits = []
    retrieval_ms = round((perf_counter() - retrieval_started) * 1000, 3)
    blocks: list[dict] = []
    for item in template:
        candidate = input_found.get(item.label)
        blocks.append(
            {
                "label": item.label,
                "query": item.query,
                "hits": list(shared_hits),
                "input_candidate": candidate,
            }
        )
    return classpath, blocks, {"retrieval_ms": retrieval_ms, **search_metrics}


def assemble_attributes(
    product_id: int,
    classpath: str | None,
    blocks: list[dict],
    llm_result: LLMAttributeExtraction,
    product_description: str = "",
) -> list[ProductAttribute]:
    attributes: list[ProductAttribute] = []
    for block in blocks:
        label = block["label"]
        hits: list[Evidence] = block["hits"]
        slot = _slot_for_label(llm_result, label)
        value = slot.value.strip() if slot and slot.value else None
        uom = slot.uom.strip() if slot and slot.uom else None
        if uom == "":
            uom = None
        title_recovered = False
        if label == "Product Type" and _is_spec_type_code(value):
            recovered = product_type_from_title(product_description, classpath)
            if recovered:
                value = recovered
                title_recovered = True
        if not slot or not slot.supported or not value:
            attributes.append(
                ProductAttribute(
                    label=label,
                    status=STATUS_NOT_FOUND,
                    retrieval_score=hits[0].retrieval_score if hits else 0.0,
                )
            )
            continue
        hit = _best_supporting_hit(value, hits)
        blob = " ".join(item.evidence_text for item in hits if item.evidence_text)
        if label == "Product Type" and product_description:
            blob = f"{product_description} {blob}".strip()
        if not title_recovered and not _evidence_supports_value(value, blob):
            attributes.append(
                ProductAttribute(
                    label=label,
                    status=STATUS_NOT_FOUND,
                    retrieval_score=hits[0].retrieval_score if hits else 0.0,
                )
            )
            continue
        if hit is None and hits:
            hit = hits[0]
        if uom and len(uom) <= 2 and uom.lower() in {"in"}:
            if not any(token in blob.lower() for token in ('"', " in", "inch", "in.")):
                uom = None
        elif uom and not appears_in_input(uom, blob):
            uom = None
        evidence_text = ""
        if slot.evidence_text and appears_in_input(slot.evidence_text, blob) and not title_recovered:
            evidence_text = slot.evidence_text.strip()
        elif title_recovered:
            evidence_text = product_description.strip()
        elif hit:
            evidence_text = (hit.evidence_text or "").strip()
        exactness = _exactness(value, evidence_text or blob)
        retrieval = hit.retrieval_score if hit else (hits[0].retrieval_score if hits else 0.0)
        source_type = hit.source_type if hit else (hits[0].source_type if hits else None)
        attributes.append(
            ProductAttribute(
                label=label,
                value=value,
                uom=uom,
                source_id=hit.source_id if hit else None,
                document_id=hit.document_id if hit else None,
                page=hit.page if hit else None,
                evidence_text=evidence_text or (hit.evidence_text if hit else None),
                confidence=evidence_confidence(
                    source_type=source_type,
                    retrieval_score=retrieval,
                    exactness=exactness,
                ),
                status=STATUS_EXTRACTED,
                retrieval_score=retrieval,
            )
        )
    return attributes


def persist_attributes(db: Session, product_id: int, attributes: list[ProductAttribute]) -> None:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    delete_normalized_attributes(db, product_id)
    db.query(ProductAttributeRecord).filter(
        ProductAttributeRecord.product_id == product_id
    ).delete(synchronize_session=False)
    created = _utcnow()
    for item in attributes:
        db.add(
            ProductAttributeRecord(
                product_id=product_id,
                label=item.label,
                value=item.value,
                uom=item.uom,
                source_id=item.source_id,
                document_id=item.document_id,
                page=item.page,
                evidence_text=item.evidence_text,
                confidence=item.confidence,
                retrieval_score=item.retrieval_score,
                status=item.status,
                created_at=created,
            )
        )
    extracted = any(item.status == STATUS_EXTRACTED for item in attributes)
    product.status = (
        ProductStatus.EXTRACTED.value if extracted else ProductStatus.INSUFFICIENT_EVIDENCE.value
    )
    product.updated_at = created
    db.flush()


def extract_product_attributes(product_id: int, db: Session) -> AttributeExtractionResponse:
    started = perf_counter()
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    document = (
        db.query(ProductDocumentRecord)
        .filter(ProductDocumentRecord.product_id == product_id)
        .one_or_none()
    )
    if document is None:
        raise LookupError(f"Product {product_id} has not been indexed yet")

    classpath, blocks, retrieval_metrics = retrieve_attribute_evidence(product_id, db)
    product_context = (
        f"MPN: {product.mpn}\n"
        f"Title/description: {product.description or ''}\n"
        f"Classification: {classpath or 'unknown'}"
    )
    reset_llm_call_metrics()
    llm_started = perf_counter()
    llm_result = invoke_attribute_llm(
        classpath or "",
        _format_blocks(blocks, product.description or ""),
        product_context=product_context,
    )
    llm_ms = round((perf_counter() - llm_started) * 1000, 3)
    llm_timings = last_llm_call_metrics()
    attributes = assemble_attributes(
        product_id,
        classpath,
        blocks,
        llm_result,
        product_description=product.description or "",
    )
    persist_started = perf_counter()
    persist_attributes(db, product_id, attributes)
    persistence_ms = round((perf_counter() - persist_started) * 1000, 3)
    extracted = any(item.status == STATUS_EXTRACTED for item in attributes)
    metrics = ExtractionMetrics(
        extraction_total_ms=round((perf_counter() - started) * 1000, 3),
        retrieval_ms=float(retrieval_metrics.get("retrieval_ms") or 0.0),
        embedding_ms=float(retrieval_metrics.get("embedding_ms") or 0.0),
        vector_search_ms=float(retrieval_metrics.get("vector_search_ms") or 0.0),
        llm_ms=llm_ms,
        llm_request_ms=llm_timings.llm_request_ms,
        llm_wait_ms=llm_timings.llm_wait_ms,
        llm_cooldown_ms=llm_timings.llm_cooldown_ms,
        llm_attempts=llm_timings.llm_attempts,
        persistence_ms=persistence_ms,
        embedding_call_count=int(retrieval_metrics.get("embedding_call_count") or 0),
        vector_search_count=int(retrieval_metrics.get("vector_search_count") or 0),
        llm_call_count=1,
        attribute_count=len(attributes),
    )
    return AttributeExtractionResponse(
        product_id=product_id,
        status=STATUS_EXTRACTED if extracted else ProductStatus.INSUFFICIENT_EVIDENCE.value,
        classpath=classpath,
        attributes=attributes,
        metrics=metrics,
    )


def get_attributes(product_id: int, db: Session) -> AttributeExtractionResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    rows = (
        db.query(ProductAttributeRecord)
        .filter(ProductAttributeRecord.product_id == product_id)
        .order_by(ProductAttributeRecord.id)
        .all()
    )
    if not rows:
        raise LookupError(f"Product {product_id} has no extracted attributes yet")
    classification = (
        db.query(ProductClassificationRecord)
        .filter(ProductClassificationRecord.product_id == product_id)
        .one_or_none()
    )
    attributes = [
        ProductAttribute(
            label=row.label,
            value=row.value,
            uom=row.uom,
            source_id=row.source_id,
            document_id=row.document_id,
            page=row.page,
            evidence_text=row.evidence_text,
            confidence=row.confidence,
            status=row.status,
            retrieval_score=row.retrieval_score,
        )
        for row in rows
    ]
    extracted = any(item.status == STATUS_EXTRACTED for item in attributes)
    return AttributeExtractionResponse(
        product_id=product_id,
        status=STATUS_EXTRACTED if extracted else ProductStatus.INSUFFICIENT_EVIDENCE.value,
        classpath=classification.classpath if classification else None,
        attributes=attributes,
    )
