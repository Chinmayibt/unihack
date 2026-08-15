from __future__ import annotations

from app.database.models import ProductAttributeRecord, ProductRecord, ProductSourceRecord
from app.schemas.normalized_attribute import (
    AGREEMENT,
    CONFLICT,
    INPUT_SOURCED,
    MANUFACTURER_SUPPORTED,
    NOT_FOUND,
    SECONDARY_SOURCE_ONLY,
    SOURCE_DISTRIBUTOR,
    SOURCE_INPUT,
    SOURCE_MANUFACTURER,
    SOURCE_MARKETPLACE,
    SOURCE_OTHER,
    SOURCE_RETAILER,
    EvidenceCandidate,
)
from app.schemas.source import (
    SOURCE_DISTRIBUTOR as RESEARCH_DISTRIBUTOR,
    SOURCE_MANUFACTURER as RESEARCH_MANUFACTURER,
    SOURCE_MARKETPLACE as RESEARCH_MARKETPLACE,
    SOURCE_RETAILER as RESEARCH_RETAILER,
)
from app.services.attribute_templates import template_for_classpath
from app.services.value_normalize import comparable_key
from app.services.value_parse import parse_input_candidates, parse_secondary_grit

AUTHORITY = {
    SOURCE_INPUT: 1.0,
    SOURCE_MANUFACTURER: 1.0,
    SOURCE_DISTRIBUTOR: 0.7,
    SOURCE_RETAILER: 0.4,
    SOURCE_MARKETPLACE: 0.2,
    SOURCE_OTHER: 0.1,
}


def _authority(source: str) -> float:
    return AUTHORITY.get(source, 0.1)


def _research_to_hierarchy(source_type: str | None) -> str:
    mapping = {
        RESEARCH_MANUFACTURER: SOURCE_MANUFACTURER,
        RESEARCH_DISTRIBUTOR: SOURCE_DISTRIBUTOR,
        RESEARCH_RETAILER: SOURCE_RETAILER,
        RESEARCH_MARKETPLACE: SOURCE_MARKETPLACE,
    }
    return mapping.get(source_type or "", SOURCE_OTHER)


def input_candidates(product: ProductRecord, labels: list[str]) -> dict[str, EvidenceCandidate]:
    parsed = parse_input_candidates(product.description or "")
    found: dict[str, EvidenceCandidate] = {}
    for label in labels:
        item = parsed.get(label)
        if not item:
            continue
        found[label] = EvidenceCandidate(
            value=item["value"],
            uom=item.get("uom"),
            source=SOURCE_INPUT,
            authority=_authority(SOURCE_INPUT),
            evidence_text=item.get("evidence_text") or product.description,
        )
    return found


def manufacturer_candidates(rows: list[ProductAttributeRecord]) -> dict[str, EvidenceCandidate]:
    found: dict[str, EvidenceCandidate] = {}
    for row in rows:
        if row.status != "EXTRACTED" or not row.value:
            continue
        found[row.label] = EvidenceCandidate(
            value=row.value,
            uom=row.uom,
            source=SOURCE_MANUFACTURER,
            authority=_authority(SOURCE_MANUFACTURER),
            source_id=row.source_id,
            evidence_text=row.evidence_text,
        )
    return found


def secondary_candidates(sources: list[ProductSourceRecord], labels: list[str]) -> dict[str, list[EvidenceCandidate]]:
    found: dict[str, list[EvidenceCandidate]] = {label: [] for label in labels}
    if "Grit" not in found:
        return found
    for source in sources:
        hierarchy = _research_to_hierarchy(source.source_type)
        if hierarchy in {SOURCE_MANUFACTURER, SOURCE_INPUT}:
            continue
        parsed = parse_secondary_grit(source.title or "")
        if not parsed:
            continue
        found["Grit"].append(
            EvidenceCandidate(
                value=parsed["value"],
                uom=None,
                source=hierarchy,
                authority=_authority(hierarchy),
                source_id=source.id,
                evidence_text=parsed.get("evidence_text") or source.title,
            )
        )
    return found


def consolidate_label(
    label: str,
    *,
    input_hit: EvidenceCandidate | None,
    manufacturer_hit: EvidenceCandidate | None,
    secondary_hits: list[EvidenceCandidate],
    classpath: str | None,
) -> tuple[list[EvidenceCandidate], EvidenceCandidate | None, str]:
    candidates: list[EvidenceCandidate] = []
    if input_hit:
        candidates.append(input_hit)
    if manufacturer_hit:
        candidates.append(manufacturer_hit)
    candidates.extend(secondary_hits)

    if manufacturer_hit and input_hit:
        left = comparable_key(manufacturer_hit.value, manufacturer_hit.uom, label, classpath)
        right = comparable_key(input_hit.value, input_hit.uom, label, classpath)
        if left and right and left == right:
            return candidates, manufacturer_hit, AGREEMENT
        if left and right and left != right:
            return candidates, None, CONFLICT
        return candidates, manufacturer_hit, MANUFACTURER_SUPPORTED
    if manufacturer_hit:
        return candidates, manufacturer_hit, MANUFACTURER_SUPPORTED
    if input_hit:
        return candidates, input_hit, INPUT_SOURCED
    if secondary_hits:
        return candidates, None, SECONDARY_SOURCE_ONLY
    return candidates, None, NOT_FOUND


def consolidate_product(
    product: ProductRecord,
    classpath: str | None,
    extracted: list[ProductAttributeRecord],
    sources: list[ProductSourceRecord],
) -> list[tuple[str, list[EvidenceCandidate], EvidenceCandidate | None, str]]:
    labels = [item.label for item in template_for_classpath(classpath)]
    from_input = input_candidates(product, labels)
    from_mfr = manufacturer_candidates(extracted)
    from_secondary = secondary_candidates(sources, labels)
    rows = []
    for label in labels:
        candidates, selected, agreement = consolidate_label(
            label,
            input_hit=from_input.get(label),
            manufacturer_hit=from_mfr.get(label),
            secondary_hits=from_secondary.get(label) or [],
            classpath=classpath,
        )
        rows.append((label, candidates, selected, agreement))
    return rows
