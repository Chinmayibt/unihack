import csv
import io
from unittest.mock import patch

from app.schemas.understanding import LLMProductUnderstanding
from app.services.entity_matching import CatalogEntry, match_against_catalog
from app.services.entity_normalize import normalize_entity_name
from app.services.entity_resolution import resolve_brand, resolve_manufacturer

HEADERS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]


def _freud_catalog() -> list[CatalogEntry]:
    return [
        CatalogEntry(
            canonical_name="Freud Inc",
            normalized_name="freud inc",
            aliases=["Freud Inc (2435)"],
        )
    ]


def _brand_catalog() -> list[CatalogEntry]:
    return [
        CatalogEntry(canonical_name="Diablo", normalized_name="diablo", aliases=["DIABLO"]),
        CatalogEntry(canonical_name="Acme", normalized_name="acme", aliases=[]),
        CatalogEntry(canonical_name="Globex", normalized_name="globex", aliases=[]),
    ]


def test_normalize_legal_suffix_and_punctuation():
    assert normalize_entity_name("Freud Inc") == "freud inc"
    assert normalize_entity_name("Freud Inc.") == "freud inc"
    assert normalize_entity_name("Freud, Inc.") == "freud inc"
    assert normalize_entity_name("FREUD INC") == "freud inc"
    assert normalize_entity_name("Freud Incorporated") == "freud inc"
    assert normalize_entity_name("Freud Inc (2435)") == "freud inc"


def test_exact_match_freud_inc():
    match = match_against_catalog("Freud Inc", _freud_catalog())
    assert match.canonical == "Freud Inc"
    assert match.method == "exact"
    assert match.status == "RESOLVED"
    assert match.confidence == 1.0


def test_formatting_difference_freud_comma_inc():
    match = match_against_catalog("Freud, Inc.", _freud_catalog())
    assert match.canonical == "Freud Inc"
    assert match.method == "normalized_exact_match"
    assert match.status == "RESOLVED"


def test_case_difference_freud_inc():
    match = match_against_catalog("FREUD INC", _freud_catalog())
    assert match.canonical == "Freud Inc"
    assert match.method == "normalized_exact_match"
    assert match.status == "RESOLVED"


def test_rapidfuzz_freud_incorporated():
    match = match_against_catalog("Freud Incorporated", _freud_catalog())
    assert match.canonical == "Freud Inc"
    assert match.status == "RESOLVED"
    assert match.method in {"normalized_exact_match", "rapidfuzz"}


def test_brand_inside_description():
    raw = {
        "e1_brand": "-- Unbranded --",
        "unilog_brand": "-- No Unilog Brand --",
        "dib_brand": "-- No DIB Brand --",
    }
    understanding = {"brand_candidate": "Diablo", "brand_conflict": True}
    match = resolve_brand(raw, understanding, _brand_catalog())
    assert match.candidate == "Diablo"
    assert match.canonical == "Diablo"
    assert match.method == "description_match"
    assert match.status == "RESOLVED"


def test_unbranded_input_without_candidate():
    raw = {"e1_brand": "-- Unbranded --"}
    match = resolve_brand(raw, {}, _brand_catalog())
    assert match.canonical is None
    assert match.status == "REVIEW_REQUIRED"
    assert match.method == "missing"


def test_unknown_brand_requires_review():
    match = match_against_catalog("SomeRandomBrand", _brand_catalog())
    assert match.canonical is None
    assert match.status == "REVIEW_REQUIRED"
    assert match.method == "unknown_entity"
    assert match.confidence == 0.71


def test_conflicting_source_and_description_brands():
    raw = {"e1_brand": "Acme"}
    understanding = {"brand_candidate": "Globex", "brand_conflict": True}
    match = resolve_brand(raw, understanding, _brand_catalog())
    assert match.status == "REVIEW_REQUIRED"
    assert match.method == "brand_conflict"
    assert match.canonical is None


def test_missing_manufacturer():
    match = resolve_manufacturer({"manufacturer": None}, {}, _freud_catalog())
    assert match.candidate is None
    assert match.canonical is None
    assert match.method == "missing"
    assert match.status == "REVIEW_REQUIRED"


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _diablo_llm(_raw: dict) -> LLMProductUnderstanding:
    return LLMProductUnderstanding(
        product_type="Sanding Belt",
        brand_candidate="Diablo",
        manufacturer_candidate="Freud Inc",
        category_candidates=["Abrasives"],
        extracted_terms=["Diablo", "Sanding Belt"],
        candidate_attributes={"quantity": "6"},
        confidence=0.94,
        reasoning_summary="Diablo sanding belt from description.",
    )


def test_resolve_api_for_product_one(client):
    rows = [
        {
            "Mfg_Part_Num": "DCB518ASTS06G",
            "Part_Desc": 'DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc',
            "E1_Brand": "-- Unbranded --",
            "Unilog_Brand": "-- No Unilog Brand --",
            "DIB_Brand": "-- No DIB Brand --",
            "Part_Manuf": "Freud Inc (2435)",
        }
    ]
    upload = client.post("/upload", files={"file": ("sample.csv", _csv_bytes(rows), "text/csv")})
    assert upload.status_code == 200

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=_diablo_llm):
        understood = client.post("/products/1/understand")
    assert understood.status_code == 200

    before = client.get("/products/1").json()
    resolved = client.post("/products/1/resolve")
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["product_id"] == 1
    assert body["status"] == "RESOLVED"
    assert body["brand"]["candidate"] == "Diablo"
    assert body["brand"]["canonical"] == "Diablo"
    assert body["brand"]["method"] == "description_match"
    assert body["brand"]["status"] == "RESOLVED"
    assert body["manufacturer"]["canonical"] == "Freud Inc"
    assert body["manufacturer"]["status"] == "RESOLVED"
    assert body["manufacturer"]["method"] in {"exact", "normalized_exact_match"}
    assert body["brand_conflict"] is True
    assert body["conflict_resolved"] is True

    stored = client.get("/products/1/entities").json()
    assert stored["brand"]["canonical"] == "Diablo"
    assert stored["manufacturer"]["canonical"] == "Freud Inc"
    assert stored["brand_conflict"] is True
    assert stored["conflict_resolved"] is True

    after = client.get("/products/1").json()
    assert after["e1_brand"] == before["e1_brand"] == "-- Unbranded --"
    assert after["manufacturer"] == "Freud Inc (2435)"
    assert after["mpn"] == "DCB518ASTS06G"
    assert after["status"] == "RESOLVED"
