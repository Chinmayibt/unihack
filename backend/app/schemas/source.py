from pydantic import BaseModel, Field, field_validator


# Authority class — who published the source.
SOURCE_MANUFACTURER = "MANUFACTURER"
SOURCE_DISTRIBUTOR = "AUTHORIZED_DISTRIBUTOR"
SOURCE_RETAILER = "RETAILER"
SOURCE_MARKETPLACE = "MARKETPLACE"
SOURCE_OTHER = "OTHER"

SOURCE_TYPES = (
    SOURCE_MANUFACTURER,
    SOURCE_DISTRIBUTOR,
    SOURCE_RETAILER,
    SOURCE_MARKETPLACE,
    SOURCE_OTHER,
)

# What kind of document it is.
CONTENT_PRODUCT_PAGE = "PRODUCT_PAGE"
CONTENT_SPECIFICATION = "SPECIFICATION"
CONTENT_TECHNICAL = "TECHNICAL_DOCUMENT"
CONTENT_MANUAL = "INSTALLATION_MANUAL"
CONTENT_CATALOG = "CATALOG"
CONTENT_OTHER = "OTHER"

SOURCE_STATUS_DISCOVERED = "DISCOVERED"
RESEARCH_STATUS_RESEARCHED = "RESEARCHED"
RESEARCH_STATUS_NO_SOURCE = "NO_AUTHORITATIVE_SOURCE"
REVIEW_SCOPE_SOURCE_DISCOVERY = "source_discovery"


class ProductSource(BaseModel):
    product_id: int
    url: str
    source_type: str
    content_type: str = CONTENT_OTHER
    title: str | None = None
    manufacturer: str | None = None
    relevance_score: float = 0.0
    authority_score: float = 0.0
    status: str = SOURCE_STATUS_DISCOVERED

    @field_validator("relevance_score", "authority_score", mode="before")
    @classmethod
    def clamp_score(cls, value: object) -> float:
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, score))


class SourceOut(BaseModel):
    url: str
    source_type: str
    content_type: str = CONTENT_OTHER
    title: str | None = None
    manufacturer: str | None = None
    relevance_score: float = 0.0
    authority_score: float = 0.0
    status: str = SOURCE_STATUS_DISCOVERED


class ResearchQueryTiming(BaseModel):
    query: str
    duration_ms: float = 0.0
    hits: int = 0
    manufacturer_found: bool = False


class ResearchMetrics(BaseModel):
    query_count: int = 0
    queries_attempted: int = 0
    queries_until_manufacturer_found: int = 0
    search_total_ms: float = 0.0
    search_avg_ms: float = 0.0
    search_max_ms: float = 0.0
    parallel_batches: int = 0
    tier1_wall_ms: float = 0.0
    tier2_wall_ms: float = 0.0
    tier1_queries: int = 0
    tier2_queries: int = 0
    early_exit: bool = False
    manufacturer_found: bool = False
    cache_hit: bool = False
    queries: list[ResearchQueryTiming] = Field(default_factory=list)


class ResearchResponse(BaseModel):
    product_id: int
    status: str
    sources_found: int
    manufacturer_source_found: bool = False
    sources: list[SourceOut] = Field(default_factory=list)
    requires_review: bool = False
    review_scope: str = REVIEW_SCOPE_SOURCE_DISCOVERY
    metrics: ResearchMetrics = Field(default_factory=ResearchMetrics)
