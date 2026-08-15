from pydantic import BaseModel, Field


class ProductDocument(BaseModel):
    product_id: int
    source_id: int
    url: str
    title: str
    document_type: str
    content: str
    page_count: int | None = None
    links: list[str] = Field(default_factory=list)


class IndexResponse(BaseModel):
    product_id: int
    documents_processed: int = 0
    chunks_created: int = 0
    vectors_created: int = 0
    status: str
    source_url: str | None = None
    fetch_ms: float = 0.0
    extract_ms: float = 0.0
    chunk_ms: float = 0.0
    embedding_ms: float = 0.0
    qdrant_ms: float = 0.0
    embed_ms: float = 0.0
