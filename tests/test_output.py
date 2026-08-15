import csv
from pathlib import Path

import test_attributes
import test_review
from app.database.models import ProductNormalizedAttributeRecord
from app.schemas.final_output import EXPECTED_OUTPUT_COLUMNS
from app.schemas.normalized_attribute import CONFLICT, SOURCE_INPUT, SOURCE_MANUFACTURER
from app.services.output_contract import empty_output_row, freeze_output_row
from app.services.output_generate import generate_output
from app.services.output_validate import validate_headers

EXPECTED_FILE = Path("/Users/btchinmayi/Projects/unihacks/Unihack_ Expected Output - Delivery Format.csv")


def _prepare_processed(client):
    test_review._prepare_normalized_product(client)
    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    return processed.json()


def test_expected_headers_are_frozen():
    with EXPECTED_FILE.open(newline="", encoding="utf-8-sig") as handle:
        delivery_headers = list(csv.DictReader(handle).fieldnames or [])
    assert EXPECTED_OUTPUT_COLUMNS == delivery_headers
    assert len(EXPECTED_OUTPUT_COLUMNS) == 252
    validate_headers(list(EXPECTED_OUTPUT_COLUMNS))


def test_missing_required_column_fails_loudly():
    row = empty_output_row()
    row.pop("Mfg_Part_Num")
    try:
        freeze_output_row(row)
    except ValueError as exc:
        assert "Mfg_Part_Num" in str(exc)
    else:
        raise AssertionError("missing column should fail")


def test_not_found_uses_approved_empty_value():
    row = empty_output_row()
    row["Mfg_Part_Num"] = "X"
    row["Part_Desc"] = "desc"
    row["ATTRIBUTE_LABEL 6"] = "Grit"
    row["ATTRIBUTE_VALUE 6"] = ""
    frozen = freeze_output_row(row)
    assert frozen["ATTRIBUTE_VALUE 6"] == ""
    assert "NOT_FOUND" not in frozen.values()


def test_product_one_output_contract(client):
    body = _prepare_processed(client)
    assert body["approved_for_output"] is True

    response = client.get("/products/1/output")
    assert response.status_code == 200
    payload = response.json()
    output = payload["output"]
    assert list(output.keys()) == EXPECTED_OUTPUT_COLUMNS
    assert payload["eligible_for_csv"] is True
    assert payload["reviewed"] is False
    assert payload["processing_status"] == "PARTIAL"
    assert output["Mfg_Part_Num"] == test_attributes.MPN
    assert output["MANUFACTURER_PART_NUMBER"] == test_attributes.MPN
    assert output["BRAND_NAME"] == "Diablo"
    assert output["MANUFACTURER_NAME"] == "Freud Inc"
    assert output["Classpath"] == "Abrasives>Sanding Products>Sanding Belts"
    assert output["ATTRIBUTE_LABEL 1"] == "Product Type"
    assert output["ATTRIBUTE_VALUE 1"] == "Sanding Belts"
    assert output["ATTRIBUTE_LABEL 2"] == "Width"
    assert output["ATTRIBUTE_VALUE 2"] == "1/2"
    assert output["ATTRIBUTE_UOM 2"] == "in"
    assert output["WIDTH"] == "1/2"
    assert output["WIDTH_UOM"] == "in"
    assert output["LENGTH"] == "18"
    assert output["LENGTH_UOM"] == "in"
    assert output["Selling Qty"] == "6"
    assert output["Selling UOM"] == "EA"
    assert output["ATTRIBUTE_LABEL 6"] == "Grit"
    assert output["ATTRIBUTE_VALUE 6"] == ""
    assert output["MFR URL"].startswith("https://www.diablotools.com/")

    width_prov = next(item for item in payload["assembled"]["provenance"] if item["label"] == "Width")
    assert width_prov["final_value"] == "1/2"
    assert width_prov["evidence_text"]
    assert width_prov["source_id"] is not None
    assert width_prov["source_url"]


def test_generate_includes_eligible_product_once(client, tmp_path):
    _prepare_processed(client)
    db, gen = test_review._db(client)
    try:
        path = tmp_path / "delivery.csv"
        result = generate_output(db, path)
        assert result.status == "COMPLETED"
        assert result.total_products == 1
        assert result.partial == 1
        assert result.approved == 0
        assert result.review_pending == 0
        assert path.exists()
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert list(reader.fieldnames or []) == EXPECTED_OUTPUT_COLUMNS
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Mfg_Part_Num"] == test_attributes.MPN
        mpns = [row["Mfg_Part_Num"] for row in rows]
        assert len(mpns) == len(set(mpns))
    finally:
        test_review._close_db(db, gen)


def test_review_required_is_not_written_to_csv(client, tmp_path):
    test_review._prepare_normalized_product(client)
    db, gen = test_review._db(client)
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
            {"value": '1/2"', "source": SOURCE_INPUT, "authority": 1.0, "evidence_text": "1/2 x 18"},
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
        test_review._close_db(db, gen)

    processed = client.post("/products/1/process")
    assert processed.json()["status"] == "REVIEW_REQUIRED"
    assert client.get("/products/1").json()["status"] == "REVIEW_REQUIRED"

    output = client.get("/products/1/output").json()
    assert output["eligible_for_csv"] is False
    assert output["eligibility_reason"] == "review_pending"
    assert output["approved_for_output"] is False

    db, gen = test_review._db(client)
    try:
        path = tmp_path / "delivery.csv"
        result = generate_output(db, path)
        assert result.status == "COMPLETED"
        assert result.review_pending == 1
        assert result.approved == 0
        assert result.partial == 0
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows == []
    finally:
        test_review._close_db(db, gen)


def test_human_override_is_final_value_with_ai_audit(client):
    test_review._prepare_normalized_product(client)
    db, gen = test_review._db(client)
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
            {"value": '1/2"', "source": SOURCE_INPUT, "authority": 1.0, "evidence_text": "1/2 x 18"},
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
        test_review._close_db(db, gen)

    processed = client.post("/products/1/process")
    review_id = processed.json()["review_id"]
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

    payload = client.get("/products/1/output").json()
    assert payload["reviewed"] is True
    assert payload["eligible_for_csv"] is True
    assert payload["output"]["ATTRIBUTE_VALUE 2"] == "3/4"
    assert payload["output"]["WIDTH"] == "3/4"
    assert payload["output"]["WIDTH_UOM"] == "in"
    width_prov = next(item for item in payload["assembled"]["provenance"] if item["label"] == "Width")
    assert width_prov["ai_value"] == '1/2"'
    assert width_prov["human_value"] == "3/4"
    assert width_prov["final_value"] == "3/4"
    assert width_prov["review_decision"] == "SELECT_CANDIDATE"


def test_output_generate_api(client):
    _prepare_processed(client)
    response = client.post("/output/generate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["total_products"] == 1
    assert body["partial"] == 1
    assert body["output_file"]
    path = Path(body["output_file"])
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert list(reader.fieldnames or []) == EXPECTED_OUTPUT_COLUMNS
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["ATTRIBUTE_VALUE 2"] == "1/2"
    assert rows[0]["ATTRIBUTE_UOM 2"] == "in"
