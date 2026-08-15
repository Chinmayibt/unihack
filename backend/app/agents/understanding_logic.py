from __future__ import annotations

import re

from app.schemas.understanding import LLMProductUnderstanding, ProductUnderstanding
from app.services.ingestion import is_missing_brand_value
from app.services.text_display import preserve_display_text


def source_brand_value(raw_product: dict) -> str | None:
    """Prefer a real source brand; otherwise keep the placeholder for traceability."""
    fields = [
        raw_product.get("e1_brand"),
        raw_product.get("unilog_brand"),
        raw_product.get("dib_brand"),
    ]
    for value in fields:
        if value and not is_missing_brand_value(value):
            return value
    for value in fields:
        if value:
            return value
    return None


def has_brand_conflict(raw_product: dict, brand_candidate: str | None) -> bool:
    """True when the description brand disagrees with source brand fields."""
    if not brand_candidate or not brand_candidate.strip():
        return False

    candidate = brand_candidate.strip().lower()
    source_values = [
        raw_product.get("e1_brand"),
        raw_product.get("unilog_brand"),
        raw_product.get("dib_brand"),
    ]
    real_sources = [
        value.strip()
        for value in source_values
        if value and not is_missing_brand_value(value)
    ]
    if not real_sources:
        return True
    return not any(
        candidate == source.lower()
        or candidate in source.lower()
        or source.lower() in candidate
        for source in real_sources
    )


def _normalized_blob(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def appears_in_input(value: str, input_text: str) -> bool:
    if not value or not value.strip():
        return False
    raw = value.strip()
    lowered_input = input_text.lower()
    if raw.lower() in lowered_input:
        return True

    variants = {
        raw.lower(),
        raw.lower().replace(" in", '"'),
        raw.lower().replace('"', " in"),
        raw.lower().replace("inch", "in"),
        raw.replace(" ", "").lower(),
    }
    if any(variant and variant in lowered_input for variant in variants):
        return True

    compact_value = _normalized_blob(raw)
    compact_input = _normalized_blob(input_text)
    if len(compact_value) >= 2 and compact_value in compact_input:
        return True
    return False


def input_text_from_raw(raw_product: dict) -> str:
    return " ".join(
        str(raw_product.get(key) or "")
        for key in (
            "mpn",
            "description",
            "e1_brand",
            "unilog_brand",
            "dib_brand",
            "manufacturer",
        )
    )


def ground_terms(terms: list[str], input_text: str) -> list[str]:
    grounded: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = term.strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        if appears_in_input(cleaned, input_text):
            grounded.append(cleaned)
            seen.add(cleaned.lower())
    return grounded


def ground_attributes(attributes: dict[str, str], input_text: str) -> dict[str, str]:
    return {
        key: value
        for key, value in attributes.items()
        if appears_in_input(value, input_text)
    }


def assemble_understanding(
    raw_product: dict, llm_result: LLMProductUnderstanding
) -> ProductUnderstanding:
    """Attach source truth and conflict flags. Never take MPN from the model."""
    text = input_text_from_raw(raw_product)
    return ProductUnderstanding(
        mpn=raw_product["mpn"],
        product_type=preserve_display_text(llm_result.product_type),
        brand_candidate=preserve_display_text(llm_result.brand_candidate),
        manufacturer_candidate=preserve_display_text(llm_result.manufacturer_candidate),
        category_candidates=[
            preserve_display_text(item) or item
            for item in llm_result.category_candidates
            if item
        ],
        extracted_terms=ground_terms(
            [preserve_display_text(term) or term for term in llm_result.extracted_terms],
            text,
        ),
        candidate_attributes=ground_attributes(llm_result.candidate_attributes, text),
        confidence=llm_result.confidence,
        reasoning_summary=llm_result.reasoning_summary,
        source_brand=source_brand_value(raw_product),
        source_manufacturer=raw_product.get("manufacturer"),
        brand_conflict=has_brand_conflict(raw_product, llm_result.brand_candidate),
    )
