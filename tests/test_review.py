from unittest.mock import patch

import test_attributes
from app.database.connection import get_db
from app.database.models import (
    ProductClassificationRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
    ReviewQueueRecord,
)
from app.schemas.normalized_attribute import CONFLICT, SOURCE_INPUT, SOURCE_MANUFACTURER
from app.services.fetch import FetchedDocument


def _db(client):
    gen = client.app.dependency_overrides[get_db]()
    return next(gen), gen


def _close_db(db, gen) -> None:
    db.close()
    try:
        next(gen)
    except StopIteration:
        pass


def _prepare_normalized_product(client):
    test_attributes._prepare_researched_product(client)
    fetched = FetchedDocument(
        url="https://www.diablotools.com/products/DCB518ASTS06G",
        content_bytes=test_attributes.ATTRIBUTE_HTML.encode("utf-8"),
        content_type="text/html",
        final_url="https://www.diablotools.com/products/DCB518ASTS06G",
    )
    with patch("app.services.indexing.fetch_url", return_value=fetched):
        assert client.post("/products/1/index").status_code == 200
    with patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        assert client.post("/products/1/attributes/extract").status_code == 200
    assert client.post("/products/1/attributes/normalize").status_code == 200


def test_product_one_skips_human_review(client):
    _prepare_normalized_product(client)
    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    body = processed.json()
    assert body["status"] == "PARTIAL"
    assert body["requires_review"] is False
    assert body["approved_for_output"] is True
    assert body["paused"] is False
    assert body["review_id"] is None
    assert body["review_ids"] == []
    assert body["validation"]["issues"] == []

    queue = client.get("/review-queue")
    assert queue.status_code == 200
    assert queue.json()["total"] == 0
    assert queue.json()["items"] == []
    assert client.get("/products/1").json()["status"] == "PARTIAL"


def test_placeholder_brand_is_not_a_review_issue(client):
    _prepare_normalized_product(client)
    assert client.post("/products/1/validate").status_code == 200
    db, gen = _db(client)
    try:
        product = db.get(ProductRecord, 1)
        assert product.e1_brand == "-- Unbranded --"
    finally:
        _close_db(db, gen)
    assert client.get("/review-queue").json()["total"] == 0


def test_width_conflict_review_and_select_candidate(client):
    _prepare_normalized_product(client)
    db, gen = _db(client)
    try:
        row = (
            db.query(ProductNormalizedAttributeRecord)
            .filter(
                ProductNormalizedAttributeRecord.product_id == 1,
                ProductNormalizedAttributeRecord.label == "Width",
            )
            .one()
        )
        row.agreement = CONFLICT
        row.status = "CONFLICT"
        row.normalized_value = None
        row.raw_value = '1/2"'
        row.candidates = [
            {
                "value": '1/2"',
                "source": SOURCE_INPUT,
                "authority": 1.0,
                "evidence_text": "1/2 x 18",
            },
            {
                "value": '3/4"',
                "source": SOURCE_MANUFACTURER,
                "authority": 1.0,
                "evidence_text": "Width: 3/4 in",
                "source_id": row.source_id,
            },
        ]
        db.commit()
    finally:
        _close_db(db, gen)

    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    body = processed.json()
    assert body["status"] == "REVIEW_REQUIRED"
    assert body["requires_review"] is True
    assert body["approved_for_output"] is False
    assert body["paused"] is True
    assert body["review_id"] is not None

    queue = client.get("/review-queue").json()
    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["issue_type"] == "SOURCE_CONFLICT"
    assert item["attribute"] == "Width"
    assert item["severity"] == "HIGH"
    review_id = item["id"]
    assert review_id == body["review_id"]

    detail = client.get(f"/review-queue/{review_id}").json()
    assert detail["product"]["mpn"] == test_attributes.MPN
    assert detail["attribute"] == "Width"
    sources = {candidate["source"] for candidate in detail["candidate_values"]}
    assert SOURCE_INPUT in sources
    assert SOURCE_MANUFACTURER in sources
    assert any("3/4" in (candidate["value"] or "") for candidate in detail["candidate_values"])
    assert any(detail["evidence"])
    assert detail["reason"]

    resolved = client.post(
        f"/review-queue/{review_id}/resolve",
        json={
            "decision": "SELECT_CANDIDATE",
            "selected_value": "3/4",
            "selected_source": "MANUFACTURER",
            "reviewed_by": "qa-reviewer",
            "review_reason": "Manufacturer source is authoritative.",
        },
    )
    assert resolved.status_code == 200
    decision = resolved.json()
    assert decision["decision"] == "SELECT_CANDIDATE"
    assert decision["selected_source"] == "MANUFACTURER"
    assert decision["final_value"] == "3/4"
    assert decision["remaining_reviews"] == 0
    assert decision["product_status"] == "APPROVED"

    saved = client.get(f"/review-queue/{review_id}").json()
    assert saved["status"] == "APPROVED"
    assert saved["ai_value"] == '1/2"'
    assert saved["final_value"] == "3/4"
    assert saved["decision"] == "SELECT_CANDIDATE"
    assert saved["review_reason"] == "Manufacturer source is authoritative."

    normalized = client.get("/products/1/attributes/normalized").json()
    width = next(item for item in normalized["attributes"] if item["label"] == "Width")
    assert width["raw_value"] == '1/2"'
    assert width["normalized_value"] == "3/4"
    assert width["ai_value"] == '1/2"'
    assert width["human_value"] == "3/4"
    assert width["review_decision"] == "SELECT_CANDIDATE"
    assert width["reviewed_by"] == "qa-reviewer"
    assert width["selected_source"] == "MANUFACTURER"

    assert client.get("/review-queue").json()["total"] == 0
    assert client.get("/products/1").json()["status"] == "APPROVED"


def test_real_brand_conflict_goes_to_review(client):
    _prepare_normalized_product(client)
    db, gen = _db(client)
    try:
        product = db.get(ProductRecord, 1)
        product.e1_brand = "Makita"
        db.commit()
    finally:
        _close_db(db, gen)

    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    body = processed.json()
    assert body["status"] == "REVIEW_REQUIRED"
    queue = client.get("/review-queue").json()
    assert queue["total"] >= 1
    assert any(item["issue_type"] == "BRAND_CONFLICT" for item in queue["items"])


def test_low_classification_confidence_goes_to_review(client):
    _prepare_normalized_product(client)
    db, gen = _db(client)
    try:
        record = (
            db.query(ProductClassificationRecord)
            .filter(ProductClassificationRecord.product_id == 1)
            .one()
        )
        record.confidence = 0.58
        record.status = "REVIEW_REQUIRED"
        db.commit()
    finally:
        _close_db(db, gen)

    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "REVIEW_REQUIRED"
    queue = client.get("/review-queue").json()
    assert any(item["issue_type"] == "LOW_CLASSIFICATION_CONFIDENCE" for item in queue["items"])


def test_missing_manufacturer_source_goes_to_review(client):
    _prepare_normalized_product(client)
    db, gen = _db(client)
    try:
        rows = db.query(ProductSourceRecord).filter(ProductSourceRecord.product_id == 1).all()
        for row in rows:
            row.source_type = "RETAILER"
        db.commit()
    finally:
        _close_db(db, gen)

    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "REVIEW_REQUIRED"
    queue = client.get("/review-queue").json()
    assert any(item["issue_type"] == "NO_AUTHORITATIVE_SOURCE" for item in queue["items"])


def test_invalid_lov_goes_to_review(client):
    _prepare_normalized_product(client)
    db, gen = _db(client)
    try:
        row = (
            db.query(ProductNormalizedAttributeRecord)
            .filter(
                ProductNormalizedAttributeRecord.product_id == 1,
                ProductNormalizedAttributeRecord.label == "Abrasive Material",
            )
            .one()
        )
        row.normalized_value = "Purple Magic Material"
        db.commit()
    finally:
        _close_db(db, gen)

    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "REVIEW_REQUIRED"
    queue = client.get("/review-queue").json()
    assert any(item["issue_type"] == "LOV_INVALID" for item in queue["items"])
    lov = next(item for item in queue["items"] if item["issue_type"] == "LOV_INVALID")
    assert lov["normalized_value"] == "Purple Magic Material"
    assert "Aluminum Oxide" in lov["allowed_values"]
    assert lov["source"] == "MANUFACTURER"

    db, gen = _db(client)
    try:
        stale = (
            db.query(ReviewQueueRecord)
            .filter(ReviewQueueRecord.issue_type == "LOV_INVALID")
            .one()
        )
        stale.diagnostics = {}
        db.commit()
        review_id = stale.id
    finally:
        _close_db(db, gen)
    refreshed = client.get("/review-queue").json()
    lov = next(item for item in refreshed["items"] if item["issue_type"] == "LOV_INVALID")
    assert lov["normalized_value"] == "Purple Magic Material"
    assert "Aluminum Oxide" in lov["allowed_values"]
    detail = client.get(f"/review-queue/{review_id}").json()
    assert detail["raw_value"]
    assert "Aluminum Oxide" in detail["allowed_values"]
