from __future__ import annotations

from time import perf_counter

from sqlalchemy.orm import Session

from app.database.models import (
    EntityResolutionRecord,
    ProductAttributeRecord,
    ProductDocumentRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
    ProductUnderstandingRecord,
    ProductValidationRecord,
)
from app.models.product import ProductStatus
from app.schemas.document import IndexResponse
from app.schemas.source import SOURCE_MANUFACTURER
from app.services.cache_store import fetch_url_cached
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts
from app.services.extract import extract_fetched
from app.services.fetch import fetch_url  # noqa: F401  — kept for test patches
from app.services.qdrant_store import delete_product_vectors, upsert_chunks


def top_manufacturer_source(db: Session, product_id: int) -> ProductSourceRecord | None:
    rows = (
        db.query(ProductSourceRecord)
        .filter(ProductSourceRecord.product_id == product_id)
        .order_by(
            ProductSourceRecord.authority_score.desc(),
            ProductSourceRecord.relevance_score.desc(),
        )
        .all()
    )
    for row in rows:
        if row.source_type == SOURCE_MANUFACTURER:
            return row
    return None


def _context(db: Session, product: ProductRecord) -> dict:
    understanding = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product.id)
        .one_or_none()
    )
    entity_rows = (
        db.query(EntityResolutionRecord)
        .filter(EntityResolutionRecord.product_id == product.id)
        .all()
    )
    by_type = {row.entity_type: row for row in entity_rows}
    brand = None
    manufacturer = product.manufacturer
    if "brand" in by_type and by_type["brand"].canonical:
        brand = by_type["brand"].canonical
    elif understanding:
        brand = understanding.brand_candidate
    if "manufacturer" in by_type and by_type["manufacturer"].canonical:
        manufacturer = by_type["manufacturer"].canonical
    return {
        "mpn": product.mpn,
        "brand": brand,
        "manufacturer": manufacturer,
    }


def index_manufacturer_document(product_id: int, db: Session, fetched=None) -> IndexResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")

    source = top_manufacturer_source(db, product_id)
    if source is None:
        return IndexResponse(
            product_id=product_id,
            status="NO_MANUFACTURER_SOURCE",
            documents_processed=0,
            chunks_created=0,
            vectors_created=0,
        )

    fetch_ms = extract_ms = chunk_ms = embedding_ms = qdrant_ms = 0.0
    fetch_started = perf_counter()
    try:
        fetched_doc = fetched or fetch_url_cached(source.url, db, fetcher=fetch_url)
        fetch_ms = round((perf_counter() - fetch_started) * 1000, 3)
        extract_started = perf_counter()
        extracted = extract_fetched(
            fetched_doc.content_bytes, fetched_doc.content_type, fetched_doc.final_url
        )
        extract_ms = round((perf_counter() - extract_started) * 1000, 3)
    except Exception:
        if not fetch_ms:
            fetch_ms = round((perf_counter() - fetch_started) * 1000, 3)
        return IndexResponse(
            product_id=product_id,
            status="FETCH_FAILED",
            documents_processed=0,
            chunks_created=0,
            vectors_created=0,
            source_url=source.url,
            fetch_ms=fetch_ms,
            extract_ms=extract_ms,
        )

    existing = (
        db.query(ProductDocumentRecord)
        .filter(ProductDocumentRecord.product_id == product_id)
        .one_or_none()
    )
    if (
        existing
        and extracted.content.strip()
        and existing.content == extracted.content
        and product.status == ProductStatus.INDEXED.value
    ):
        return IndexResponse(
            product_id=product_id,
            status="INDEXED",
            documents_processed=0,
            chunks_created=0,
            vectors_created=0,
            source_url=existing.url,
            fetch_ms=fetch_ms,
            extract_ms=extract_ms,
        )

    if not extracted.content.strip():
        return IndexResponse(
            product_id=product_id,
            status="EMPTY_DOCUMENT",
            documents_processed=0,
            chunks_created=0,
            vectors_created=0,
            source_url=source.url,
            fetch_ms=fetch_ms,
            extract_ms=extract_ms,
        )

    from app.services.review import delete_pending_reviews

    delete_pending_reviews(db, product_id)
    db.query(ProductValidationRecord).filter(
        ProductValidationRecord.product_id == product_id
    ).delete(synchronize_session=False)
    db.query(ProductNormalizedAttributeRecord).filter(
        ProductNormalizedAttributeRecord.product_id == product_id
    ).delete(synchronize_session=False)
    db.query(ProductAttributeRecord).filter(
        ProductAttributeRecord.product_id == product_id
    ).delete(synchronize_session=False)
    db.query(ProductDocumentRecord).filter(
        ProductDocumentRecord.product_id == product_id
    ).delete(synchronize_session=False)
    record = ProductDocumentRecord(
        product_id=product_id,
        source_id=source.id,
        url=fetched_doc.final_url or source.url,
        title=extracted.title[:512],
        document_type=extracted.document_type or source.content_type,
        content=extracted.content,
        page_count=extracted.page_count,
        links=extracted.links,
    )
    db.add(record)
    db.flush()

    chunk_started = perf_counter()
    chunks = chunk_text(extracted.content)
    chunk_ms = round((perf_counter() - chunk_started) * 1000, 3)
    context = _context(db, product)
    payloads = [
        {
            "product_id": product_id,
            "document_id": record.id,
            "source_id": source.id,
            "mpn": context["mpn"],
            "manufacturer": context["manufacturer"],
            "brand": context["brand"],
            "source_type": source.source_type,
            "content_type": source.content_type,
            "url": record.url,
            "document_title": record.title,
            "page": chunk.page,
            "text": chunk.text,
            "chunk_index": chunk.index,
        }
        for chunk in chunks
    ]
    delete_product_vectors(product_id)
    embed_started = perf_counter()
    vectors = embed_texts([chunk.text for chunk in chunks])
    embedding_ms = round((perf_counter() - embed_started) * 1000, 3)
    qdrant_started = perf_counter()
    stored = upsert_chunks(vectors, payloads)
    qdrant_ms = round((perf_counter() - qdrant_started) * 1000, 3)

    product.status = ProductStatus.INDEXED.value
    db.flush()
    return IndexResponse(
        product_id=product_id,
        documents_processed=1,
        chunks_created=len(chunks),
        vectors_created=stored,
        status="INDEXED",
        source_url=record.url,
        fetch_ms=fetch_ms,
        extract_ms=extract_ms,
        chunk_ms=chunk_ms,
        embedding_ms=embedding_ms,
        qdrant_ms=qdrant_ms,
        embed_ms=embedding_ms,
    )
