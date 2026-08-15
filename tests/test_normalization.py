from unittest.mock import patch

import test_attributes
from app.schemas.normalized_attribute import (
    AGREEMENT,
    CONFLICT,
    INPUT_SOURCED,
    SECONDARY_SOURCE_ONLY,
    SOURCE_INPUT,
    SOURCE_MANUFACTURER,
    SOURCE_MARKETPLACE,
    EvidenceCandidate,
)
from app.services.evidence_consolidation import consolidate_label
from app.services.fetch import FetchedDocument
from app.services.standards import canonical_uom
from app.services.value_normalize import normalize_raw, to_approved_fraction
from app.services.value_parse import parse_input_candidates, split_value_and_uom


def test_split_quoted_inch():
    value, uom = split_value_and_uom('1/2"')
    assert value == "1/2"
    assert uom == '"'
    assert canonical_uom(uom) == "in"


def test_fraction_24_25_becomes_mixed_number():
    value, method = to_approved_fraction("24.25")
    assert value == "24-1/4"
    assert method == "FRACTION"
    assert to_approved_fraction("0.5") == ("1/2", "FRACTION")
    assert to_approved_fraction("18") == ("18", None)


def test_normalize_width_and_quantity():
    width = normalize_raw('1/2"', None, "Width")
    assert width.normalized_value == "1/2"
    assert width.normalized_uom == "in"
    assert width.raw_value == '1/2"'
    assert "UOM_STANDARD" in "+".join(width.methods)

    qty = normalize_raw("6pc", None, "Quantity")
    assert qty.normalized_value == "6"
    assert qty.normalized_uom == "EA"

    material = normalize_raw("aluminum oxide blend", None, "Abrasive Material")
    assert material.normalized_value == "Aluminum Oxide"
    assert "LOV" in material.methods

    product_type = normalize_raw(
        "Metal Cut Off Wheel",
        None,
        "Product Type",
        "Abrasives>Cutting Products>Cut-Off Discs",
    )
    assert product_type.normalized_value == "Cut-Off Discs"
    default_material = normalize_raw("Aluminum Oxide", None, "Material")
    assert default_material.normalized_value == "Aluminum Oxide"
    assert normalize_raw("aluminum oxide", None, "Material").normalized_value == "Aluminum Oxide"
    assert normalize_raw("aluminum oxide grain", None, "Material").normalized_value == (
        "Aluminum Oxide"
    )
    assert normalize_raw("ceramic blend", None, "Material").normalized_value == "Ceramic"
    masonry = normalize_raw(
        "Masonry Cut Off Wheel",
        None,
        "Product Type",
        "Abrasives>Cutting Products>Cut-Off Discs",
    )
    assert masonry.normalized_value == "Cut-Off Discs"
    type_code = normalize_raw(
        "Type 1",
        None,
        "Product Type",
        "Abrasives>Cutting Products>Cut-Off Discs",
    )
    assert type_code.normalized_value == "Type 1"
    assert "LOV" not in "+".join(type_code.methods)
    zirconia = normalize_raw("zirconia grain", None, "Abrasive Material")
    assert zirconia.normalized_value == "zirconia grain"
    assert normalize_raw("Bonded Abrasive", None, "Material").normalized_value == "Bonded Abrasive"
    assert normalize_raw("metal", None, "Material").normalized_value == "metal"


def test_input_parser_reads_size_and_quantity():
    parsed = parse_input_candidates(
        'DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc'
    )
    assert parsed["Width"]["value"] == "1/2"
    assert parsed["Length"]["value"] == "18"
    assert parsed["Quantity"]["value"] == "6pc"
    assert parsed["Quantity"]["evidence_text"] == "6pc"
    assert "Grit" not in parsed


def test_agreement_and_input_sourced_quantity():
    classpath = "Abrasives>Sanding Products>Sanding Belts"
    _, selected, agreement = consolidate_label(
        "Width",
        input_hit=EvidenceCandidate(value='1/2"', source=SOURCE_INPUT, authority=1.0),
        manufacturer_hit=EvidenceCandidate(
            value='1/2"', source=SOURCE_MANUFACTURER, authority=1.0
        ),
        secondary_hits=[],
        classpath=classpath,
    )
    assert agreement == AGREEMENT
    assert selected is not None and selected.source == SOURCE_MANUFACTURER

    _, selected_qty, qty_agreement = consolidate_label(
        "Quantity",
        input_hit=EvidenceCandidate(value="6pc", source=SOURCE_INPUT, authority=1.0),
        manufacturer_hit=None,
        secondary_hits=[],
        classpath=classpath,
    )
    assert qty_agreement == INPUT_SOURCED
    assert selected_qty is not None and selected_qty.value == "6pc"

    _, selected_grit, grit_agreement = consolidate_label(
        "Grit",
        input_hit=None,
        manufacturer_hit=None,
        secondary_hits=[
            EvidenceCandidate(
                value="50/80/120",
                source=SOURCE_MARKETPLACE,
                authority=0.2,
                evidence_text="50/80/120-Grit Multi-Grade",
            )
        ],
        classpath=classpath,
    )
    assert grit_agreement == SECONDARY_SOURCE_ONLY
    assert selected_grit is None

    _, selected_conflict, conflict = consolidate_label(
        "Quantity",
        input_hit=EvidenceCandidate(value="6pc", source=SOURCE_INPUT, authority=1.0),
        manufacturer_hit=EvidenceCandidate(
            value="10", uom="pc", source=SOURCE_MANUFACTURER, authority=1.0
        ),
        secondary_hits=[],
        classpath=classpath,
    )
    assert conflict == CONFLICT
    assert selected_conflict is None


def test_normalize_api_combines_input_and_manufacturer(client):
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

    response = client.post("/products/1/attributes/normalize")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NORMALIZED"
    assert body["completeness"] == "PARTIAL"
    assert body["requires_review"] is False
    assert "Grit" in body["missing_attributes"]
    assert "Backing Material" in body["missing_attributes"]
    by_label = {item["label"]: item for item in body["attributes"]}

    assert by_label["Width"]["normalized_value"] == "1/2"
    assert by_label["Width"]["normalized_uom"] == "in"
    assert by_label["Width"]["agreement"] == AGREEMENT
    assert by_label["Length"]["normalized_value"] == "18"
    assert by_label["Length"]["normalized_uom"] == "in"
    assert by_label["Quantity"]["raw_value"] == "6pc"
    assert by_label["Quantity"]["normalized_value"] == "6"
    assert by_label["Quantity"]["normalized_uom"] == "EA"
    assert by_label["Quantity"]["agreement"] == INPUT_SOURCED
    assert by_label["Quantity"]["selected_source"] == SOURCE_INPUT
    assert by_label["Abrasive Material"]["normalized_value"] == "Aluminum Oxide"
    assert by_label["Grit"]["normalized_value"] is None
    assert by_label["Grit"]["status"] == "NOT_FOUND"

    product = client.get("/products/1").json()
    assert product["status"] == "NORMALIZED"
    saved = client.get("/products/1/attributes/normalized")
    assert saved.status_code == 200
    assert saved.json()["status"] == "NORMALIZED"
