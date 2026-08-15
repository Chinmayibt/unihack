from __future__ import annotations

from app.schemas.attribute import AttributeTemplateItem
from app.schemas.normalized_attribute import CONFLICT, SECONDARY_SOURCE_ONLY


def is_populated(attribute) -> bool:
    return bool(getattr(attribute, "normalized_value", None))


def missing_attribute_labels(
    attributes: list, template: list[AttributeTemplateItem]
) -> list[str]:
    populated = {item.label for item in attributes if is_populated(item)}
    return [item.label for item in template if item.label not in populated]


def needs_review(attributes: list) -> bool:
    return any(
        getattr(item, "agreement", None) in {CONFLICT, SECONDARY_SOURCE_ONLY}
        for item in attributes
    )


def completeness_status(missing: list[str], requires_review: bool) -> str:
    if requires_review:
        return "REVIEW_REQUIRED"
    if not missing:
        return "COMPLETE"
    return "PARTIAL"
