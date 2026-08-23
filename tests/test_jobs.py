from unittest.mock import patch

import test_attributes
import test_ingestion
from app.database.connection import get_db
from app.database.models import (
    ProductAttributeRecord,
    ProductUnderstandingRecord,
)
from app.services.fetch import FetchedDocument
from app.services.web_search import SearchHit


def _hits(mpn="DCB518ASTS06G"):
    return [
        SearchHit(
            title=f"{mpn} product page",
            url=f"https://www.diablotools.com/products/{mpn}",
            snippet=f"{mpn} Diablo sanding belt",
        )
    ]


def _search_for_query(query, max_results=8):
    mpn = (query or "").split()[0] or "DCB518ASTS06G"
    return _hits(mpn)


def _fetched():
    return FetchedDocument(
        url="https://www.diablotools.com/products/DCB518ASTS06G",
        content_bytes=test_attributes.ATTRIBUTE_HTML.encode("utf-8"),
        content_type="text/html",
        final_url="https://www.diablotools.com/products/DCB518ASTS06G",
    )


def _llm():
    return test_attributes.LLMProductUnderstanding(
        product_type="Sanding Belt",
        brand_candidate="Diablo",
        manufacturer_candidate="Freud Inc",
        category_candidates=["Abrasives"],
        extracted_terms=["Sanding Belt"],
        candidate_attributes={},
        confidence=0.94,
        reasoning_summary="Sanding belt from description.",
    )


TPD_ERROR = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000. "
    "Please try again in 3m17.856s.'}}"
)


def _upload_one(client, mpn="DCB518ASTS06G", desc=None):
    row = test_ingestion._row(
        Mfg_Part_Num=mpn,
        Part_Desc=desc or f'{mpn} Diablo 1/2"x18" - Sanding Belt 6pc',
    )
    assert test_ingestion._upload(client, test_ingestion._csv_bytes([row])).status_code == 200


def test_create_job_queued_without_start(client):
    _upload_one(client)
    response = client.post("/jobs", json={"auto_start": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["total"] == 1
    assert body["processed"] == 0
    assert body["job_id"]
    saved = client.get(f"/jobs/{body['job_id']}")
    assert saved.status_code == 200
    assert saved.json()["status"] == "QUEUED"


def test_list_job_products_and_output_not_ready(client):
    _upload_one(client)
    created = client.post("/jobs", json={"auto_start": False}).json()
    job_id = created["job_id"]
    listed = client.get(f"/jobs/{job_id}/products")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["mpn"] == "DCB518ASTS06G"
    assert body["items"][0]["product_id"] == 1
    csv_response = client.get(f"/jobs/{job_id}/output.csv")
    assert csv_response.status_code == 409


def test_empty_job_is_rejected(client):
    response = client.post("/jobs", json={"auto_start": False})
    assert response.status_code == 400
    assert "No eligible products" in response.json()["detail"]


def test_explicit_duplicate_product_ids_are_eligible(client):
    _upload_one(client)
    second = test_ingestion._upload(
        client,
        test_ingestion._csv_bytes(
            [test_ingestion._row(E1_Brand="Diablo", Part_Manuf="Freud Inc")]
        ),
    )
    assert second.status_code == 200
    ids = second.json()["product_ids"]
    assert ids
    assert second.json()["duplicate_mpns"] == 1
    response = client.post(
        "/jobs", json={"auto_start": False, "product_ids": ids}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["status"] == "QUEUED"
    assert body["dataset_name"] == "DCB518ASTS06G"
    assert body["progress"] == 0.0


def test_job_processes_product_and_reports_progress(client):
    _upload_one(client)
    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", return_value=_hits()
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        response = client.post("/jobs", json={"auto_start": True})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["total"] == 1
    assert body["processed"] == 1
    assert body["progress"] == 100.0
    assert body["failed"] == 0
    assert body["partial"] + body["approved"] + body["review_required"] == 1
    assert body["success_rate"] == 1.0
    report = client.get(f"/jobs/{body['job_id']}/report").json()
    assert report["products"] == 1
    assert report["failed"] == 0
    assert "JOB SUMMARY" in report["summary"]
    listed = client.get("/jobs").json()
    assert any(item["job_id"] == body["job_id"] for item in listed)
    output = client.get("/products/1/output")
    assert output.status_code == 200
    assert output.json()["output"]["Mfg_Part_Num"] == "DCB518ASTS06G"
    csv_response = client.get(f"/jobs/{body['job_id']}/output.csv")
    assert csv_response.status_code == 200
    assert "Mfg_Part_Num" in csv_response.text
    assert "DCB518ASTS06G" in csv_response.text


def test_one_product_failure_does_not_stop_job(client):
    _upload_one(client, mpn="OK-001")
    _upload_one(client, mpn="BAD-002", desc='BAD-002 Diablo 1/2"x18" - Sanding Belt 6pc')

    from app.services.attribute_extraction import extract_product_attributes as original

    def wrapper(product_id, db):
        if product_id == 2:
            raise RuntimeError("extraction boom")
        return original(product_id, db)

    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", side_effect=_search_for_query
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ), patch(
        "app.agents.graph.extract_product_attributes",
        side_effect=wrapper,
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["total"] == 2
    assert body["failed"] == 1
    assert body["processed"] == 2
    assert body["partial"] + body["approved"] + body["review_required"] == 1
    errors = client.get(f"/jobs/{body['job_id']}/errors").json()
    assert errors
    assert any(item["stage"] == "extraction" for item in errors)
    assert client.get("/products/1").json()["status"] != "INGESTED"


def test_retry_skips_completed_understanding(client):
    _upload_one(client)
    created = client.post("/jobs", json={"auto_start": False}).json()
    job_id = created["job_id"]
    understand_calls = {"n": 0}

    def counting_llm(raw_product):
        understand_calls["n"] += 1
        return _llm()

    extract_fail = {"n": 0}

    def failing_extract(product_id, db):
        extract_fail["n"] += 1
        raise RuntimeError("extraction boom")

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=counting_llm), patch(
        "app.services.research.search_web", return_value=_hits()
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.agents.graph.extract_product_attributes",
        side_effect=failing_extract,
    ):
        started = client.post(f"/jobs/{job_id}/start")
    assert started.status_code == 200
    assert started.json()["failed"] == 1
    assert understand_calls["n"] >= 1
    first_calls = understand_calls["n"]

    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        assert (
            db.query(ProductUnderstandingRecord).filter_by(product_id=1).one_or_none()
            is not None
        )
    finally:
        db.close()
        try:
            next(gen)
        except StopIteration:
            pass

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=counting_llm), patch(
        "app.services.research.search_web", return_value=_hits()
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        retried = client.post(f"/jobs/{job_id}/products/1/retry")
    assert retried.status_code == 200
    assert understand_calls["n"] == first_calls
    stages = client.get(f"/jobs/{job_id}/products/1/stages").json()
    assert stages["stages"]["understanding"] in {"COMPLETED", "SKIPPED"}
    assert stages["stages"]["extraction"] == "COMPLETED"


def test_research_cache_avoids_second_search(client):
    _upload_one(client, mpn="CACHE-001")
    search_calls = {"n": 0}

    def counting_search(query, max_results=8):
        search_calls["n"] += 1
        return _hits()

    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", side_effect=counting_search
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        first = client.post("/jobs", json={"auto_start": True, "generate_output": False})
        assert first.status_code == 200
        after_first = search_calls["n"]
        assert after_first > 0
        second = client.post("/jobs", json={"auto_start": True, "generate_output": False})
        assert second.status_code == 200
    assert search_calls["n"] == after_first


def test_job_exposes_stage_profile_and_review_breakdown(client):
    _upload_one(client)
    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", return_value=_hits()
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        created = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    body = client.get(f"/jobs/{job_id}").json()
    assert "research" in body["stage_timings"]
    profile = client.get(f"/jobs/{job_id}/profile").json()
    assert profile["stages"]
    rag = next(item for item in profile["stages"] if item["stage"] == "rag")
    assert "count_timed" in rag
    assert "count_skipped" in rag
    assert rag["count_total"] == rag["count"]
    assert {item["stage"] for item in profile["stages"]} >= {"understanding", "research"}
    stages = client.get(f"/jobs/{job_id}/products/1/stages").json()
    assert stages["details"]
    research = next(item for item in stages["details"] if item["stage"] == "research")
    assert research["metrics"]["queries_attempted"] >= 1
    assert research["metrics"]["query_count"] >= research["metrics"]["queries_attempted"]
    assert research["metrics"]["queries"]
    assert "duration_ms" in research["metrics"]["queries"][0]
    research_timing = next(item for item in profile["stages"] if item["stage"] == "research")
    assert research_timing["breakdown"]["queries_attempted"] >= 1
    assert research_timing["breakdown"]["search_total_ms"] >= 0
    breakdown = client.get(f"/jobs/{job_id}/review-breakdown").json()
    assert "by_issue_type" in breakdown
    detailed = client.get(f"/jobs/{job_id}/review-breakdown?details=true").json()
    assert "lov_invalid_by_attribute" in detailed
    assert "by_attribute" in detailed


def test_stage_profile_separates_skipped_from_timed():
    from types import SimpleNamespace

    from app.services.jobs import build_stage_timing

    items = [
        SimpleNamespace(duration_ms=0.0, status="SKIPPED", metrics={}),
        SimpleNamespace(duration_ms=0.0, status="SKIPPED", metrics={}),
        SimpleNamespace(duration_ms=20047.9, status="FAILED", metrics={"fetch_ms": 20047.9}),
        SimpleNamespace(duration_ms=10000.0, status="COMPLETED", metrics={"fetch_ms": 8000.0}),
    ]
    timing = build_stage_timing("rag", items)
    assert timing.count_total == 4
    assert timing.count_timed == 2
    assert timing.count_skipped == 2
    assert timing.count_failed == 1
    assert timing.avg_ms == 15024.0
    assert timing.p50_ms == 15024.0
    assert timing.max_ms == 20047.9
    assert timing.p95_ms >= timing.p50_ms
    assert timing.breakdown["fetch_ms"] == 14024.0


def test_fetch_timeout_splits_connect_and_read():
    from app.services.fetch import FETCH_CONNECT_TIMEOUT, FETCH_READ_TIMEOUT, fetch_timeout

    timeout = fetch_timeout()
    assert timeout.connect == FETCH_CONNECT_TIMEOUT
    assert timeout.read == FETCH_READ_TIMEOUT
    assert FETCH_CONNECT_TIMEOUT < 20.0
    assert FETCH_READ_TIMEOUT < 20.0
    assert timeout.connect < timeout.read


def test_rate_limit_retry_parses_wait():
    from app.services.llm_retry import is_rate_limit_error, retry_delay_seconds

    exc = RuntimeError(
        "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
        "`openai/gpt-oss-120b`. Please try again in 6.2325s.'}}"
    )
    assert is_rate_limit_error(exc)
    assert 6.2 <= retry_delay_seconds(exc, 0) <= 7.0

    tpd = RuntimeError(
        "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
        "`openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000. "
        "Please try again in 3m17.856s.'}}"
    )
    assert is_rate_limit_error(tpd)
    assert 120.0 <= retry_delay_seconds(tpd, 0) <= 121.0

    hours = RuntimeError(
        "Rate limit reached on tokens per day (TPD). Please try again in 7h32m12.5s."
    )
    assert retry_delay_seconds(hours, 0) == 120.0
    from app.services.llm_retry import (
        classify_llm_error,
        should_retry_rate_limit,
        call_with_rate_limit_retry,
    )

    assert classify_llm_error(exc) == "LLM_RATE_LIMIT_TPM"
    assert classify_llm_error(tpd) == "LLM_QUOTA_EXHAUSTED"
    assert classify_llm_error(RuntimeError("[Errno 61] Connection refused")) == "CONNECTION_REFUSED"
    assert should_retry_rate_limit(exc) is True
    assert should_retry_rate_limit(tpd) is False
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise tpd

    try:
        call_with_rate_limit_retry(boom)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected TPD to fail fast")
    assert calls["n"] == 1


def test_tpd_switches_to_backup_groq_key():
    from app.services import chat_llm, groq_keys, llm_retry

    groq_keys.reset_groq_key_index()
    chat_llm.reset_llm_provider()
    keys_used: list[str] = []

    def fake_keys():
        return ["primary-key", "backup-key"]

    def run():
        key = groq_keys.groq_api_key()
        keys_used.append(key or "")
        if key == "primary-key":
            raise RuntimeError(
                "Error code: 429 - tokens per day (TPD): Limit 200000. "
                "Please try again in 7h0m0s."
            )
        return "ok"

    with patch.object(groq_keys, "groq_api_keys", side_effect=fake_keys):
        groq_keys.reset_groq_key_index()
        chat_llm.reset_llm_provider()
        assert llm_retry.call_with_rate_limit_retry(run) == "ok"
    assert keys_used == ["primary-key", "backup-key"]
    groq_keys.reset_groq_key_index()
    chat_llm.reset_llm_provider()


def test_tpd_falls_over_to_openrouter_after_groq_keys(monkeypatch):
    from app.services import chat_llm, groq_keys, llm_retry

    groq_keys.reset_groq_key_index()
    chat_llm.reset_llm_provider()
    providers: list[str] = []

    def fake_keys():
        return ["only-groq"]

    def run():
        providers.append("openrouter" if chat_llm.use_openrouter() else "groq")
        if not chat_llm.use_openrouter():
            raise RuntimeError(
                "Error code: 429 - tokens per day (TPD): Limit 200000. "
                "Please try again in 7h0m0s."
            )
        return "ok"

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with patch.object(groq_keys, "groq_api_keys", side_effect=fake_keys):
        groq_keys.reset_groq_key_index()
        chat_llm.reset_llm_provider()
        assert llm_retry.call_with_rate_limit_retry(run) == "ok"
    assert providers == ["groq", "openrouter"]
    chat_llm.reset_llm_provider()
    groq_keys.reset_groq_key_index()


def test_llm_metrics_split_request_wait_and_cooldown():
    import threading
    import time

    from app.services import llm_retry

    def slow():
        time.sleep(0.05)
        return "ok"

    assert llm_retry.invoke_with_llm_metrics(slow, serialize=False, apply_cooldown=False) == "ok"
    direct = llm_retry.last_llm_call_metrics()
    assert direct.llm_request_ms >= 40
    assert direct.llm_wait_ms == 0
    assert direct.llm_cooldown_ms == 0
    assert direct.llm_attempts == 1

    held = threading.Event()
    release = threading.Event()

    def holder():
        llm_retry._LLM_CALL_LOCK.acquire()
        held.set()
        release.wait(2)
        llm_retry._LLM_CALL_LOCK.release()

    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(1)
    try:
        threading.Timer(0.12, release.set).start()
        assert llm_retry.invoke_with_llm_metrics(lambda: "ok", serialize=True, apply_cooldown=False) == "ok"
        waited = llm_retry.last_llm_call_metrics()
        assert waited.llm_wait_ms >= 80
    finally:
        release.set()

    llm_retry._RATE_LIMIT_UNTIL = 0.0
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Error code: 429 - Rate limit reached.")
        return "ok"

    original_delay = llm_retry.retry_delay_seconds
    llm_retry.retry_delay_seconds = lambda exc, attempt: 0.1
    try:
        recovered = llm_retry.invoke_with_llm_metrics(flaky, serialize=False, apply_cooldown=True)
    finally:
        llm_retry.retry_delay_seconds = original_delay
        llm_retry._RATE_LIMIT_UNTIL = 0.0
    assert recovered == "ok"
    cooled = llm_retry.last_llm_call_metrics()
    assert calls["n"] == 2
    assert cooled.llm_attempts == 2
    assert cooled.llm_cooldown_ms >= 80


def test_job_start_revalidates_lov_from_extracted_values(client):
    test_review = __import__("test_review")
    test_review._prepare_normalized_product(client)
    db, gen = test_review._db(client)
    try:
        row = (
            db.query(test_review.ProductNormalizedAttributeRecord)
            .filter(
                test_review.ProductNormalizedAttributeRecord.product_id == 1,
                test_review.ProductNormalizedAttributeRecord.label == "Abrasive Material",
            )
            .one()
        )
        row.normalized_value = "Purple Magic Material"
        db.commit()
    finally:
        test_review._close_db(db, gen)
    processed = client.post("/products/1/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "REVIEW_REQUIRED"
    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", return_value=_hits()
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        created = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert created.status_code == 200
    body = created.json()
    assert body["review_required"] == 0
    breakdown = client.get(f"/jobs/{body['job_id']}/review-breakdown").json()
    assert breakdown.get("by_issue_type", {}).get("LOV_INVALID", 0) == 0


def test_products_per_minute_uses_average_duration_not_wall_clock():
    from app.services.jobs import throughput_products_per_minute

    assert throughput_products_per_minute(14660, 1) == 4.09
    assert throughput_products_per_minute(14660, 2) == 8.19
    assert throughput_products_per_minute(0, 2) == 0.0


def _db(client):
    gen = client.app.dependency_overrides[get_db]()
    return next(gen), gen


def _close_db(db, gen) -> None:
    db.close()
    try:
        next(gen)
    except StopIteration:
        pass


def test_understanding_groq_success_does_not_fail_product(client):
    _upload_one(client, mpn="OK-GROQ-001")
    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", return_value=_hits("OK-GROQ-001")
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["failed"] == 0
    assert body["processed"] == 1
    product = client.get("/products/1").json()
    assert product["status"] not in {"FAIL", "INGESTED"}
    db, gen = _db(client)
    try:
        assert (
            db.query(ProductUnderstandingRecord).filter_by(product_id=1).one_or_none()
            is not None
        )
    finally:
        _close_db(db, gen)


def test_understanding_tpd_defers_review_and_continues_job(client):
    _upload_one(client, mpn="TPD-001")
    _upload_one(client, mpn="OK-002")
    understand_calls = {"TPD-001": 0, "OK-002": 0}
    search_queries = []

    def maybe_tpd(raw):
        mpn = raw.get("mpn")
        understand_calls[mpn] = understand_calls.get(mpn, 0) + 1
        if mpn == "TPD-001":
            raise RuntimeError(TPD_ERROR)
        return _llm()

    def counting_search(query, max_results=8):
        search_queries.append(query or "")
        return _hits("OK-002")

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=maybe_tpd), patch(
        "app.services.research.search_web", side_effect=counting_search
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["total"] == 2
    assert body["processed"] == 2
    assert body["failed"] == 0
    assert body["review_required"] >= 1
    assert understand_calls["TPD-001"] == 1
    assert understand_calls["OK-002"] == 1
    assert not any("TPD-001" in query for query in search_queries)

    tpd_product = client.get("/products/1").json()
    ok_product = client.get("/products/2").json()
    assert tpd_product["status"] == "REVIEW_REQUIRED"
    assert ok_product["status"] != "FAIL"
    assert ok_product["status"] != "INGESTED"

    queue = client.get("/review-queue", params={"product_id": 1}).json()
    issues = [item["issue_type"] for item in queue["items"]]
    assert "LLM_QUOTA_EXHAUSTED" in issues
    assert "MISSING_IDENTITY" not in issues

    breakdown = client.get(f"/jobs/{body['job_id']}/review-breakdown").json()
    assert breakdown["by_issue_type"].get("LLM_QUOTA_EXHAUSTED", 0) >= 1

    errors = client.get(f"/jobs/{body['job_id']}/errors").json()
    quota_errors = [item for item in errors if item["error_type"] == "LLM_QUOTA_EXHAUSTED"]
    assert quota_errors
    assert all(item["status"] == "DEFERRED" for item in quota_errors)
    assert all(item["stage"] == "understanding" for item in quota_errors)

    stages = client.get(f"/jobs/{body['job_id']}/products/1/stages").json()
    assert stages["stages"]["understanding"] == "FAILED"
    assert stages["stages"]["research"] == "SKIPPED"
    assert stages["stages"]["extraction"] == "SKIPPED"

    db, gen = _db(client)
    try:
        assert (
            db.query(ProductUnderstandingRecord).filter_by(product_id=1).one_or_none()
            is None
        )
        assert db.query(ProductAttributeRecord).filter_by(product_id=1).count() == 0
        assert (
            db.query(ProductUnderstandingRecord).filter_by(product_id=2).one_or_none()
            is not None
        )
    finally:
        _close_db(db, gen)


def test_understanding_tpd_does_not_retry_within_job(client):
    _upload_one(client, mpn="TPD-RETRY-001")
    calls = {"n": 0}

    def boom(_raw):
        calls["n"] += 1
        raise RuntimeError(TPD_ERROR)

    with patch("app.agents.graph.invoke_understanding_llm", side_effect=boom), patch(
        "app.services.research.search_web", return_value=_hits()
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 0
    assert body["review_required"] == 1
    assert calls["n"] == 1


def test_extraction_tpd_defers_review_once_and_continues_job(client):
    _upload_one(client, mpn="TPD-EXTRACT-001")
    _upload_one(client, mpn="OK-EXTRACT-002")
    extraction_calls = {1: 0, 2: 0}
    from app.services.attribute_extraction import extract_product_attributes as original

    def maybe_tpd(product_id, db):
        extraction_calls[product_id] += 1
        if product_id == 1:
            raise RuntimeError(TPD_ERROR)
        return original(product_id, db)

    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", side_effect=_search_for_query
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.agents.graph.extract_product_attributes", side_effect=maybe_tpd
    ), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 0
    assert body["processed"] == 2
    assert body["review_required"] >= 1
    assert extraction_calls == {1: 1, 2: 1}
    assert client.get("/products/1").json()["status"] == "REVIEW_REQUIRED"
    assert client.get("/products/2").json()["status"] != "FAIL"

    queue = client.get("/review-queue", params={"product_id": 1}).json()
    assert any(item["issue_type"] == "LLM_QUOTA_EXHAUSTED" for item in queue["items"])
    breakdown = client.get(f"/jobs/{body['job_id']}/review-breakdown").json()
    assert breakdown["by_issue_type"].get("LLM_QUOTA_EXHAUSTED", 0) >= 1
    errors = client.get(f"/jobs/{body['job_id']}/errors").json()
    quota_errors = [item for item in errors if item["stage"] == "extraction"]
    assert len(quota_errors) == 1
    assert quota_errors[0]["error_type"] == "LLM_QUOTA_EXHAUSTED"
    assert quota_errors[0]["status"] == "DEFERRED"
    stages = client.get(f"/jobs/{body['job_id']}/products/1/stages").json()
    assert stages["stages"]["extraction"] == "FAILED"
    assert stages["stages"]["normalization"] == "SKIPPED"
    assert stages["stages"]["validation"] == "SKIPPED"
    db, gen = _db(client)
    try:
        assert db.query(ProductAttributeRecord).filter_by(product_id=1).count() == 0
    finally:
        _close_db(db, gen)


def test_extraction_tpd_review_survives_queue_sync(client):
    _upload_one(client, mpn="TPD-EXTRACT-SYNC-001")

    def boom(_product_id, _db):
        raise RuntimeError(TPD_ERROR)

    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", side_effect=_search_for_query
    ), patch("app.services.indexing.fetch_url_cached", return_value=_fetched()), patch(
        "app.agents.graph.extract_product_attributes", side_effect=boom
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    assert response.json()["failed"] == 0

    db, gen = _db(client)
    try:
        from app.services.review import sync_review_queue

        sync_review_queue(db, 1)
        db.commit()
    finally:
        _close_db(db, gen)

    queue = client.get("/review-queue", params={"product_id": 1}).json()
    quota = [item for item in queue["items"] if item["issue_type"] == "LLM_QUOTA_EXHAUSTED"]
    assert len(quota) == 1
    assert quota[0]["attribute"] == "Extraction"


def test_manufacturer_fetch_failure_defers_source_review_and_continues_job(client):
    _upload_one(client, mpn="FETCH-FAIL-001")
    _upload_one(client, mpn="FETCH-OK-002")
    fetched_calls = {"n": 0}

    def fetch_by_product(*args, **kwargs):
        fetched_calls["n"] += 1
        if fetched_calls["n"] == 1:
            raise RuntimeError("upstream unavailable")
        return _fetched()

    with patch("app.agents.graph.invoke_understanding_llm", return_value=_llm()), patch(
        "app.services.research.search_web", side_effect=_search_for_query
    ), patch("app.services.indexing.fetch_url_cached", side_effect=fetch_by_product), patch(
        "app.services.attribute_extraction.invoke_attribute_llm",
        return_value=test_attributes.INVENTED_LLM,
    ):
        response = client.post("/jobs", json={"auto_start": True, "generate_output": False})
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 0
    assert body["processed"] == 2
    assert client.get("/products/1").json()["status"] == "REVIEW_REQUIRED"
    assert client.get("/products/2").json()["status"] != "FAIL"
    queue = client.get("/review-queue", params={"product_id": 1}).json()
    source_issues = [item for item in queue["items"] if item["issue_type"] == "SOURCE_FETCH_FAILED"]
    assert len(source_issues) == 1
    assert "fetch failed" in source_issues[0]["reason"].lower()
    errors = client.get(f"/jobs/{body['job_id']}/errors").json()
    source_errors = [item for item in errors if item["stage"] == "rag"]
    assert len(source_errors) == 1
    assert source_errors[0]["status"] == "DEFERRED"
    assert source_errors[0]["error_type"] == "SourceFetchFailedError"
