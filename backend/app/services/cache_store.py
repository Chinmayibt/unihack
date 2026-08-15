from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database.models import DocumentCacheRecord, ResearchCacheRecord
from app.schemas.source import ProductSource
from app.services.fetch import FetchedDocument, fetch_url

_RUNTIME_LOCK = threading.Lock()
_ENTITY_CACHE: dict[str, dict] = {}
_CLASSIFICATION_CACHE: dict[str, dict] = {}
_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDING_CACHE_MAX = 4096
_UNDERSTANDING_CACHE: dict[str, dict] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clear_runtime_caches() -> None:
    with _RUNTIME_LOCK:
        _ENTITY_CACHE.clear()
        _CLASSIFICATION_CACHE.clear()
        _EMBEDDING_CACHE.clear()
        _UNDERSTANDING_CACHE.clear()


def clear_classification_cache() -> None:
    with _RUNTIME_LOCK:
        _CLASSIFICATION_CACHE.clear()


def get_cached_entity(key: str) -> dict | None:
    if not key:
        return None
    with _RUNTIME_LOCK:
        payload = _ENTITY_CACHE.get(key)
        return dict(payload) if payload else None


def put_cached_entity(key: str, payload: dict) -> None:
    if not key:
        return
    with _RUNTIME_LOCK:
        _ENTITY_CACHE[key] = dict(payload)


def get_cached_classification(key: str) -> dict | None:
    if not key:
        return None
    with _RUNTIME_LOCK:
        payload = _CLASSIFICATION_CACHE.get(key)
        return dict(payload) if payload else None


def put_cached_classification(key: str, payload: dict) -> None:
    if not key:
        return
    with _RUNTIME_LOCK:
        _CLASSIFICATION_CACHE[key] = dict(payload)


def embedding_cache_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def get_cached_embedding(text: str) -> list[float] | None:
    key = embedding_cache_key(text)
    with _RUNTIME_LOCK:
        vector = _EMBEDDING_CACHE.get(key)
        return list(vector) if vector is not None else None


def put_cached_embedding(text: str, vector: list[float]) -> None:
    key = embedding_cache_key(text)
    with _RUNTIME_LOCK:
        if len(_EMBEDDING_CACHE) >= _EMBEDDING_CACHE_MAX:
            _EMBEDDING_CACHE.pop(next(iter(_EMBEDDING_CACHE)))
        _EMBEDDING_CACHE[key] = list(vector)


def understanding_cache_key(raw_product: dict) -> str:
    payload = {
        "mpn": (raw_product.get("mpn") or "").strip().lower(),
        "description": (raw_product.get("description") or "").strip().lower(),
        "manufacturer": (raw_product.get("manufacturer") or "").strip().lower(),
        "e1_brand": (raw_product.get("e1_brand") or "").strip().lower(),
        "unilog_brand": (raw_product.get("unilog_brand") or "").strip().lower(),
        "dib_brand": (raw_product.get("dib_brand") or "").strip().lower(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def get_cached_understanding(raw_product: dict) -> dict | None:
    key = understanding_cache_key(raw_product)
    with _RUNTIME_LOCK:
        payload = _UNDERSTANDING_CACHE.get(key)
        return dict(payload) if payload else None


def put_cached_understanding(raw_product: dict, payload: dict) -> None:
    key = understanding_cache_key(raw_product)
    with _RUNTIME_LOCK:
        _UNDERSTANDING_CACHE[key] = dict(payload)


def research_cache_key(context: dict) -> str:
    payload = {
        "mpn": (context.get("mpn") or "").strip().lower(),
        "brand": (context.get("brand") or "").strip().lower(),
        "manufacturer": (context.get("manufacturer") or "").strip().lower(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def get_cached_sources(db: Session, context: dict) -> list[ProductSource] | None:
    row = db.get(ResearchCacheRecord, research_cache_key(context))
    if row is None:
        return None
    return [ProductSource.model_validate(item) for item in (row.sources_json or [])]


def put_cached_sources(db: Session, context: dict, sources: list[ProductSource]) -> None:
    key = research_cache_key(context)
    payload = [source.model_dump() for source in sources]
    row = db.get(ResearchCacheRecord, key)
    if row is None:
        db.add(ResearchCacheRecord(cache_key=key, sources_json=payload, created_at=_utcnow()))
    else:
        row.sources_json = payload
    db.flush()


def fetch_url_cached(
    url: str,
    db: Session | None = None,
    timeout: float | None = None,
    fetcher=None,
) -> FetchedDocument:
    if db is not None:
        row = db.get(DocumentCacheRecord, url)
        if row is not None:
            return FetchedDocument(
                url=url,
                content_bytes=row.content_bytes,
                content_type=row.content_type,
                final_url=row.final_url or url,
            )
    loader = fetcher or fetch_url
    fetched = loader(url, timeout=timeout)
    if db is not None:
        digest = hashlib.sha256(fetched.content_bytes).hexdigest()
        existing = db.get(DocumentCacheRecord, url)
        if existing is None:
            db.add(
                DocumentCacheRecord(
                    url=url,
                    content_bytes=fetched.content_bytes,
                    content_type=fetched.content_type,
                    final_url=fetched.final_url,
                    content_hash=digest,
                    created_at=_utcnow(),
                )
            )
        else:
            existing.content_bytes = fetched.content_bytes
            existing.content_type = fetched.content_type
            existing.final_url = fetched.final_url
            existing.content_hash = digest
        db.flush()
    return fetched
