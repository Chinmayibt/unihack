from sqlalchemy.orm import Session

from app.agents.graph import build_understanding_graph
from app.agents.product_understanding import MissingLLMConfigError
from app.agents.state import empty_product_state
from app.database.models import ProductRecord, ProductUnderstandingRecord
from app.models.product import ProductStatus
from app.schemas.understanding import (
    BatchUnderstandResponse,
    ProductUnderstanding,
    UnderstandResponse,
)
from app.services.llm_retry import is_daily_token_limit
from app.services.review import defer_llm_quota_exhausted
from app.services.text_display import preserve_display_text


class ProductNotFoundError(LookupError):
    pass


class UnderstandingNotFoundError(LookupError):
    pass


class LlmQuotaExhaustedError(RuntimeError):
    pass


def _to_response(product: ProductRecord, payload: dict) -> UnderstandResponse:
    understanding = ProductUnderstanding.model_validate(
        {**payload, "mpn": product.mpn}
    )
    return UnderstandResponse(
        product_id=product.id,
        status=product.status,
        understanding=understanding,
    )


def understand_product(product_id: int, db: Session) -> UnderstandResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise ProductNotFoundError(f"Product {product_id} not found")

    snapshot = {
        "mpn": product.mpn,
        "description": product.description,
        "e1_brand": product.e1_brand,
        "unilog_brand": product.unilog_brand,
        "dib_brand": product.dib_brand,
        "manufacturer": product.manufacturer,
    }

    graph = build_understanding_graph(db)
    result = graph.invoke(empty_product_state(product_id))
    errors = result.get("errors") or []
    if errors:
        db.rollback()
        wrapped = RuntimeError(errors[0])
        if is_daily_token_limit(wrapped):
            defer_llm_quota_exhausted(
                db, product_id, message=str(wrapped), stage="understanding"
            )
            db.commit()
            raise LlmQuotaExhaustedError(errors[0])
        raise wrapped

    db.commit()
    db.refresh(product)

    for field, value in snapshot.items():
        if getattr(product, field) != value:
            raise RuntimeError(f"Source field {field} was mutated during understanding")

    return _to_response(product, result["understanding"])


def get_understanding(product_id: int, db: Session) -> UnderstandResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise ProductNotFoundError(f"Product {product_id} not found")

    record = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product_id)
        .one_or_none()
    )
    if record is None:
        raise UnderstandingNotFoundError(
            f"Product {product_id} has not been understood yet"
        )

    payload = {
        "mpn": product.mpn,
        "product_type": preserve_display_text(record.product_type),
        "brand_candidate": preserve_display_text(record.brand_candidate),
        "manufacturer_candidate": preserve_display_text(record.manufacturer_candidate),
        "category_candidates": record.category_candidates or [],
        "extracted_terms": record.extracted_terms or [],
        "candidate_attributes": record.candidate_attributes or {},
        "confidence": record.confidence,
        "reasoning_summary": record.reasoning_summary,
        "source_brand": record.source_brand,
        "source_manufacturer": record.source_manufacturer,
        "brand_conflict": record.brand_conflict,
    }
    return _to_response(product, payload)


def understand_products(
    db: Session,
    skip: int = 0,
    limit: int | None = None,
    force: bool = False,
) -> BatchUnderstandResponse:
    query = db.query(ProductRecord).order_by(ProductRecord.id)
    if not force:
        query = query.filter(
            ProductRecord.status.in_(
                [
                    ProductStatus.INGESTED.value,
                    ProductStatus.DUPLICATE_CANDIDATE.value,
                ]
            )
        )
    query = query.offset(skip)
    if limit is not None:
        query = query.limit(limit)

    products = query.all()
    results: list[UnderstandResponse] = []
    errors: list[dict[str, str]] = []

    for product in products:
        try:
            results.append(understand_product(product.id, db))
        except MissingLLMConfigError:
            raise
        except Exception as exc:
            db.rollback()
            errors.append({"product_id": str(product.id), "error": str(exc)})

    return BatchUnderstandResponse(
        status="success" if not errors else "partial",
        total=len(products),
        processed=len(products),
        succeeded=len(results),
        failed=len(errors),
        results=results,
        errors=errors,
    )
