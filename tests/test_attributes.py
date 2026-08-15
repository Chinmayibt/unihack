from unittest.mock import patch

from app.schemas.attribute import LLMAttributeExtraction, LLMExtractedSlot
from app.schemas.evidence import Evidence
from app.schemas.understanding import LLMProductUnderstanding
from app.services.attribute_extraction import assemble_attributes, evidence_confidence
from app.services.attribute_templates import template_for_classpath
from app.services.fetch import FetchedDocument
from app.services.web_search import SearchHit


MPN = "DCB518ASTS06G"


ATTRIBUTE_HTML = """
<html>
  <head>
    <title>DCB518ASTS06G | Sanding Belts - Diablo Tools</title>
    <meta name="description" content="Diablo's 1/2&quot; x 18&quot; detail file sanding belts. Premium aluminum oxide blend with stearate coating.">
  </head>
  <body>
    <main>
      <h1>DCB518ASTS06G Sanding Belt</h1>
      <p>Diablo 1/2 in. x 18 in. Assorted File Sanding Belt. Brand: Diablo. Product type: Sanding Belt.</p>
      <p>Premium aluminum oxide blend with stearate coating for heavy stock removal, planing and sanding.</p>
      <table>
        <tr><th>Size</th><td>1/2 in. x 18 in.</td></tr>
        <tr><th>Width</th><td>1/2 in</td></tr>
        <tr><th>Length</th><td>18 in</td></tr>
        <tr><th>Brand</th><td>Diablo</td></tr>
      </table>
    </main>
  </body>
</html>
"""

INVENTED_LLM = LLMAttributeExtraction(
    attributes=[
        LLMExtractedSlot(
            label="Product Type",
            value="Sanding Belt",
            evidence_text="Product type: Sanding Belt",
            supported=True,
        ),
        LLMExtractedSlot(
            label="Width",
            value="1/2",
            uom="in",
            evidence_text='Diablo 1/2 in. x 18 in.',
            supported=True,
        ),
        LLMExtractedSlot(
            label="Length",
            value="18",
            uom="in",
            evidence_text="1/2 in. x 18 in.",
            supported=True,
        ),
        LLMExtractedSlot(
            label="Abrasive Material",
            value="Aluminum Oxide",
            evidence_text="Premium aluminum oxide blend",
            supported=True,
        ),
        LLMExtractedSlot(label="Backing Material", supported=False),
        LLMExtractedSlot(
            label="Grit",
            value="80",
            evidence_text="80 grit",
            supported=True,
        ),
        LLMExtractedSlot(
            label="Quantity",
            value="6pc",
            evidence_text="6pc pack",
            supported=True,
        ),
        LLMExtractedSlot(
            label="Application",
            value="heavy stock removal, planing and sanding",
            evidence_text="heavy stock removal, planing and sanding",
            supported=True,
        ),
    ]
)


def _prepare_researched_product(client):
    import csv
    import io

    headers = [
        "Mfg_Part_Num",
        "Part_Desc",
        "E1_Brand",
        "Unilog_Brand",
        "DIB_Brand",
        "Part_Manuf",
    ]
    row = {
        "Mfg_Part_Num": MPN,
        "Part_Desc": f'{MPN} Diablo 1/2"x18" - Sanding Belt 6pc',
        "E1_Brand": "-- Unbranded --",
        "Unilog_Brand": "-- No Unilog Brand --",
        "DIB_Brand": "-- No DIB Brand --",
        "Part_Manuf": "Freud Inc (2435)",
    }
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    writer.writerow(row)
    assert client.post(
        "/upload",
        files={"file": ("sample.csv", buffer.getvalue().encode("utf-8"), "text/csv")},
    ).status_code == 200
    llm = LLMProductUnderstanding(
        product_type="Sanding Belt",
        brand_candidate="Diablo",
        manufacturer_candidate="Freud Inc",
        category_candidates=["Abrasives"],
        extracted_terms=["Sanding Belt"],
        candidate_attributes={},
        confidence=0.94,
        reasoning_summary="Sanding belt from description.",
    )
    with patch("app.agents.graph.invoke_understanding_llm", return_value=llm):
        assert client.post("/products/1/understand").status_code == 200
    assert client.post("/products/1/resolve").status_code == 200
    assert client.post("/products/1/classify").status_code == 200
    hits = [
        SearchHit(
            title="DCB518ASTS06G product page",
            url="https://www.diablotools.com/products/DCB518ASTS06G",
            snippet="DCB518ASTS06G Diablo sanding belt",
        )
    ]
    with patch("app.services.research.search_web", return_value=hits):
        researched = client.post("/products/1/research")
    assert researched.status_code == 200
    assert researched.json()["manufacturer_source_found"] is True


def test_template_for_sanding_belts():
    items = template_for_classpath("Abrasives>Sanding Products>Sanding Belts")
    labels = [item.label for item in items]
    assert labels == [
        "Product Type",
        "Width",
        "Length",
        "Abrasive Material",
        "Backing Material",
        "Grit",
        "Quantity",
        "Application",
    ]
    assert any("belt width" in item.query.lower() for item in items)


def test_grounding_rejects_invented_grit_and_quantity():
    evidence = Evidence(
        text='Diablo 1/2 in. x 18 in. Assorted File Sanding Belt. Premium aluminum oxide blend for heavy stock removal, planing and sanding. DCB518ASTS06G.',
        evidence_text='Diablo 1/2 in. x 18 in. Assorted File Sanding Belt. Premium aluminum oxide blend for heavy stock removal, planing and sanding. DCB518ASTS06G.',
        score=0.78,
        retrieval_score=0.78,
        source="Diablo Tools",
        url="https://www.diablotools.com/products/DCB518ASTS06G",
        source_id=16,
        document_id=2,
        source_type="MANUFACTURER",
    )
    template = template_for_classpath("Abrasives>Sanding Products>Sanding Belts")
    blocks = [{"label": item.label, "query": item.query, "hits": [evidence]} for item in template]
    attributes = assemble_attributes(
        1,
        "Abrasives>Sanding Products>Sanding Belts",
        blocks,
        INVENTED_LLM,
    )
    by_label = {item.label: item for item in attributes}
    assert by_label["Width"].status == "EXTRACTED"
    assert by_label["Width"].value == "1/2"
    assert by_label["Width"].uom == "in"
    assert by_label["Length"].status == "EXTRACTED"
    assert by_label["Length"].value == "18"
    assert by_label["Abrasive Material"].status == "EXTRACTED"
    assert by_label["Abrasive Material"].value == "Aluminum Oxide"
    assert by_label["Application"].status == "EXTRACTED"
    assert by_label["Grit"].status == "NOT_FOUND"
    assert by_label["Grit"].value is None
    assert by_label["Quantity"].status == "NOT_FOUND"
    assert by_label["Quantity"].value is None
    assert by_label["Backing Material"].status == "NOT_FOUND"
    assert by_label["Width"].source_id == 16
    assert by_label["Width"].document_id == 2
    assert by_label["Width"].confidence > 0.7


def test_evidence_confidence_prefers_manufacturer_authority():
    manufacturer = evidence_confidence(
        source_type="MANUFACTURER", retrieval_score=0.78, exactness=0.95
    )
    retailer = evidence_confidence(
        source_type="RETAILER", retrieval_score=0.78, exactness=0.95
    )
    assert manufacturer > retailer
    assert 0.85 <= manufacturer <= 0.95


def test_extract_api_grounds_attributes(client):
    _prepare_researched_product(client)
    fetched = FetchedDocument(
        url="https://www.diablotools.com/products/DCB518ASTS06G",
        content_bytes=ATTRIBUTE_HTML.encode("utf-8"),
        content_type="text/html",
        final_url="https://www.diablotools.com/products/DCB518ASTS06G",
    )
    with patch("app.services.indexing.fetch_url", return_value=fetched):
        indexed = client.post("/products/1/index")
    assert indexed.status_code == 200

    with patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=INVENTED_LLM,
    ):
        extracted = client.post("/products/1/attributes/extract")
    assert extracted.status_code == 200
    body = extracted.json()
    assert body["product_id"] == 1
    assert body["status"] == "EXTRACTED"
    assert body["classpath"] == "Abrasives>Sanding Products>Sanding Belts"
    by_label = {item["label"]: item for item in body["attributes"]}
    assert by_label["Width"]["value"] == "1/2"
    assert by_label["Width"]["uom"] == "in"
    assert by_label["Width"]["status"] == "EXTRACTED"
    assert by_label["Width"]["evidence_text"]
    assert by_label["Width"]["source_id"] is not None
    assert by_label["Width"]["retrieval_score"] > 0
    assert by_label["Length"]["value"] == "18"
    assert by_label["Abrasive Material"]["value"] == "Aluminum Oxide"
    assert by_label["Application"]["status"] == "EXTRACTED"
    assert by_label["Grit"]["status"] == "NOT_FOUND"
    assert by_label["Grit"]["value"] is None
    assert by_label["Quantity"]["status"] == "NOT_FOUND"
    metrics = body["metrics"]
    assert metrics["llm_call_count"] == 1
    assert metrics["embedding_call_count"] == 1
    assert metrics["vector_search_count"] == 1
    assert metrics["attribute_count"] == len(body["attributes"])
    assert metrics["extraction_total_ms"] >= metrics["llm_ms"]
    assert "llm_request_ms" in metrics
    assert "llm_wait_ms" in metrics
    assert "llm_cooldown_ms" in metrics

    product = client.get("/products/1").json()
    assert product["status"] == "EXTRACTED"

    saved = client.get("/products/1/attributes")
    assert saved.status_code == 200
    assert saved.json()["status"] == "EXTRACTED"


def test_extract_without_index_returns_404(client):
    _prepare_researched_product(client)
    response = client.post("/products/1/attributes/extract")
    assert response.status_code == 404
    assert "indexed" in response.json()["detail"].lower()


def test_retrieve_evidence_uses_one_search(client):
    _prepare_researched_product(client)
    fetched = FetchedDocument(
        url="https://www.diablotools.com/products/DCB518ASTS06G",
        content_bytes=ATTRIBUTE_HTML.encode("utf-8"),
        content_type="text/html",
        final_url="https://www.diablotools.com/products/DCB518ASTS06G",
    )
    with patch("app.services.indexing.fetch_url", return_value=fetched):
        assert client.post("/products/1/index").status_code == 200
    calls = {"n": 0}
    original = None
    from app.services import retrieval

    original = retrieval.search_product_evidence

    def counting(product_id, query, db, top_k=5):
        calls["n"] += 1
        return original(product_id, query, db, top_k=top_k)

    with patch("app.services.attribute_extraction.search_product_evidence", side_effect=counting), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=INVENTED_LLM,
    ):
        extracted = client.post("/products/1/attributes/extract")
    assert extracted.status_code == 200
    assert calls["n"] == 1
    metrics = extracted.json()["metrics"]
    assert metrics["llm_call_count"] == 1
    assert metrics["vector_search_count"] == 1
    assert metrics["embedding_call_count"] == 1


def test_type_code_product_type_recovered_from_title():
    llm = LLMAttributeExtraction(
        attributes=[
            LLMExtractedSlot(
                label="Product Type",
                value="Type 1",
                evidence_text="Type 1",
                supported=True,
            )
        ]
    )
    blocks = [{"label": "Product Type", "query": "What is the product type?", "hits": []}]
    recovered = assemble_attributes(
        1,
        "Abrasives>Cutting Products>Cut-Off Discs",
        blocks,
        llm,
        product_description='DBD090094101F Diablo 9" - Metal Cut-Off Disc',
    )
    assert recovered[0].value == "Cut-Off Discs"
    assert recovered[0].status == "EXTRACTED"

    kept = assemble_attributes(
        1,
        "Abrasives>Cutting Products>Cut-Off Discs",
        blocks,
        llm,
        product_description="Type 1 bonded abrasive",
    )
    assert kept[0].value == "Type 1"
