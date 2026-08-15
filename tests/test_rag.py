from unittest.mock import patch

from app.services.chunking import chunk_text
from app.services.extract import extract_html
from app.services.fetch import FetchedDocument
from app.services.web_search import SearchHit
from app.schemas.understanding import LLMProductUnderstanding


MPN = "DCB518ASTS06G"

SAMPLE_HTML = """
<html>
  <head><title>DCB518ASTS06G | Sanding Belts - Diablo Tools</title></head>
  <body>
    <main>
      <h1>DCB518ASTS06G Sanding Belt</h1>
      <p>Diablo 1/2 in. x 18 in. Assorted File Sanding Belt. Brand: Diablo. Product type: Sanding Belt.</p>
      <table>
        <tr><th>Size</th><td>1/2 in. x 18 in.</td></tr>
        <tr><th>Width</th><td>1/2 in</td></tr>
        <tr><th>Length</th><td>18 in</td></tr>
        <tr><th>Brand</th><td>Diablo</td></tr>
      </table>
      <a href="/docs/spec.pdf">Specification PDF</a>
    </main>
  </body>
</html>
"""


def test_html_extract_keeps_size_and_tables():
    extracted = extract_html(SAMPLE_HTML, "https://www.diablotools.com/products/DCB518ASTS06G")
    assert "1/2 in. x 18 in." in extracted.content
    assert "Diablo" in extracted.content
    assert "Sanding Belt" in extracted.content
    assert extracted.title.startswith("DCB518ASTS06G")
    assert any("spec.pdf" in link for link in extracted.links)


def test_chunk_text_splits_long_documents():
    text = "Paragraph one. " * 400
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert chunks[0].index == 0


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


def test_index_and_search_manufacturer_page(client):
    _prepare_researched_product(client)
    fetched = FetchedDocument(
        url="https://www.diablotools.com/products/DCB518ASTS06G",
        content_bytes=SAMPLE_HTML.encode("utf-8"),
        content_type="text/html",
        final_url="https://www.diablotools.com/products/DCB518ASTS06G",
    )
    with patch("app.services.indexing.fetch_url", return_value=fetched):
        indexed = client.post("/products/1/index")
    assert indexed.status_code == 200
    body = indexed.json()
    assert body["status"] == "INDEXED"
    assert body["documents_processed"] == 1
    assert body["chunks_created"] >= 1
    assert body["vectors_created"] == body["chunks_created"]

    product = client.get("/products/1").json()
    assert product["status"] == "INDEXED"

    size = client.post(
        "/products/1/search",
        json={"query": "What is the size of this sanding belt?"},
    )
    assert size.status_code == 200
    size_body = size.json()
    assert size_body["results"]
    joined = " ".join(item["evidence_text"] for item in size_body["results"])
    assert "1/2" in joined
    assert "18" in joined
    assert size_body["results"][0]["url"].startswith("https://www.diablotools.com")
    assert size_body["results"][0]["source_type"] == "MANUFACTURER"

    brand = client.post("/products/1/search", json={"query": "What brand is this product?"}).json()
    assert any("Diablo" in item["evidence_text"] for item in brand["results"])

    ptype = client.post("/products/1/search", json={"query": "What is the product type?"}).json()
    assert any("Sanding Belt" in item["evidence_text"] for item in ptype["results"])


def test_index_without_manufacturer_source_does_not_fail(client):
    _prepare_researched_product(client)
    hits = [
        SearchHit(
            title="DCB518ASTS06G Home Depot",
            url="https://www.homedepot.com/p/DCB518ASTS06G",
            snippet="DCB518ASTS06G Diablo sanding belt",
        )
    ]
    with patch("app.services.research.search_web", return_value=hits):
        researched = client.post("/products/1/research")
    assert researched.json()["manufacturer_source_found"] is False
    indexed = client.post("/products/1/index")
    assert indexed.status_code == 200
    assert indexed.json()["status"] == "NO_MANUFACTURER_SOURCE"
    assert indexed.json()["documents_processed"] == 0
