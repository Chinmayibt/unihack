import csv
import io
from unittest.mock import patch

from app.agents.understanding_logic import assemble_understanding, has_brand_conflict
from app.schemas.understanding import LLMProductUnderstanding

HEADERS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]


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


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _upload(client, rows: list[dict[str, str]]):
    return client.post(
        "/upload",
        files={"file": ("sample.csv", _csv_bytes(rows), "text/csv")},
    )


def _diablo_llm(_raw: dict) -> LLMProductUnderstanding:
    return LLMProductUnderstanding(
        product_type="Sanding Belt",
        brand_candidate="Diablo",
        manufacturer_candidate="Freud Inc",
        category_candidates=["Abrasives", "Sanding Belts"],
        extracted_terms=["Diablo", "1/2", "18", "Sanding Belt", "6pc"],
        candidate_attributes={
            "width": "1/2 in",
            "length": "18 in",
            "quantity": "6",
            "voltage": "120 V",
        },
        confidence=0.94,
        reasoning_summary="Description names a Diablo sanding belt with size and pack quantity.",
    )


def test_brand_conflict_when_source_is_placeholder():
    raw = {
        "e1_brand": "-- Unbranded --",
        "unilog_brand": "-- No Unilog Brand --",
        "dib_brand": "-- No DIB Brand --",
    }
    assert has_brand_conflict(raw, "Diablo") is True


def test_no_brand_conflict_when_source_matches():
    raw = {
        "e1_brand": "Diablo",
        "unilog_brand": "-- No Unilog Brand --",
        "dib_brand": "-- No DIB Brand --",
    }
    assert has_brand_conflict(raw, "Diablo") is False


def test_mpn_always_comes_from_source():
    raw = {
        "mpn": "DCB518ASTS06G",
        "description": 'Diablo 1/2"x18" - Sanding Belt 6pc',
        "e1_brand": "-- Unbranded --",
        "unilog_brand": "-- No Unilog Brand --",
        "dib_brand": "-- No DIB Brand --",
        "manufacturer": "Freud Inc (2435)",
    }
    assembled = assemble_understanding(raw, _diablo_llm(raw))
    assert assembled.mpn == "DCB518ASTS06G"
    assert assembled.brand_conflict is True
    assert assembled.source_brand == "-- Unbranded --"
    assert assembled.source_manufacturer == "Freud Inc (2435)"
    assert "voltage" not in assembled.candidate_attributes
    assert assembled.candidate_attributes["quantity"] == "6"


def test_understand_requires_api_key(client):
    _upload(client, [_row()])
    response = client.post("/products/1/understand")
    assert response.status_code == 503


def test_understand_product_persists_without_mutating_source(client):
    _upload(client, [_row()])
    before = client.get("/products/1").json()

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=_diablo_llm):
        response = client.post("/products/1/understand")

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == 1
    assert body["status"] == "UNDERSTOOD"
    understanding = body["understanding"]
    assert understanding["mpn"] == "DCB518ASTS06G"
    assert understanding["product_type"] == "Sanding Belt"
    assert understanding["brand_candidate"] == "Diablo"
    assert understanding["manufacturer_candidate"] == "Freud Inc"
    assert understanding["brand_conflict"] is True
    assert understanding["source_brand"] == "-- Unbranded --"
    assert understanding["candidate_attributes"]["width"] == "1/2 in"
    assert "voltage" not in understanding["candidate_attributes"]

    after = client.get("/products/1").json()
    assert after["mpn"] == before["mpn"]
    assert after["description"] == before["description"]
    assert after["e1_brand"] == "-- Unbranded --"
    assert after["unilog_brand"] == before["unilog_brand"]
    assert after["dib_brand"] == before["dib_brand"]
    assert after["manufacturer"] == before["manufacturer"]
    assert after["status"] == "UNDERSTOOD"

    stored = client.get("/products/1/understanding").json()
    assert stored["understanding"]["brand_candidate"] == "Diablo"
    assert stored["understanding"]["brand_conflict"] is True


def test_understand_tpd_returns_conflict_and_defers_review(client):
    _upload(client, [_row()])
    tpd = RuntimeError(
        "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
        "`openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000. "
        "Please try again in 3m17.856s.'}}"
    )
    with patch("app.agents.graph.invoke_understanding_llm", side_effect=tpd):
        response = client.post("/products/1/understand")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["issue_type"] == "LLM_QUOTA_EXHAUSTED"
    product = client.get("/products/1").json()
    assert product["status"] == "REVIEW_REQUIRED"
    queue = client.get("/review-queue", params={"product_id": 1}).json()
    assert any(item["issue_type"] == "LLM_QUOTA_EXHAUSTED" for item in queue["items"])
    missing = client.get("/products/1/understanding")
    assert missing.status_code == 404


def test_understanding_missing_before_agent_runs(client):
    _upload(client, [_row()])
    response = client.get("/products/1/understanding")
    assert response.status_code == 404


def test_batch_understand(client):
    rows = [
        _row(),
        _row(
            Mfg_Part_Num="49-94-0029",
            Part_Desc='49-94-0029 Milw 6-1/2"x1/8"x5/8" DKO Metal Cut Off Disc',
        ),
    ]
    _upload(client, rows)

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=_diablo_llm):
        response = client.post("/products/understand")

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert {item["understanding"]["mpn"] for item in body["results"]} == {
        "DCB518ASTS06G",
        "49-94-0029",
    }


def test_understanding_cache_returns_without_llm():
    from app.agents.product_understanding import invoke_understanding_llm
    from app.services.cache_store import clear_runtime_caches, put_cached_understanding

    clear_runtime_caches()
    raw = {
        "mpn": "CACHE-MPN",
        "description": "cached sanding belt",
        "manufacturer": "Freud Inc",
        "e1_brand": "",
        "unilog_brand": "",
        "dib_brand": "",
    }
    put_cached_understanding(raw, _diablo_llm(raw).model_dump())
    result = invoke_understanding_llm(raw)
    assert result.product_type == "Sanding Belt"
    assert result.brand_candidate == "Diablo"
