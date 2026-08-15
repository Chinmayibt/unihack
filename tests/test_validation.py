from app.schemas.normalized_attribute import (
    AGREEMENT,
    CONFLICT,
    INPUT_SOURCED,
    MANUFACTURER_SUPPORTED,
    NOT_FOUND,
    SECONDARY_SOURCE_ONLY,
    SOURCE_INPUT,
    SOURCE_MANUFACTURER,
    SOURCE_MARKETPLACE,
    EvidenceCandidate,
    NormalizedAttribute,
)
from app.services.attribute_templates import template_for_classpath
from app.services.validation import evaluate_attributes
from app.services.fetch import FetchedDocument
from unittest.mock import patch
import test_attributes


CLASSPATH = "Abrasives>Sanding Products>Sanding Belts"


def _attr(**kwargs) -> NormalizedAttribute:
    return NormalizedAttribute(**kwargs)


def _sanding_belt_attributes(**overrides) -> list[NormalizedAttribute]:
    items = {
        "Product Type": _attr(
            label="Product Type",
            normalized_value="Sanding Belts",
            selected_source=SOURCE_MANUFACTURER,
            evidence_text="Sanding Belts",
            source_id=16,
            agreement=MANUFACTURER_SUPPORTED,
            status="NORMALIZED",
        ),
        "Width": _attr(
            label="Width",
            raw_value='1/2"',
            normalized_value="1/2",
            normalized_uom="in",
            selected_source=SOURCE_MANUFACTURER,
            evidence_text='1/2" x 18"',
            source_id=16,
            agreement=AGREEMENT,
            status="NORMALIZED",
        ),
        "Length": _attr(
            label="Length",
            raw_value='18"',
            normalized_value="18",
            normalized_uom="in",
            selected_source=SOURCE_MANUFACTURER,
            evidence_text='1/2" x 18"',
            source_id=16,
            agreement=AGREEMENT,
            status="NORMALIZED",
        ),
        "Abrasive Material": _attr(
            label="Abrasive Material",
            normalized_value="Aluminum Oxide",
            selected_source=SOURCE_MANUFACTURER,
            evidence_text="premium aluminum oxide blend",
            source_id=16,
            agreement=MANUFACTURER_SUPPORTED,
            status="NORMALIZED",
        ),
        "Backing Material": _attr(label="Backing Material", agreement=NOT_FOUND, status="NOT_FOUND"),
        "Grit": _attr(label="Grit", agreement=NOT_FOUND, status="NOT_FOUND"),
        "Quantity": _attr(
            label="Quantity",
            raw_value="6pc",
            normalized_value="6",
            normalized_uom="EA",
            selected_source=SOURCE_INPUT,
            evidence_text="6pc",
            agreement=INPUT_SOURCED,
            status="NORMALIZED",
        ),
        "Application": _attr(
            label="Application",
            normalized_value="heavy stock removal, planing and sanding",
            selected_source=SOURCE_MANUFACTURER,
            evidence_text="heavy stock removal, planing and sanding",
            source_id=16,
            agreement=MANUFACTURER_SUPPORTED,
            status="UNCHANGED",
        ),
    }
    items.update(overrides)
    return list(items.values())


def test_sanding_belt_template_marks_core_size_required():
    template = template_for_classpath(CLASSPATH)
    by_label = {item.label: item for item in template}
    assert by_label["Width"].required is True
    assert by_label["Length"].required is True
    assert by_label["Product Type"].required is True
    assert by_label["Abrasive Material"].required is True
    assert by_label["Grit"].required is False
    assert by_label["Backing Material"].required is False
    assert by_label["Quantity"].required is False
    assert by_label["Width"].uom_family == "length"


def test_product_one_is_partial_not_review():
    result = evaluate_attributes(1, CLASSPATH, _sanding_belt_attributes(), classified=True)
    assert result.status == "PARTIAL"
    assert result.requires_review is False
    assert result.approved_for_output is True
    assert result.completeness_score == 0.75
    assert result.evidence_coverage == 1.0
    assert result.issues == []
    assert result.missing_attributes == ["Backing Material", "Grit"]


def test_width_conflict_requires_review():
    conflict = _attr(
        label="Width",
        raw_value='1/2"',
        normalized_value=None,
        agreement=CONFLICT,
        status="CONFLICT",
        candidates=[
            EvidenceCandidate(value='1/2"', source=SOURCE_INPUT, authority=1.0),
            EvidenceCandidate(value='3/4"', source=SOURCE_MANUFACTURER, authority=1.0),
        ],
    )
    result = evaluate_attributes(
        1, CLASSPATH, _sanding_belt_attributes(**{"Width": conflict}), classified=True
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.requires_review is True
    assert result.approved_for_output is False
    assert any(issue.issue_type == "SOURCE_CONFLICT" for issue in result.issues)
    assert not any(issue.issue_type == "MISSING_REQUIRED" for issue in result.issues)


def test_invalid_uom_is_not_approved():
    bad = _attr(
        label="Width",
        normalized_value="1/2",
        normalized_uom="kg",
        selected_source=SOURCE_MANUFACTURER,
        evidence_text="1/2 kg",
        source_id=16,
        agreement=MANUFACTURER_SUPPORTED,
        status="NORMALIZED",
    )
    result = evaluate_attributes(
        1, CLASSPATH, _sanding_belt_attributes(**{"Width": bad}), classified=True
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.requires_review is True
    assert any(issue.issue_type == "UOM_INVALID" for issue in result.issues)


def test_lov_invalid_includes_diagnostics():
    bad = _attr(
        label="Abrasive Material",
        raw_value="purple magic",
        normalized_value="Purple Magic Material",
        selected_source=SOURCE_MANUFACTURER,
        evidence_text="purple magic blend",
        source_id=16,
        agreement=MANUFACTURER_SUPPORTED,
        status="NORMALIZED",
    )
    result = evaluate_attributes(
        1, CLASSPATH, _sanding_belt_attributes(**{"Abrasive Material": bad}), classified=True
    )
    issue = next(item for item in result.issues if item.issue_type == "LOV_INVALID")
    assert issue.attribute == "Abrasive Material"
    assert issue.raw_value == "purple magic"
    assert issue.normalized_value == "Purple Magic Material"
    assert "Aluminum Oxide" in issue.allowed_values
    assert issue.source == SOURCE_MANUFACTURER
    assert issue.evidence_text == "purple magic blend"
    assert issue.requires_review is True


def test_canonical_and_alias_lov_are_not_review():
    lowered = _attr(
        label="Abrasive Material",
        raw_value="aluminum oxide",
        normalized_value="aluminum oxide",
        selected_source=SOURCE_MANUFACTURER,
        evidence_text="aluminum oxide",
        source_id=16,
        agreement=MANUFACTURER_SUPPORTED,
        status="NORMALIZED",
    )
    result = evaluate_attributes(
        1, CLASSPATH, _sanding_belt_attributes(**{"Abrasive Material": lowered}), classified=True
    )
    assert not any(issue.issue_type == "LOV_INVALID" for issue in result.issues)
    assert lowered.normalized_value == "Aluminum Oxide"

    cut_off = "Abrasives>Cutting Products>Cut-Off Discs"
    product_type = _attr(
        label="Product Type",
        raw_value="Metal Cut Off Wheel",
        normalized_value="Metal Cut Off Wheel",
        selected_source=SOURCE_MANUFACTURER,
        evidence_text="Metal Cut Off Wheel",
        source_id=16,
        agreement=MANUFACTURER_SUPPORTED,
        status="NORMALIZED",
    )
    from app.services.validation import _lov_issue

    assert _lov_issue(product_type, cut_off) is None
    assert product_type.normalized_value == "Cut-Off Discs"


def test_unsupported_lov_stays_review():
    from app.services.validation import _lov_issue

    cut_off = "Abrasives>Cutting Products>Cut-Off Discs"
    type_one = _attr(
        label="Product Type",
        raw_value="Type 1",
        normalized_value="Type 1",
        selected_source=SOURCE_MANUFACTURER,
        evidence_text="Type 1",
        source_id=16,
        agreement=MANUFACTURER_SUPPORTED,
        status="NORMALIZED",
    )
    issue = _lov_issue(type_one, cut_off)
    assert issue is not None
    assert issue.issue_type == "LOV_INVALID"
    assert issue.normalized_value == "Type 1"
    assert "Cut-Off Discs" in issue.allowed_values

    zirconia = _attr(
        label="Abrasive Material",
        raw_value="zirconia",
        normalized_value="zirconia",
        selected_source=SOURCE_MANUFACTURER,
        evidence_text="zirconia",
        source_id=16,
        agreement=MANUFACTURER_SUPPORTED,
        status="NORMALIZED",
    )
    result = evaluate_attributes(
        1, CLASSPATH, _sanding_belt_attributes(**{"Abrasive Material": zirconia}), classified=True
    )
    assert any(issue.issue_type == "LOV_INVALID" for issue in result.issues)
    bonded = _lov_issue(
        _attr(
            label="Material",
            raw_value="Bonded Abrasive",
            normalized_value="Bonded Abrasive",
            selected_source=SOURCE_MANUFACTURER,
            evidence_text="Bonded Abrasive",
            source_id=16,
            agreement=MANUFACTURER_SUPPORTED,
            status="NORMALIZED",
        ),
        cut_off,
    )
    assert bonded is not None
    assert bonded.issue_type == "LOV_INVALID"


def test_secondary_grit_is_review_not_output_value():
    grit = _attr(
        label="Grit",
        agreement=SECONDARY_SOURCE_ONLY,
        status="SECONDARY_SOURCE_ONLY",
        candidates=[
            EvidenceCandidate(
                value="50/80/120",
                source=SOURCE_MARKETPLACE,
                authority=0.2,
                evidence_text="50/80/120-Grit Multi-Grade",
            )
        ],
    )
    result = evaluate_attributes(
        1, CLASSPATH, _sanding_belt_attributes(**{"Grit": grit}), classified=True
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.requires_review is True
    assert result.approved_for_output is False
    assert any(issue.issue_type == "SECONDARY_SOURCE_ONLY" for issue in result.issues)


def test_validate_api_for_product_one(client):
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

    response = client.post("/products/1/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["requires_review"] is False
    assert body["approved_for_output"] is True
    assert body["completeness_score"] == 0.75
    assert body["evidence_coverage"] == 1.0
    assert body["issues"] == []
    assert "Grit" in body["missing_attributes"]
    assert "Backing Material" in body["missing_attributes"]
    assert client.get("/products/1").json()["status"] == "PARTIAL"
    saved = client.get("/products/1/validation")
    assert saved.status_code == 200
    assert saved.json()["status"] == "PARTIAL"
