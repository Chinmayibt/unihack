import csv
import io
from pathlib import Path

from app.services.ingestion import parse_and_validate, read_csv_bytes

HEADERS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]

SAMPLE_CSV = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "input"
    / "Unihack_Sample_Dataset_Input.csv"
)


def _row(**overrides) -> dict[str, str]:
    base = {
        "Mfg_Part_Num": "DCB518ASTS06G",
        "Part_Desc": 'DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc',
        "E1_Brand": "-- Unbranded --",
        "Unilog_Brand": "-- No Unilog Brand --",
        "DIB_Brand": "-- No DIB Brand --",
        "Part_Manuf": "Freud Inc (2435)",
    }
    base.update(overrides)
    return base


def _csv_bytes(rows: list[dict[str, str]], headers: list[str] | None = None) -> bytes:
    fieldnames = headers or HEADERS
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _upload(client, content: bytes, filename: str = "sample.csv"):
    return client.post(
        "/upload",
        files={"file": (filename, content, "text/csv")},
    )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_valid_csv_ingests_200_products(client):
    rows = [
        _row(
            Mfg_Part_Num=f"MPN-{i:03d}",
            Part_Desc=f"Product {i} 1/2\" belt",
        )
        for i in range(1, 201)
    ]

    response = _upload(client, _csv_bytes(rows))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["total_rows"] == 200
    assert body["valid_rows"] == 200
    assert body["invalid_rows"] == 0
    assert body["job_id"]

    products = client.get("/products").json()
    assert len(products) == 200
    first = client.get("/products/1").json()
    assert first["id"] == 1
    assert first["mpn"] == "MPN-001"
    assert first["status"] == "INGESTED"
    assert first["manufacturer"] == "Freud Inc (2435)"


def test_missing_column_returns_error(client):
    headers = [column for column in HEADERS if column != "Part_Desc"]
    response = _upload(client, _csv_bytes([_row()], headers=headers))
    assert response.status_code == 400
    assert "Part_Desc" in response.json()["detail"]


def test_missing_mpn_is_invalid(client):
    rows = [_row(), _row(Mfg_Part_Num="", Part_Desc="Missing MPN row")]
    response = _upload(client, _csv_bytes(rows))
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 2
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 1
    assert body["missing_mpn"] == 1
    assert any(
        error["row"] == 2 and "Mfg_Part_Num is missing" in error["error"]
        for error in body["errors"]
    )

    products = client.get("/products").json()
    assert len(products) == 1
    assert products[0]["mpn"] == "DCB518ASTS06G"


def test_duplicate_mpn_is_marked_candidate(client):
    rows = [
        _row(Mfg_Part_Num="DCB518ASTS06G", Part_Desc="First copy"),
        _row(Mfg_Part_Num="DCB518ASTS06G", Part_Desc="Second copy"),
        _row(Mfg_Part_Num="UNIQUE-001", Part_Desc="Unique product"),
    ]
    response = _upload(client, _csv_bytes(rows))
    assert response.status_code == 200
    body = response.json()
    assert body["valid_rows"] == 3
    assert body["invalid_rows"] == 0
    assert body["duplicate_mpns"] == 1

    products = {item["mpn"]: item for item in client.get("/products").json()}
    duplicates = [
        item
        for item in client.get("/products").json()
        if item["mpn"] == "DCB518ASTS06G"
    ]
    assert len(duplicates) == 2
    assert {item["status"] for item in duplicates} == {"DUPLICATE_CANDIDATE"}
    assert products["UNIQUE-001"]["status"] == "INGESTED"


def test_empty_brand_placeholders_are_preserved(client):
    response = _upload(client, _csv_bytes([_row()]))
    assert response.status_code == 200
    product = client.get("/products/1").json()
    assert product["e1_brand"] == "-- Unbranded --"
    assert product["unilog_brand"] == "-- No Unilog Brand --"
    assert product["dib_brand"] == "-- No DIB Brand --"
    assert product["status"] == "INGESTED"


def test_special_characters_survive_ingestion(client):
    description = '1/2"x18" - Sanding Belt 6pc & Finishing® Kit™'
    response = _upload(
        client,
        _csv_bytes([_row(Mfg_Part_Num="SPEC-001", Part_Desc=description)]),
    )
    assert response.status_code == 200
    product = client.get("/products/1").json()
    assert product["description"] == description
    assert '"' in product["description"]
    assert "®" in product["description"]
    assert "™" in product["description"]
    assert "&" in product["description"]


def test_non_csv_is_rejected(client):
    response = _upload(client, b"not a csv", filename="notes.txt")
    assert response.status_code == 400
    assert response.json()["detail"] == "File must be a CSV"


def test_missing_product_returns_404(client):
    response = client.get("/products/999")
    assert response.status_code == 404


def test_sample_dataset_ingests_when_present(client):
    if not SAMPLE_CSV.exists():
        return

    response = _upload(
        client,
        SAMPLE_CSV.read_bytes(),
        filename="Unihack_Sample_Dataset_Input.csv",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["total_rows"] == 1000
    assert body["valid_rows"] == 1000
    assert body["invalid_rows"] == 0
    assert body["duplicate_mpns"] == 1

    first = client.get("/products/1").json()
    assert first["mpn"] == "DCB518ASTS06G"
    assert first["manufacturer"] == "Freud Inc (2435)"
    assert '1/2"' in first["description"]


def test_parse_and_validate_reports_row_errors():
    csv_bytes = _csv_bytes(
        [
            _row(Mfg_Part_Num="OK-1"),
            _row(Mfg_Part_Num="", Part_Desc=""),
        ]
    )
    batch = parse_and_validate(read_csv_bytes(csv_bytes))
    assert batch.stats.total_rows == 2
    assert batch.stats.valid_rows == 1
    assert len(batch.products) == 1
    assert batch.stats.invalid_rows == 1
    assert "Mfg_Part_Num is missing" in batch.errors[0].error
    assert "Part_Desc is missing" in batch.errors[0].error
