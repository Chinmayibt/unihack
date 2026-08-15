from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.product import ProductStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductRecord(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_index: Mapped[int] = mapped_column(Integer, nullable=False)
    mpn: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    e1_brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unilog_brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dib_brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(64), nullable=False, default=ProductStatus.INGESTED.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    understandings: Mapped[list["ProductUnderstandingRecord"]] = relationship(
        back_populates="product"
    )
    entity_resolutions: Mapped[list["EntityResolutionRecord"]] = relationship(
        back_populates="product"
    )
    classifications: Mapped[list["ProductClassificationRecord"]] = relationship(
        back_populates="product"
    )
    sources: Mapped[list["ProductSourceRecord"]] = relationship(
        back_populates="product"
    )
    documents: Mapped[list["ProductDocumentRecord"]] = relationship(
        back_populates="product"
    )
    attributes: Mapped[list["ProductAttributeRecord"]] = relationship(
        back_populates="product"
    )
    normalized_attributes: Mapped[list["ProductNormalizedAttributeRecord"]] = relationship(
        back_populates="product"
    )
    validations: Mapped[list["ProductValidationRecord"]] = relationship(
        back_populates="product"
    )
    reviews: Mapped[list["ReviewQueueRecord"]] = relationship(
        back_populates="product"
    )
    stage_runs: Mapped[list["ProductStageRun"]] = relationship(
        back_populates="product"
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_mpn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_description: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_mpns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_manufacturer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_brand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ProductUnderstandingRecord(Base):
    __tablename__ = "product_understanding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, unique=True, index=True
    )
    product_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_candidate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer_candidate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    extracted_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    candidate_attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="understandings")


class ManufacturerRecord(Base):
    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class BrandRecord(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class EntityResolutionRecord(Base):
    __tablename__ = "entity_resolution"
    __table_args__ = (UniqueConstraint("product_id", "entity_type", name="uq_entity_resolution_product_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    brand_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="entity_resolutions")


class TaxonomyRecord(Base):
    __tablename__ = "taxonomy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    class_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fine: Mapped[str] = mapped_column(String(255), nullable=False)
    classpath: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ProductClassificationRecord(Base):
    __tablename__ = "product_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, unique=True, index=True
    )
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fine: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classpath: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="classifications")


class ProductSourceRecord(Base):
    __tablename__ = "product_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False, default="OTHER")
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    authority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOVERED")
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="sources")
    documents: Mapped[list["ProductDocumentRecord"]] = relationship(
        back_populates="source"
    )


class ProductDocumentRecord(Base):
    __tablename__ = "product_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("product_sources.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="documents")
    source: Mapped[ProductSourceRecord] = relationship(back_populates="documents")
    attributes: Mapped[list["ProductAttributeRecord"]] = relationship(
        back_populates="document"
    )


class ProductAttributeRecord(Base):
    __tablename__ = "product_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uom: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_sources.id"), nullable=True, index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_documents.id"), nullable=True, index=True
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_FOUND")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="attributes")
    document: Mapped["ProductDocumentRecord | None"] = relationship(back_populates="attributes")


class ProductNormalizedAttributeRecord(Base):
    __tablename__ = "product_normalized_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_uom: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_uom: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_sources.id"), nullable=True, index=True
    )
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agreement: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_FOUND")
    candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    normalization_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_FOUND")
    ai_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    human_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="normalized_attributes")


class ProductValidationRecord(Base):
    __tablename__ = "product_validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    missing_attributes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_for_output: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    product: Mapped[ProductRecord] = relationship(back_populates="validations")


class ReviewQueueRecord(Base):
    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="HIGH")
    attribute: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    candidate_values: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    final_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    product: Mapped[ProductRecord] = relationship(back_populates="reviews")


class ProcessingJobRecord(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED", index=True)
    total_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generate_output: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    output_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    items: Mapped[list["ProcessingJobItem"]] = relationship(back_populates="job")
    errors: Mapped[list["ProcessingErrorRecord"]] = relationship(back_populates="job")
    stage_runs: Mapped[list["ProductStageRun"]] = relationship(back_populates="job")


class ProcessingJobItem(Base):
    __tablename__ = "processing_job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "product_id", name="uq_processing_job_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_retrieved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_retrieved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attributes_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job: Mapped[ProcessingJobRecord] = relationship(back_populates="items")
    product: Mapped[ProductRecord] = relationship()


class ProductStageRun(Base):
    __tablename__ = "product_stage_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "product_id", "stage", name="uq_product_stage_run"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job: Mapped[ProcessingJobRecord] = relationship(back_populates="stage_runs")
    product: Mapped[ProductRecord] = relationship(back_populates="stage_runs")


class ProcessingErrorRecord(Base):
    __tablename__ = "processing_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[str] = mapped_column(String(64), nullable=False, default="STAGE_FAILED")
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="FAILED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    job: Mapped[ProcessingJobRecord] = relationship(back_populates="errors")


class ResearchCacheRecord(Base):
    __tablename__ = "research_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sources_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class DocumentCacheRecord(Base):
    __tablename__ = "document_cache"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    content_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    final_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )




