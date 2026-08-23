from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import (
    ProductAttributeRecord,
    ProductDocumentRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
    ProductValidationRecord,
)
from app.models.product import ProductStatus
from app.schemas.source import (
    CONTENT_CATALOG,
    CONTENT_MANUAL,
    CONTENT_OTHER,
    CONTENT_PRODUCT_PAGE,
    CONTENT_SPECIFICATION,
    CONTENT_TECHNICAL,
    RESEARCH_STATUS_NO_SOURCE,
    RESEARCH_STATUS_RESEARCHED,
    REVIEW_SCOPE_SOURCE_DISCOVERY,
    SOURCE_DISTRIBUTOR,
    SOURCE_MANUFACTURER,
    SOURCE_MARKETPLACE,
    SOURCE_OTHER,
    SOURCE_RETAILER,
    SOURCE_STATUS_DISCOVERED,
    ProductSource,
    ResearchMetrics,
    ResearchQueryTiming,
    ResearchResponse,
    SourceOut,
)
from app.services.entity_normalize import normalize_entity_name
from app.services.text_display import compact_alnum, preserve_display_text
from app.services.web_search import SEARCH_TIMEOUT_SECONDS, SearchHit, search_web, web_search_session

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference"

SOURCE_PRODUCT_PAGE = CONTENT_PRODUCT_PAGE
SOURCE_SPECIFICATION = CONTENT_SPECIFICATION
SOURCE_TECHNICAL = CONTENT_TECHNICAL
SOURCE_MANUAL = CONTENT_MANUAL
SOURCE_CATALOG = CONTENT_CATALOG

MARKETPLACE_HOSTS = {
    "amazon.com",
    "amazon.ca",
    "ebay.com",
    "walmart.com",
    "alibaba.com",
    "aliexpress.com",
    "etsy.com",
    "facebook.com",
    "craigslist.org",
    "temu.com",
}

RETAILER_HOSTS = {
    "homedepot.com",
    "lowes.com",
    "acehardware.com",
    "northerntool.com",
    "toolbarn.com",
    "build.com",
    "mclendons.com",
    "mccoys.com",
}

DISTRIBUTOR_HOSTS = {
    "zoro.com",
    "grainger.com",
    "mscdirect.com",
    "supplyhouse.com",
    "acwholesalers.com",
    "fastenal.com",
    "globalindustrial.com",
}

MANUFACTURER_CONTENT_AUTHORITY = {
    CONTENT_PRODUCT_PAGE: 1.0,
    CONTENT_SPECIFICATION: 0.95,
    CONTENT_TECHNICAL: 0.90,
    CONTENT_MANUAL: 0.90,
    CONTENT_CATALOG: 0.85,
    CONTENT_OTHER: 0.80,
}

AUTHORITATIVE_MIN = 0.85


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_domain_map() -> dict:
    path = REFERENCE_DIR / "manufacturer_domains.json"
    if not path.exists():
        return {"manufacturers": {}, "brands": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def manufacturer_domains(brand: str | None, manufacturer: str | None) -> list[str]:
    data = _load_domain_map()
    found: list[str] = []
    pairs = [
        (manufacturer, data.get("manufacturers") or {}),
        (brand, data.get("brands") or {}),
    ]
    for value, mapping in pairs:
        needle = normalize_entity_name(value)
        if not needle:
            continue
        for name, domains in mapping.items():
            key = normalize_entity_name(name)
            if needle == key or needle.startswith(key) or key.startswith(needle):
                found.extend(domains)
    ordered: list[str] = []
    for domain in found:
        host = domain.lower().removeprefix("www.")
        if host not in ordered:
            ordered.append(host)
    return ordered


def build_research_input(
    raw_product: dict,
    understanding: dict,
    entity_resolution: dict,
    classification: dict,
) -> dict:
    brand_match = entity_resolution.get("brand") or {}
    manufacturer_match = entity_resolution.get("manufacturer") or {}
    brand = (
        brand_match.get("canonical")
        or understanding.get("brand_candidate")
        or None
    )
    manufacturer = (
        manufacturer_match.get("canonical")
        or understanding.get("manufacturer_candidate")
        or raw_product.get("manufacturer")
        or None
    )
    product_type = preserve_display_text(understanding.get("product_type"))
    classpath = classification.get("classpath") or ""
    return {
        "mpn": raw_product.get("mpn") or "",
        "product_type": product_type,
        "brand": preserve_display_text(brand),
        "manufacturer": preserve_display_text(manufacturer),
        "department": classification.get("department"),
        "class": classification.get("class_name"),
        "fine": classification.get("fine"),
        "classpath": classpath,
    }


def build_search_queries(context: dict) -> list[str]:
    mpn = (context.get("mpn") or "").strip()
    if not mpn:
        return []
    queries: list[str] = []
    brand = (context.get("brand") or "").strip()
    if brand:
        queries.append(f"{mpn} {brand}")
    for domain in manufacturer_domains(context.get("brand"), context.get("manufacturer")):
        queries.append(f"{mpn} site:{domain}")
    queries.append(mpn)
    product_type = (context.get("product_type") or "").strip()
    if product_type:
        queries.append(f"{mpn} {product_type}")
    queries.append(f"{mpn} specification")
    queries.append(f"{mpn} PDF")
    ordered: list[str] = []
    for query in queries:
        if query not in ordered:
            ordered.append(query)
    return ordered


def split_search_tiers(queries: list[str], context: dict) -> tuple[list[str], list[str]]:
    """High-value brand/domain queries vs sequential fallbacks."""
    mpn = (context.get("mpn") or "").strip()
    brand = (context.get("brand") or "").strip()
    brand_query = f"{mpn} {brand}" if mpn and brand else None
    site_prefix = f"{mpn} site:" if mpn else None
    tier1: list[str] = []
    tier2: list[str] = []
    for query in queries:
        if brand_query and query == brand_query:
            tier1.append(query)
        elif site_prefix and query.startswith(site_prefix):
            tier1.append(query)
        else:
            tier2.append(query)
    return tier1, tier2


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower() or "https", host, path, "", parsed.query, ""))


def _host_kind(host: str, manufacturer_hosts: list[str]) -> str:
    for domain in manufacturer_hosts:
        if host == domain or host.endswith("." + domain):
            return "manufacturer"
    for domain in MARKETPLACE_HOSTS:
        if host == domain or host.endswith("." + domain):
            return "marketplace"
    for domain in DISTRIBUTOR_HOSTS:
        if host == domain or host.endswith("." + domain):
            return "distributor"
    for domain in RETAILER_HOSTS:
        if host == domain or host.endswith("." + domain):
            return "retailer"
    return "unknown"


def infer_source_class(host_kind: str) -> str:
    return {
        "manufacturer": SOURCE_MANUFACTURER,
        "distributor": SOURCE_DISTRIBUTOR,
        "retailer": SOURCE_RETAILER,
        "marketplace": SOURCE_MARKETPLACE,
    }.get(host_kind, SOURCE_OTHER)


def infer_content_type(url: str, title: str, snippet: str, host_kind: str) -> str:
    blob = f"{url} {title} {snippet}".lower()
    is_pdf = bool(re.search(r"\.pdf($|\?)", url.lower())) or "filetype:pdf" in blob
    if is_pdf:
        if any(word in blob for word in ("install", "manual", "instruction")):
            return CONTENT_MANUAL
        if "catalog" in blob:
            return CONTENT_CATALOG
        if any(word in blob for word in ("spec", "datasheet", "data sheet")):
            return CONTENT_SPECIFICATION
        return CONTENT_TECHNICAL
    if "catalog" in blob:
        return CONTENT_CATALOG
    if any(word in blob for word in ("install", "manual", "instruction")):
        return CONTENT_MANUAL
    if any(word in blob for word in ("spec", "datasheet", "data sheet")):
        return CONTENT_SPECIFICATION
    if host_kind == "manufacturer":
        return CONTENT_PRODUCT_PAGE
    return CONTENT_OTHER


def authority_score(host_kind: str, content_type: str) -> float:
    if host_kind == "manufacturer":
        return MANUFACTURER_CONTENT_AUTHORITY.get(content_type, 0.80)
    if host_kind == "distributor":
        return 0.50
    if host_kind == "retailer":
        return 0.45
    if host_kind == "marketplace":
        return 0.20
    return 0.10


def mpn_match_haystack(mpn: str, url: str, title: str, snippet: str) -> bool:
    needle = compact_alnum(mpn)
    if not needle:
        return False
    hay = compact_alnum(f"{url} {title} {snippet}")
    return needle in hay


def relevance_score(hit: SearchHit, context: dict) -> float:
    mpn = context.get("mpn") or ""
    if not mpn_match_haystack(mpn, hit.url, hit.title, hit.snippet):
        return 0.0
    score = 0.0
    mpn_c = compact_alnum(mpn)
    if mpn_c in compact_alnum(hit.url):
        score += 0.50
    elif mpn_c in compact_alnum(hit.title):
        score += 0.40
    else:
        score += 0.30
    brand = compact_alnum(context.get("brand"))
    if brand and brand in compact_alnum(f"{hit.url} {hit.title} {hit.snippet}"):
        score += 0.20
    product_type = compact_alnum(context.get("product_type"))
    if product_type and product_type in compact_alnum(f"{hit.title} {hit.snippet}"):
        score += 0.15
    blob = f"{hit.url} {hit.title} {hit.snippet}".lower()
    if ".pdf" in hit.url.lower() or "spec" in blob:
        score += 0.10
    return min(1.0, round(score, 4))


@dataclass
class RankedHit:
    source: ProductSource
    rank: float


def rank_hits(
    hits: list[SearchHit],
    context: dict,
    product_id: int,
) -> list[ProductSource]:
    manufacturer_hosts = manufacturer_domains(context.get("brand"), context.get("manufacturer"))
    ranked: list[RankedHit] = []
    seen: set[str] = set()
    for hit in hits:
        if not hit.url:
            continue
        normalized = _normalize_url(hit.url)
        if normalized in seen:
            continue
        if not mpn_match_haystack(context.get("mpn") or "", hit.url, hit.title, hit.snippet):
            continue
        host = _host(hit.url)
        kind = _host_kind(host, manufacturer_hosts)
        source_type = infer_source_class(kind)
        content_type = infer_content_type(hit.url, hit.title, hit.snippet, kind)
        authority = authority_score(kind, content_type)
        relevance = relevance_score(hit, context)
        seen.add(normalized)
        ranked.append(
            RankedHit(
                source=ProductSource(
                    product_id=product_id,
                    url=hit.url,
                    source_type=source_type,
                    content_type=content_type,
                    title=hit.title or None,
                    manufacturer=context.get("manufacturer"),
                    relevance_score=relevance,
                    authority_score=authority,
                    status=SOURCE_STATUS_DISCOVERED,
                ),
                rank=authority * 100 + relevance * 50,
            )
        )
    ranked.sort(key=lambda item: item.rank, reverse=True)
    limit = settings.RESEARCH_MAX_SOURCES
    return [item.source for item in ranked[:limit]]


@dataclass
class DiscoverSourcesResult:
    sources: list[ProductSource]
    metrics: ResearchMetrics


def _dedupe_hits(raw_hits: list[SearchHit], seen_urls: set[str]) -> list[SearchHit]:
    collected: list[SearchHit] = []
    for hit in raw_hits:
        key = _normalize_url(hit.url) if hit.url else ""
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        collected.append(hit)
    return collected


def _timed_search_web(query: str) -> tuple[str, list[SearchHit], float]:
    started = perf_counter()
    raw_hits = search_web(query, max_results=8)
    duration_ms = round((perf_counter() - started) * 1000.0, 3)
    return query, raw_hits, duration_ms


def _search_query(query: str, seen_urls: set[str]) -> tuple[list[SearchHit], ResearchQueryTiming]:
    _query, raw_hits, duration_ms = _timed_search_web(query)
    collected = _dedupe_hits(raw_hits, seen_urls)
    return collected, ResearchQueryTiming(
        query=query,
        duration_ms=duration_ms,
        hits=len(raw_hits),
        manufacturer_found=False,
    )


def _search_parallel_batch(
    queries: list[str],
    seen_urls: set[str],
) -> tuple[list[tuple[list[SearchHit], ResearchQueryTiming]], int]:
    """Run a tier concurrently when more than one query is available."""
    if not queries:
        return [], 0
    if len(queries) == 1:
        return [_search_query(queries[0], seen_urls)], 0

    by_query: dict[str, tuple[list[SearchHit], float]] = {}
    timeout = max(1.0, SEARCH_TIMEOUT_SECONDS + 1.0)
    pool = ThreadPoolExecutor(max_workers=len(queries))
    try:
        futures = {pool.submit(_timed_search_web, query): query for query in queries}
        try:
            for future in as_completed(futures, timeout=timeout):
                query, raw_hits, duration_ms = future.result(timeout=0.1)
                by_query[query] = (raw_hits, duration_ms)
        except TimeoutError:
            pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    for query in queries:
        if query not in by_query:
            by_query[query] = ([], round(timeout * 1000.0, 3))

    ordered: list[tuple[list[SearchHit], ResearchQueryTiming]] = []
    for query in queries:
        raw_hits, duration_ms = by_query[query]
        collected = _dedupe_hits(raw_hits, seen_urls)
        ordered.append(
            (
                collected,
                ResearchQueryTiming(
                    query=query,
                    duration_ms=duration_ms,
                    hits=len(raw_hits),
                    manufacturer_found=False,
                ),
            )
        )
    return ordered, 1


def build_research_metrics(
    *,
    query_count: int,
    timings: list[ResearchQueryTiming],
    manufacturer_found: bool,
    cache_hit: bool = False,
    search_total_ms: float | None = None,
    parallel_batches: int = 0,
    tier1_wall_ms: float = 0.0,
    tier2_wall_ms: float = 0.0,
    tier1_queries: int = 0,
    tier2_queries: int = 0,
) -> ResearchMetrics:
    attempted = len(timings)
    durations = [item.duration_ms for item in timings]
    until = 0
    if manufacturer_found:
        for index, item in enumerate(timings, start=1):
            if item.manufacturer_found:
                until = index
                break
        if until == 0:
            until = attempted
    if search_total_ms is None:
        total = round(sum(durations), 3) if durations else 0.0
    else:
        total = round(search_total_ms, 3)
    return ResearchMetrics(
        query_count=query_count,
        queries_attempted=attempted,
        queries_until_manufacturer_found=until,
        search_total_ms=total,
        search_avg_ms=round(total / attempted, 3) if attempted else 0.0,
        search_max_ms=round(max(durations), 3) if durations else 0.0,
        parallel_batches=parallel_batches,
        tier1_wall_ms=round(tier1_wall_ms, 3),
        tier2_wall_ms=round(tier2_wall_ms, 3),
        tier1_queries=tier1_queries,
        tier2_queries=tier2_queries,
        early_exit=bool(manufacturer_found and attempted < query_count),
        manufacturer_found=manufacturer_found,
        cache_hit=cache_hit,
        queries=list(timings),
    )


def cached_research_metrics(context: dict, sources: list[ProductSource]) -> ResearchMetrics:
    return build_research_metrics(
        query_count=len(build_search_queries(context)),
        timings=[],
        manufacturer_found=manufacturer_source_found(sources),
        cache_hit=True,
    )


def discover_sources(context: dict, product_id: int) -> DiscoverSourcesResult:
    queries = build_search_queries(context)
    tier1, tier2 = split_search_tiers(queries, context)
    seen_urls: set[str] = set()
    hits: list[SearchHit] = []
    timings: list[ResearchQueryTiming] = []
    limit = settings.RESEARCH_MAX_SOURCES
    ranked: list[ProductSource] = []
    parallel_batches = 0
    tier1_wall_ms = 0.0
    tier2_wall_ms = 0.0
    tier1_queries = 0
    tier2_queries = 0
    search_started = perf_counter()

    def ingest(
        batch: list[tuple[list[SearchHit], ResearchQueryTiming]],
    ) -> list[ProductSource]:
        for collected, timing in batch:
            hits.extend(collected)
            own = rank_hits(collected, context, product_id)[:limit]
            timing.manufacturer_found = manufacturer_source_found(own)
            timings.append(timing)
        return rank_hits(hits, context, product_id)[:limit]

    def metrics_for(found: bool) -> ResearchMetrics:
        elapsed = round((perf_counter() - search_started) * 1000.0, 3)
        return build_research_metrics(
            query_count=len(queries),
            timings=timings,
            manufacturer_found=found,
            search_total_ms=elapsed,
            parallel_batches=parallel_batches,
            tier1_wall_ms=tier1_wall_ms,
            tier2_wall_ms=tier2_wall_ms,
            tier1_queries=tier1_queries,
            tier2_queries=tier2_queries,
        )

    with web_search_session():
        if tier1:
            started = perf_counter()
            batch, batches = _search_parallel_batch(tier1, seen_urls)
            tier1_wall_ms = round((perf_counter() - started) * 1000.0, 3)
            parallel_batches += batches
            tier1_queries = len(batch)
            ranked = ingest(batch)
            if manufacturer_source_found(ranked):
                return DiscoverSourcesResult(sources=ranked, metrics=metrics_for(True))

        if tier2:
            started = perf_counter()
            batch, batches = _search_parallel_batch(tier2, seen_urls)
            tier2_wall_ms = round((perf_counter() - started) * 1000.0, 3)
            parallel_batches += batches
            tier2_queries = len(batch)
            ranked = ingest(batch)
            if manufacturer_source_found(ranked):
                return DiscoverSourcesResult(sources=ranked, metrics=metrics_for(True))

        ranked = rank_hits(hits, context, product_id)[:limit]
        found = manufacturer_source_found(ranked)
        return DiscoverSourcesResult(sources=ranked, metrics=metrics_for(found))


def persist_sources(db: Session, product_id: int, sources: list[ProductSource]) -> None:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")

    from app.services.review import delete_pending_reviews

    delete_pending_reviews(db, product_id)
    db.query(ProductValidationRecord).filter(
        ProductValidationRecord.product_id == product_id
    ).delete(synchronize_session=False)
    db.query(ProductNormalizedAttributeRecord).filter(
        ProductNormalizedAttributeRecord.product_id == product_id
    ).delete(synchronize_session=False)
    db.query(ProductAttributeRecord).filter(ProductAttributeRecord.product_id == product_id).delete(
        synchronize_session=False
    )
    db.query(ProductDocumentRecord).filter(ProductDocumentRecord.product_id == product_id).delete(
        synchronize_session=False
    )
    db.query(ProductSourceRecord).filter(ProductSourceRecord.product_id == product_id).delete(
        synchronize_session=False
    )
    retrieved_at = _utcnow()
    for source in sources:
        db.add(
            ProductSourceRecord(
                product_id=product_id,
                url=source.url,
                title=source.title,
                source_type=source.source_type,
                content_type=source.content_type,
                manufacturer=source.manufacturer,
                relevance_score=source.relevance_score,
                authority_score=source.authority_score,
                status=source.status,
                retrieved_at=retrieved_at,
            )
        )

    found_manufacturer = manufacturer_source_found(sources)
    product.status = (
        ProductStatus.RESEARCHED.value
        if found_manufacturer
        else ProductStatus.NO_AUTHORITATIVE_SOURCE.value
    )
    product.updated_at = retrieved_at
    db.flush()


def manufacturer_source_found(sources: list[ProductSource]) -> bool:
    return any(source.source_type == SOURCE_MANUFACTURER for source in sources)


def research_status_for(sources: list[ProductSource]) -> tuple[str, bool]:
    """Review flag is source-discovery only — not product validation."""
    if manufacturer_source_found(sources):
        return RESEARCH_STATUS_RESEARCHED, False
    return RESEARCH_STATUS_NO_SOURCE, True


def sources_to_response(
    product_id: int,
    sources: list[ProductSource],
    metrics: ResearchMetrics | dict | None = None,
) -> ResearchResponse:
    status, requires_review = research_status_for(sources)
    return ResearchResponse(
        product_id=product_id,
        status=status,
        sources_found=len(sources),
        manufacturer_source_found=manufacturer_source_found(sources),
        sources=[SourceOut.model_validate(source.model_dump()) for source in sources],
        requires_review=requires_review,
        review_scope=REVIEW_SCOPE_SOURCE_DISCOVERY,
        metrics=ResearchMetrics.model_validate(metrics or {}),
    )


def get_sources(product_id: int, db: Session) -> ResearchResponse:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise LookupError(f"Product {product_id} not found")
    rows = (
        db.query(ProductSourceRecord)
        .filter(ProductSourceRecord.product_id == product_id)
        .order_by(
            ProductSourceRecord.authority_score.desc(),
            ProductSourceRecord.relevance_score.desc(),
        )
        .all()
    )
    sources = [
        ProductSource(
            product_id=product_id,
            url=row.url,
            source_type=row.source_type,
            content_type=getattr(row, "content_type", None) or CONTENT_OTHER,
            title=row.title,
            manufacturer=row.manufacturer,
            relevance_score=row.relevance_score,
            authority_score=row.authority_score,
            status=row.status,
        )
        for row in rows
    ]
    if not rows:
        if product.status in {
            ProductStatus.NO_AUTHORITATIVE_SOURCE.value,
            ProductStatus.RESEARCHED.value,
        }:
            return ResearchResponse(
                product_id=product_id,
                status=RESEARCH_STATUS_NO_SOURCE,
                sources_found=0,
                manufacturer_source_found=False,
                sources=[],
                requires_review=True,
                review_scope=REVIEW_SCOPE_SOURCE_DISCOVERY,
            )
        raise LookupError(f"Product {product_id} has not been researched yet")
    return sources_to_response(product_id, sources)
