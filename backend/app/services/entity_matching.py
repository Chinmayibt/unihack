from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.core.config import settings
from app.schemas.entity_resolution import EntityMatch
from app.services.entity_normalize import normalize_entity_name
from app.services.cache_store import get_cached_entity, put_cached_entity


@dataclass
class CatalogEntry:
    canonical_name: str
    normalized_name: str
    aliases: list[str]


STATUS_RESOLVED = "RESOLVED"
STATUS_REVIEW = "REVIEW_REQUIRED"


def _alias_list(entry: CatalogEntry) -> list[str]:
    values = [entry.canonical_name, *entry.aliases]
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if not value:
            continue
        key = value.strip()
        if key.lower() in seen:
            continue
        seen.add(key.lower())
        unique.append(key)
    return unique


def match_against_catalog(
    candidate: str | None,
    catalog: list[CatalogEntry],
    *,
    missing_method: str = "missing",
) -> EntityMatch:
    if candidate is None or not str(candidate).strip():
        return EntityMatch(
            candidate=None,
            canonical=None,
            confidence=0.0,
            method=missing_method,
            status=STATUS_REVIEW,
        )

    raw = candidate.strip()
    cache_key = f"entity::{raw}"
    cached = get_cached_entity(cache_key)
    if cached:
        return EntityMatch(candidate=raw, **cached)

    def _resolved(canonical: str, confidence: float, method: str) -> EntityMatch:
        put_cached_entity(
            cache_key,
            {
                "canonical": canonical,
                "confidence": confidence,
                "method": method,
                "status": STATUS_RESOLVED,
            },
        )
        return EntityMatch(
            candidate=raw,
            canonical=canonical,
            confidence=confidence,
            method=method,
            status=STATUS_RESOLVED,
        )

    for entry in catalog:
        for alias in _alias_list(entry):
            if raw == alias:
                return _resolved(entry.canonical_name, 1.0, "exact")

    normalized_candidate = normalize_entity_name(raw)
    if normalized_candidate:
        for entry in catalog:
            names = [entry.normalized_name, *[normalize_entity_name(a) for a in _alias_list(entry)]]
            if normalized_candidate in {name for name in names if name}:
                return _resolved(entry.canonical_name, 0.99, "normalized_exact_match")

    strong = settings.ENTITY_STRONG_MATCH
    possible = settings.ENTITY_POSSIBLE_MATCH
    best_score = 0.0
    best_entry: CatalogEntry | None = None
    for entry in catalog:
        for alias in _alias_list(entry):
            score = fuzz.token_sort_ratio(
                normalized_candidate or raw.lower(),
                normalize_entity_name(alias) or alias.lower(),
            )
            if score > best_score:
                best_score = float(score)
                best_entry = entry

    if best_entry is not None and best_score >= strong:
        return _resolved(best_entry.canonical_name, round(best_score / 100.0, 4), "rapidfuzz")
    if best_entry is not None and best_score >= possible:
        return EntityMatch(
            candidate=raw,
            canonical=best_entry.canonical_name,
            confidence=round(best_score / 100.0, 4),
            method="rapidfuzz",
            status=STATUS_REVIEW,
        )

    return EntityMatch(
        candidate=raw,
        canonical=None,
        confidence=0.71,
        method="unknown_entity",
        status=STATUS_REVIEW,
    )
