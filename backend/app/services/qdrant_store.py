from __future__ import annotations

from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.services.embeddings import embedding_dim

_client: QdrantClient | None = None


def reset_qdrant_client() -> None:
    global _client
    _client = None


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        if settings.TESTING:
            _client = QdrantClient(":memory:")
        else:
            _client = QdrantClient(url=settings.QDRANT_URL)
    return _client


def _collection_exists(client: QdrantClient, name: str) -> bool:
    try:
        return bool(client.collection_exists(name))
    except Exception:
        try:
            client.get_collection(name)
            return True
        except Exception:
            return False


def ensure_collection(client: QdrantClient | None = None) -> None:
    client = client or get_qdrant_client()
    name = settings.QDRANT_COLLECTION
    if _collection_exists(client, name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=embedding_dim(), distance=Distance.COSINE),
    )


def delete_product_vectors(product_id: int) -> None:
    client = get_qdrant_client()
    if not _collection_exists(client, settings.QDRANT_COLLECTION):
        return
    try:
        client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="product_id", match=MatchValue(value=product_id))]
            ),
        )
    except Exception:
        return


def upsert_chunks(vectors: list[list[float]], payloads: list[dict]) -> int:
    if not vectors:
        return 0
    client = get_qdrant_client()
    ensure_collection(client)
    points = [
        PointStruct(id=str(uuid4()), vector=vector, payload=payload)
        for vector, payload in zip(vectors, payloads)
    ]
    client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
    return len(points)


def search_product_chunks(product_id: int, query_vector: list[float], top_k: int = 5) -> list[dict]:
    client = get_qdrant_client()
    ensure_collection(client)
    query_filter = Filter(
        must=[FieldCondition(key="product_id", match=MatchValue(value=product_id))]
    )
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        points = getattr(response, "points", response)
    else:
        points = client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    hits = []
    for point in points:
        payload = point.payload or {}
        hits.append({"score": float(point.score or 0.0), **payload})
    return hits
