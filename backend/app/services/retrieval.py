from __future__ import annotations

from time import perf_counter

from sqlalchemy.orm import Session

from app.database.models import ProductDocumentRecord, ProductRecord
from app.schemas.evidence import Evidence, SearchResponse
from app.services.embeddings import embed_texts
from app.services.qdrant_store import search_product_chunks


def search_product_evidence(
    product_id: int,
    query: str,
    db: Session,
    top_k: int = 5,
) -> SearchResponse:
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

    embed_started = perf_counter()
    vectors = embed_texts([query])
    embedding_ms = round((perf_counter() - embed_started) * 1000, 3)
    search_started = perf_counter()
    hits = search_product_chunks(product_id, vectors[0], top_k=top_k)
    vector_search_ms = round((perf_counter() - search_started) * 1000, 3)
    results: list[Evidence] = []
    for hit in hits:
        text = str(hit.get("text") or "")
        score = float(hit.get("score") or 0.0)
        title = str(hit.get("document_title") or "Manufacturer document")
        results.append(
            Evidence(
                text=text,
                evidence_text=text,
                score=score,
                retrieval_score=score,
                source=title,
                url=str(hit.get("url") or document.url),
                page=hit.get("page"),
                source_id=hit.get("source_id"),
                document_id=hit.get("document_id") or document.id,
                source_type=hit.get("source_type"),
            )
        )
    return SearchResponse(
        product_id=product_id,
        query=query,
        results=results,
        embedding_ms=embedding_ms,
        vector_search_ms=vector_search_ms,
        embedding_call_count=1,
        vector_search_count=1,
    )
