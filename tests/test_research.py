from unittest.mock import patch

from app.services.research import (
    AUTHORITATIVE_MIN,
    build_search_queries,
    cached_research_metrics,
    discover_sources,
    rank_hits,
    research_status_for,
    split_search_tiers,
)
from app.services.text_display import preserve_display_text
from app.services.web_search import SearchHit
from app.schemas.understanding import LLMProductUnderstanding


MPN = "DCB518ASTS06G"
CONTEXT = {
    "mpn": MPN,
    "product_type": "Sanding Belt",
    "brand": "Diablo",
    "manufacturer": "Freud Inc",
    "department": "Abrasives",
    "class": "Sanding Products",
    "fine": "Sanding Belts",
    "classpath": "Abrasives>Sanding Products>Sanding Belts",
}


def test_preserve_display_text_restores_sanding_belt():
    assert preserve_display_text("SandingBelt") == "Sanding Belt"
    assert preserve_display_text("Sanding Belt") == "Sanding Belt"


def test_search_queries_prioritize_brand_and_domain():
    queries = build_search_queries(CONTEXT)
    assert queries[0] == f"{MPN} Diablo"
    site_queries = [query for query in queries if query.startswith(f"{MPN} site:")]
    assert site_queries
    assert queries[1] == site_queries[0]
    assert MPN in queries
    assert queries.index(f"{MPN} Diablo") < queries.index(site_queries[0]) < queries.index(MPN)
    assert queries.index(MPN) < queries.index(f"{MPN} Sanding Belt")
    assert queries.index(f"{MPN} Sanding Belt") < queries.index(f"{MPN} specification")
    assert queries.index(f"{MPN} specification") < queries.index(f"{MPN} PDF")
    assert queries[-2:] == [f"{MPN} specification", f"{MPN} PDF"]


def test_search_queries_keep_bare_mpn_as_fallback_without_brand():
    queries = build_search_queries({**CONTEXT, "brand": None})
    assert queries[0].startswith(f"{MPN} site:")
    assert MPN in queries
    assert queries.index(queries[0]) < queries.index(MPN)


def test_discover_sources_stops_after_manufacturer_hit():
    queries: list[str] = []

    def fake_search(query, max_results=8):
        queries.append(query)
        return [
            SearchHit(
                title=f"{MPN} Diablo Sanding Belt",
                url="https://www.diablotools.com/products/DCB518ASTS06G",
                snippet=f"{MPN} Diablo sanding belt",
            )
        ]

    with patch("app.services.research.search_web", side_effect=fake_search):
        result = discover_sources(CONTEXT, 1)
    sources = result.sources
    metrics = result.metrics
    tier1, _tier2 = split_search_tiers(build_search_queries(CONTEXT), CONTEXT)
    assert sources
    assert sources[0].source_type == "MANUFACTURER"
    assert f"{MPN} specification" not in queries
    assert f"{MPN} PDF" not in queries
    assert set(queries) == set(tier1)
    assert metrics.query_count == len(build_search_queries(CONTEXT))
    assert metrics.queries_attempted == len(tier1)
    assert metrics.parallel_batches == 1
    assert metrics.tier1_queries == len(tier1)
    assert metrics.tier2_queries == 0
    assert metrics.tier2_wall_ms == 0.0
    assert metrics.early_exit is True
    assert metrics.manufacturer_found is True
    assert metrics.cache_hit is False
    assert metrics.queries[0].query == f"{MPN} Diablo"
    assert metrics.queries[0].manufacturer_found is True
    assert metrics.search_max_ms >= 0.0


def test_research_metrics_count_queries_until_manufacturer_found():
    def fake_search(query, max_results=8):
        if query == f"{MPN} Diablo":
            return [
                SearchHit(
                    title=f"{MPN} at Home Depot",
                    url="https://www.homedepot.com/p/DCB518ASTS06G",
                    snippet=f"Buy {MPN} Diablo sanding belt",
                )
            ]
        if query.startswith(f"{MPN} site:"):
            return [
                SearchHit(
                    title=f"{MPN} Diablo product page",
                    url="https://www.diablotools.com/products/DCB518ASTS06G",
                    snippet=f"{MPN} Diablo sanding belt",
                )
            ]
        return []

    with patch("app.services.research.search_web", side_effect=fake_search):
        result = discover_sources(CONTEXT, 1)
    metrics = result.metrics
    tier1, _tier2 = split_search_tiers(build_search_queries(CONTEXT), CONTEXT)
    assert metrics.queries_attempted == len(tier1)
    assert metrics.parallel_batches == 1
    assert metrics.tier2_queries == 0
    assert metrics.early_exit is True
    assert metrics.manufacturer_found is True
    assert metrics.queries[0].query == f"{MPN} Diablo"
    assert metrics.queries[1].query.startswith(f"{MPN} site:")
    assert metrics.queries[0].manufacturer_found is False
    assert any(item.manufacturer_found for item in metrics.queries[1:])
    assert metrics.search_avg_ms == round(metrics.search_total_ms / metrics.queries_attempted, 3)


def test_research_metrics_no_manufacturer_runs_all_queries():
    planned = build_search_queries(CONTEXT)
    tier1, tier2 = split_search_tiers(planned, CONTEXT)
    with patch("app.services.research.search_web", return_value=[]):
        result = discover_sources(CONTEXT, 1)
    metrics = result.metrics
    assert result.sources == []
    assert metrics.query_count == len(planned)
    assert metrics.queries_attempted == len(planned)
    assert metrics.queries_until_manufacturer_found == 0
    assert metrics.early_exit is False
    assert metrics.manufacturer_found is False
    assert metrics.parallel_batches == 2
    assert metrics.tier1_queries == len(tier1)
    assert metrics.tier2_queries == len(tier2)
    assert metrics.tier1_wall_ms >= 0.0
    assert metrics.tier2_wall_ms >= 0.0
    assert [item.query for item in metrics.queries] == tier1 + tier2


def test_cached_research_metrics_mark_cache_hit_without_searches():
    metrics = cached_research_metrics(CONTEXT, [])
    assert metrics.cache_hit is True
    assert metrics.queries_attempted == 0
    assert metrics.query_count == len(build_search_queries(CONTEXT))
    assert metrics.queries == []
    assert metrics.search_total_ms == 0.0
    assert metrics.parallel_batches == 0
    assert metrics.manufacturer_found is False


def test_discover_sources_skips_ddgs_session_reuse_across_parallel_fallback():
    context = {**CONTEXT, "brand": None, "manufacturer": None}
    with patch("app.services.research.search_web", return_value=[]):
        result = discover_sources(context, 1)
    metrics = result.metrics
    planned = build_search_queries(context)
    _tier1, tier2 = split_search_tiers(planned, context)
    assert metrics.tier1_queries == 0
    assert metrics.tier1_wall_ms == 0.0
    assert metrics.tier2_queries == len(tier2)
    assert metrics.parallel_batches == 1
    assert metrics.queries_attempted == len(planned)


def test_tier_parallel_search_uses_wall_clock_not_sum():
    import time

    def fake_search(query, max_results=8):
        time.sleep(0.08)
        return []

    with patch("app.services.research.search_web", side_effect=fake_search):
        result = discover_sources(CONTEXT, 1)
    metrics = result.metrics
    summed = sum(item.duration_ms for item in metrics.queries)
    assert metrics.parallel_batches == 2
    assert metrics.tier1_queries > 1
    assert metrics.tier2_queries > 1
    assert metrics.queries_attempted == metrics.query_count
    assert summed > metrics.search_total_ms + 40
    assert metrics.search_total_ms < summed
    assert metrics.tier1_wall_ms + metrics.tier2_wall_ms <= metrics.search_total_ms + 50


def test_a_manufacturer_page_outranks_distributor():
    hits = [
        SearchHit(
            title="Diablo Sanding Belt DCB518ASTS06G",
            url="https://www.homedepot.com/p/DCB518ASTS06G",
            snippet="Buy DCB518ASTS06G Diablo sanding belt",
        ),
        SearchHit(
            title="DCB518ASTS06G 1/2 in. x 18 in. Sanding Belt",
            url="https://www.diablotools.com/us/en/dcb518asts06g",
            snippet="Diablo DCB518ASTS06G sanding belt from Freud",
        ),
    ]
    ranked = rank_hits(hits, CONTEXT, product_id=1)
    assert ranked[0].url.startswith("https://www.diablotools.com")
    assert ranked[0].source_type == "MANUFACTURER"
    assert ranked[0].content_type == "PRODUCT_PAGE"
    assert ranked[1].source_type == "RETAILER"
    assert ranked[0].authority_score == 1.0
    assert ranked[0].authority_score > ranked[1].authority_score


def test_b_manufacturer_pdf_is_specification():
    hits = [
        SearchHit(
            title="DCB518ASTS06G Specification Sheet",
            url="https://www.diablotools.com/docs/DCB518ASTS06G-spec.pdf",
            snippet="Official specification PDF for DCB518ASTS06G",
        )
    ]
    ranked = rank_hits(hits, CONTEXT, product_id=1)
    assert len(ranked) == 1
    assert ranked[0].source_type == "MANUFACTURER"
    assert ranked[0].content_type == "SPECIFICATION"
    assert ranked[0].authority_score >= 0.95


def test_c_multiple_manufacturer_sources_are_ranked():
    hits = [
        SearchHit(
            title="Diablo Catalog DCB518ASTS06G",
            url="https://www.freudtools.com/catalog/abrasives.pdf",
            snippet="Catalog listing DCB518ASTS06G sanding belts",
        ),
        SearchHit(
            title="DCB518ASTS06G product page",
            url="https://www.diablotools.com/us/en/dcb518asts06g",
            snippet="DCB518ASTS06G Diablo sanding belt",
        ),
        SearchHit(
            title="DCB518ASTS06G spec sheet",
            url="https://www.diablotools.com/docs/DCB518ASTS06G.pdf",
            snippet="Technical specification for DCB518ASTS06G",
        ),
    ]
    ranked = rank_hits(hits, CONTEXT, product_id=1)
    assert len(ranked) == 3
    assert ranked[0].source_type == "MANUFACTURER"
    assert ranked[0].content_type == "PRODUCT_PAGE"
    assert ranked[1].authority_score >= ranked[2].authority_score
    status, requires_review = research_status_for(ranked)
    assert status == "RESEARCHED"
    assert requires_review is False


def test_d_distributor_only_is_not_authoritative():
    hits = [
        SearchHit(
            title="DCB518ASTS06G Diablo Sanding Belt",
            url="https://www.homedepot.com/p/diablo-DCB518ASTS06G",
            snippet="Home Depot DCB518ASTS06G Diablo sanding belt",
        )
    ]
    ranked = rank_hits(hits, CONTEXT, product_id=1)
    assert len(ranked) == 1
    assert ranked[0].source_type == "RETAILER"
    assert ranked[0].authority_score < AUTHORITATIVE_MIN
    status, requires_review = research_status_for(ranked)
    assert status == "NO_AUTHORITATIVE_SOURCE"
    assert requires_review is True


def test_e_no_source_found():
    ranked = rank_hits([], CONTEXT, product_id=1)
    assert ranked == []
    status, requires_review = research_status_for(ranked)
    assert status == "NO_AUTHORITATIVE_SOURCE"
    assert requires_review is True


def test_f_wrong_mpn_is_rejected():
    hits = [
        SearchHit(
            title="Random abrasive DCB518",
            url="https://example.com/products/dcb518",
            snippet="Partial match only, not the full manufacturer part number",
        ),
        SearchHit(
            title="Unrelated belt XYZ999",
            url="https://www.diablotools.com/us/en/xyz999",
            snippet="A different Diablo belt",
        ),
    ]
    ranked = rank_hits(hits, CONTEXT, product_id=1)
    assert ranked == []


def _prepare_classified_product(client):
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
    upload = client.post(
        "/upload",
        files={"file": ("sample.csv", buffer.getvalue().encode("utf-8"), "text/csv")},
    )
    assert upload.status_code == 200
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


def test_research_api_persists_ranked_manufacturer_sources(client):
    _prepare_classified_product(client)
    hits = [
        SearchHit(
            title="DCB518ASTS06G product page",
            url="https://www.diablotools.com/us/en/dcb518asts06g",
            snippet="DCB518ASTS06G Diablo sanding belt",
        ),
        SearchHit(
            title="DCB518ASTS06G spec PDF",
            url="https://www.diablotools.com/docs/DCB518ASTS06G.pdf",
            snippet="Specification for DCB518ASTS06G",
        ),
        SearchHit(
            title="Amazon DCB518ASTS06G",
            url="https://www.amazon.com/dp/DCB518ASTS06G",
            snippet="Buy DCB518ASTS06G",
        ),
    ]
    with patch("app.services.research.search_web", return_value=hits):
        response = client.post("/products/1/research")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESEARCHED"
    assert body["manufacturer_source_found"] is True
    assert body["requires_review"] is False
    assert body["review_scope"] == "source_discovery"
    assert body["sources_found"] >= 2
    assert body["sources"][0]["source_type"] == "MANUFACTURER"
    assert body["sources"][0]["content_type"] == "PRODUCT_PAGE"
    metrics = body["metrics"]
    assert metrics["queries_attempted"] >= 1
    assert metrics["query_count"] >= metrics["queries_attempted"]
    assert metrics["manufacturer_found"] is True
    assert metrics["early_exit"] is True
    assert metrics["cache_hit"] is False
    assert metrics["queries"]
    assert metrics["queries"][0]["query"]
    assert "duration_ms" in metrics["queries"][0]
    assert "hits" in metrics["queries"][0]
    by_url = {item["url"]: item for item in body["sources"]}
    amazon = by_url.get("https://www.amazon.com/dp/DCB518ASTS06G")
    if amazon:
        assert amazon["source_type"] == "MARKETPLACE"
    stored = client.get("/products/1/sources").json()
    assert stored["sources_found"] == body["sources_found"]
    assert stored["manufacturer_source_found"] is True
    product = client.get("/products/1").json()
    assert product["status"] == "RESEARCHED"


def test_zoro_is_authorized_distributor():
    hits = [
        SearchHit(
            title="DCB518ASTS06G Diablo Sanding Belt",
            url="https://www.zoro.com/diablo-dcb518asts06g",
            snippet="Zoro DCB518ASTS06G Diablo sanding belt",
        )
    ]
    ranked = rank_hits(hits, CONTEXT, product_id=1)
    assert ranked[0].source_type == "AUTHORIZED_DISTRIBUTOR"


def test_research_api_empty_search_is_not_pipeline_failure(client):
    _prepare_classified_product(client)
    with patch("app.services.research.search_web", return_value=[]):
        response = client.post("/products/1/research")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NO_AUTHORITATIVE_SOURCE"
    assert body["sources"] == []
    assert body["manufacturer_source_found"] is False
    assert body["requires_review"] is True
    assert body["review_scope"] == "source_discovery"
    product = client.get("/products/1").json()
    assert product["status"] == "NO_AUTHORITATIVE_SOURCE"


def test_search_web_times_out_instead_of_hanging():
    import time

    from app.services import web_search

    class HangClient:
        def text(self, query, max_results=8):
            time.sleep(30)
            return [{"href": "https://example.com", "title": "late", "body": "late"}]

    token = web_search._active_client.set(HangClient())
    try:
        started = time.perf_counter()
        with patch.object(web_search, "SEARCH_TIMEOUT_SECONDS", 0.2):
            hits = web_search.search_web("hanging query")
        elapsed = time.perf_counter() - started
    finally:
        web_search._active_client.reset(token)
    assert hits == []
    assert elapsed < 2.0


def test_parallel_search_batch_does_not_wait_forever():
    import time

    from app.services import research

    def hang(query: str):
        time.sleep(30)
        return query, [], 30000.0

    started = time.perf_counter()
    with patch.object(research, "SEARCH_TIMEOUT_SECONDS", 0.2), patch.object(
        research, "_timed_search_web", side_effect=hang
    ):
        batch, _count = research._search_parallel_batch(["a", "b"], set())
    elapsed = time.perf_counter() - started
    assert len(batch) == 2
    assert elapsed < 3.0
