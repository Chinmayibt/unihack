from pydantic import BaseModel, Field


JOB_QUEUED = "QUEUED"
JOB_RUNNING = "RUNNING"
JOB_PAUSED = "PAUSED"
JOB_COMPLETED = "COMPLETED"
JOB_FAILED = "FAILED"

ITEM_PENDING = "PENDING"
ITEM_RUNNING = "RUNNING"
ITEM_APPROVED = "APPROVED"
ITEM_PARTIAL = "PARTIAL"
ITEM_REVIEW = "REVIEW_REQUIRED"
ITEM_FAILED = "FAILED"
ITEM_SKIPPED = "SKIPPED"

STAGE_PENDING = "PENDING"
STAGE_RUNNING = "RUNNING"
STAGE_COMPLETED = "COMPLETED"
STAGE_FAILED = "FAILED"
STAGE_SKIPPED = "SKIPPED"

PIPELINE_STAGES = (
    "understanding",
    "entity_resolution",
    "classification",
    "research",
    "rag",
    "extraction",
    "normalization",
    "validation",
)


class JobCreateRequest(BaseModel):
    input_file: str | None = None
    auto_start: bool = True
    worker_count: int | None = None
    product_ids: list[int] | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)
    generate_output: bool = True
    force_ingest: bool = False


class JobStageStatus(BaseModel):
    stage: str
    status: str
    duration_ms: float = 0.0
    retry_count: int = 0
    llm_calls: int = 0
    search_calls: int = 0
    error_message: str | None = None
    metrics: dict = Field(default_factory=dict)


class JobProductStages(BaseModel):
    product_id: int
    stages: dict[str, str]
    details: list[JobStageStatus] = Field(default_factory=list)


class JobErrorOut(BaseModel):
    id: int
    product_id: int | None = None
    stage: str
    error_type: str
    error_message: str
    retry_count: int = 0
    status: str
    created_at: str | None = None


class JobProductOut(BaseModel):
    product_id: int
    mpn: str
    description: str
    item_status: str
    product_status: str
    brand: str | None = None
    manufacturer: str | None = None


class JobProductList(BaseModel):
    total: int = 0
    items: list[JobProductOut] = Field(default_factory=list)


class JobSummary(BaseModel):
    job_id: str
    status: str
    dataset_name: str = ""
    total: int = 0
    processed: int = 0
    approved: int = 0
    partial: int = 0
    review_required: int = 0
    failed: int = 0
    progress: float = 0.0
    worker_count: int = 1
    output_file: str | None = None
    avg_processing_ms: float = 0.0
    products_per_minute: float = 0.0
    success_rate: float = 0.0
    evidence_coverage: float = 0.0
    completeness: float = 0.0
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    stage_timings: dict[str, float] = Field(default_factory=dict)
    review_breakdown: dict[str, int] = Field(default_factory=dict)


class JobReport(BaseModel):
    job_id: str
    products: int = 0
    approved: int = 0
    partial: int = 0
    human_review: int = 0
    failed: int = 0
    success_rate: float = 0.0
    avg_processing_ms: float = 0.0
    products_per_minute: float = 0.0
    evidence_coverage: float = 0.0
    completeness: float = 0.0
    output_file: str | None = None
    summary: str = ""


class StageTiming(BaseModel):
    stage: str
    count: int = 0
    count_total: int = 0
    count_timed: int = 0
    count_skipped: int = 0
    count_failed: int = 0
    failed: int = 0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    avg_s: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)


class JobProfile(BaseModel):
    job_id: str
    total: int = 0
    processed: int = 0
    avg_processing_ms: float = 0.0
    stages: list[StageTiming] = Field(default_factory=list)
    sample_product_id: int | None = None
    sample_stages: dict[str, float] = Field(default_factory=dict)


class ReviewBreakdown(BaseModel):
    job_id: str
    total_items: int = 0
    total_products: int = 0
    by_issue_type: dict[str, int] = Field(default_factory=dict)
    products_by_issue_type: dict[str, int] = Field(default_factory=dict)
    by_attribute: dict[str, int] = Field(default_factory=dict)
    lov_invalid_by_attribute: dict[str, int] = Field(default_factory=dict)
    details: list[dict] = Field(default_factory=list)
