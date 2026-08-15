from __future__ import annotations

import math
import re

from app.core.config import settings

EMBEDDING_DIM = 384

_fastembed_model = None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _hash_embed(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    for token in _tokenize(text):
        vector[hash(token) % EMBEDDING_DIM] += 1.0
        if len(token) >= 3:
            vector[hash(token[:3]) % EMBEDDING_DIM] += 0.25
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _fastembed(texts: list[str]) -> list[list[float]]:
    global _fastembed_model
    from fastembed import TextEmbedding

    if _fastembed_model is None:
        _fastembed_model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
    vectors = list(_fastembed_model.embed(texts))
    return [list(map(float, vector)) for vector in vectors]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    from app.services.cache_store import get_cached_embedding, put_cached_embedding

    cached: list[list[float] | None] = [get_cached_embedding(text) for text in texts]
    missing_indexes = [index for index, vector in enumerate(cached) if vector is None]
    if missing_indexes:
        missing_texts = [texts[index] for index in missing_indexes]
        if settings.TESTING:
            fresh = [_hash_embed(text) for text in missing_texts]
        else:
            try:
                fresh = _fastembed(missing_texts)
            except Exception:
                fresh = [_hash_embed(text) for text in missing_texts]
        for index, vector in zip(missing_indexes, fresh):
            put_cached_embedding(texts[index], vector)
            cached[index] = vector
    return [vector or _hash_embed(texts[i]) for i, vector in enumerate(cached)]


def embedding_dim() -> int:
    return EMBEDDING_DIM
