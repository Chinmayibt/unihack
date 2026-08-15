from app.database.models import TaxonomyRecord
from app.services.classification import classify_against_taxonomy


def _node(**overrides) -> TaxonomyRecord:
    defaults = {
        "department": "Abrasives",
        "class_name": "Sanding Products",
        "fine": "Sanding Belts",
        "classpath": "Abrasives>Sanding Products>Sanding Belts",
        "aliases": ["Sanding Belt", "Abrasive Belt"],
    }
    defaults.update(overrides)
    return TaxonomyRecord(**defaults)


def _abrasive_nodes() -> list[TaxonomyRecord]:
    return [
        _node(),
        _node(
            class_name="Cutting Products",
            fine="Cut-Off Discs",
            classpath="Abrasives>Cutting Products>Cut-Off Discs",
            aliases=[
                "Cut Off Disc",
                "Cut-Off Disc",
                "Cut Off Wheel",
                "Metal Cut Off Disc",
                "Masonry Cut Off Wheel",
            ],
        ),
        _node(
            class_name="Grinding Products",
            fine="Grinding Wheels",
            classpath="Abrasives>Grinding Products>Grinding Wheels",
            aliases=["Grinding Wheel", "Metal Grinding Wheel"],
        ),
    ]


def test_exact_product_type_maps_to_allowed_taxonomy():
    nodes = [
        _node(),
        _node(
            department="Appliances",
            class_name="Large Appliances",
            fine="Dishwashers",
            classpath="Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers",
            aliases=["Dishwasher"],
        ),
    ]
    result = classify_against_taxonomy(
        {"id": 1, "description": 'Diablo 1/2"x18" - Sanding Belt 6pc', "mpn": "DCB518ASTS06G"},
        {"product_type": "Sanding Belt", "extracted_terms": ["Sanding Belt"], "category_candidates": ["Abrasives"]},
        nodes,
    )
    assert result.classpath == "Abrasives>Sanding Products>Sanding Belts"
    assert result.fine == "Sanding Belts"
    assert result.department == "Abrasives"
    assert result.class_name == "Sanding Products"
    assert result.status == "CLASSIFIED"
    assert result.method in {"exact", "normalized_exact"}
    assert result.confidence >= 0.9
    assert result.confidence < 1.0
    assert "Sanding Belt" in (result.reasoning_summary or "")
    assert "SandingBelt" not in (result.reasoning_summary or "")


def test_classifier_does_not_invent_outside_taxonomy():
    nodes = [
        _node(
            department="Appliances",
            class_name="Large Appliances",
            fine="Dishwashers",
            classpath="Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers",
            aliases=["Dishwasher"],
        )
    ]
    result = classify_against_taxonomy(
        {"id": 2, "description": "SomeRandomWidget XYZ", "mpn": "XYZ"},
        {"product_type": "SomeRandomWidget", "extracted_terms": [], "category_candidates": []},
        nodes,
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.classpath is None or result.classpath == nodes[0].classpath
    if result.classpath is None:
        assert result.method == "no_match"


def test_classify_api_for_sanding_belt(client):
    import csv
    import io
    from unittest.mock import patch

    from app.schemas.understanding import LLMProductUnderstanding

    headers = [
        "Mfg_Part_Num",
        "Part_Desc",
        "E1_Brand",
        "Unilog_Brand",
        "DIB_Brand",
        "Part_Manuf",
    ]
    row = {
        "Mfg_Part_Num": "DCB518ASTS06G",
        "Part_Desc": 'DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc',
        "E1_Brand": "-- Unbranded --",
        "Unilog_Brand": "-- No Unilog Brand --",
        "DIB_Brand": "-- No DIB Brand --",
        "Part_Manuf": "Freud Inc (2435)",
    }
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    writer.writerow(row)

    upload = client.post(
        "/upload",
        files={"file": ("sample.csv", buffer.getvalue().encode("utf-8"), "text/csv")},
    )
    assert upload.status_code == 200

    llm = LLMProductUnderstanding(
        product_type="Sanding Belt",
        brand_candidate="Diablo",
        manufacturer_candidate="Freud Inc",
        category_candidates=["Abrasives", "Sanding Belts"],
        extracted_terms=["Diablo", "Sanding Belt"],
        candidate_attributes={"quantity": "6"},
        confidence=0.94,
        reasoning_summary="Sanding belt from description.",
    )
    with patch("app.agents.graph.invoke_understanding_llm", return_value=llm):
        understood = client.post("/products/1/understand")
    assert understood.status_code == 200

    classified = client.post("/products/1/classify")
    assert classified.status_code == 200
    body = classified.json()
    assert body["status"] == "CLASSIFIED"
    assert body["classification"]["fine"] == "Sanding Belts"
    assert body["classification"]["classpath"] == "Abrasives>Sanding Products>Sanding Belts"
    assert body["classification"]["department"] == "Abrasives"
    assert body["classification"]["class_name"] == "Sanding Products"

    stored = client.get("/products/1/classification").json()
    assert stored["classification"]["classpath"] == body["classification"]["classpath"]
    assert "Sanding Belt" in body["classification"]["reasoning_summary"]
    assert "Sanding Belt" in stored["classification"]["reasoning_summary"]
    assert "SandingBelt" not in body["classification"]["reasoning_summary"]
    assert "SandingBelt" not in stored["classification"]["reasoning_summary"]
    assert body["classification"]["confidence"] < 1.0
    assert body["classification"]["confidence"] >= 0.9
    product = client.get("/products/1").json()
    assert product["description"].startswith("DCB518ASTS06G")
    assert product["e1_brand"] == "-- Unbranded --"
    assert product["status"] == "CLASSIFIED"


def test_category_candidate_does_not_collapse_abrasives_onto_sanding_belts():
    result = classify_against_taxonomy(
        {"id": 46, "description": "49-94-1915 Masonry Cut Off Disc", "mpn": "49-94-1915"},
        {
            "product_type": "Masonry Cut Off Disc",
            "extracted_terms": ["Masonry Cut Off Disc"],
            "category_candidates": ["Abrasives"],
        },
        _abrasive_nodes(),
    )
    assert result.fine == "Cut-Off Discs"
    assert result.classpath == "Abrasives>Cutting Products>Cut-Off Discs"
    assert result.method in {"exact", "normalized_exact", "alias_containment"}


def test_grinding_wheel_does_not_use_sanding_belt_template():
    result = classify_against_taxonomy(
        {"id": 54, "description": "Masonry Grinding Wheel", "mpn": "49-94-1955"},
        {
            "product_type": "Masonry Grinding Wheel",
            "extracted_terms": ["Grinding Wheel"],
            "category_candidates": ["Abrasives"],
        },
        _abrasive_nodes(),
    )
    assert result.fine == "Grinding Wheels"
    assert result.classpath == "Abrasives>Grinding Products>Grinding Wheels"


def test_sanding_sponge_does_not_match_sanding_belts():
    result = classify_against_taxonomy(
        {"id": 58, "description": "Sanding Sponges & Pads", "mpn": "DFBLBLOMFN01G"},
        {
            "product_type": "Sanding Sponge",
            "extracted_terms": ["Sanding Sponge"],
            "category_candidates": ["Abrasives"],
        },
        _abrasive_nodes(),
    )
    assert result.method == "no_match"
    assert result.classpath is None
    assert result.status == "REVIEW_REQUIRED"


def test_cut_and_grind_is_not_aliased_to_cut_off_or_sanding_belts():
    result = classify_against_taxonomy(
        {
            "id": 43,
            "description": "Performance+ Dual Metal Cut & Grind Wheel - Type 27",
            "mpn": "49-94-0923",
        },
        {
            "product_type": "Metal Cut and Grind Disc",
            "extracted_terms": ["Cut and Grind"],
            "category_candidates": ["Abrasives"],
        },
        _abrasive_nodes(),
    )
    assert result.method == "no_match"
    assert result.classpath is None
    assert result.fine is None


def test_compact_product_type_restores_spacing():
    nodes = [_node()]
    result = classify_against_taxonomy(
        {"id": 1, "description": 'Diablo 1/2"x18" - Sanding Belt 6pc', "mpn": "DCB518ASTS06G"},
        {"product_type": "SandingBelt", "extracted_terms": [], "category_candidates": []},
        nodes,
    )
    assert result.status == "CLASSIFIED"
    assert "Sanding Belt" in (result.reasoning_summary or "")
    assert "SandingBelt" not in (result.reasoning_summary or "")
