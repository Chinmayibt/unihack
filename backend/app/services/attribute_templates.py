from __future__ import annotations

import json
from pathlib import Path

from app.schemas.attribute import AttributeTemplateItem

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference"


def _load_templates() -> dict:
    path = REFERENCE_DIR / "attribute_templates.json"
    if not path.exists():
        return {"templates": [], "default": []}
    return json.loads(path.read_text(encoding="utf-8"))


def template_for_classpath(classpath: str | None) -> list[AttributeTemplateItem]:
    data = _load_templates()
    needle = (classpath or "").strip()
    for row in data.get("templates") or []:
        if (row.get("classpath") or "").strip() == needle:
            return [
                AttributeTemplateItem(
                    label=item["label"],
                    query=item["query"],
                    required=bool(item.get("required", False)),
                    expects_uom=bool(item.get("expects_uom", False)),
                    uom_family=item.get("uom_family"),
                )
                for item in row.get("attributes") or []
                if item.get("label") and item.get("query")
            ]
    return [
        AttributeTemplateItem(
            label=item["label"],
            query=item["query"],
            required=bool(item.get("required", False)),
            expects_uom=bool(item.get("expects_uom", False)),
            uom_family=item.get("uom_family"),
        )
        for item in data.get("default") or []
        if item.get("label") and item.get("query")
    ]
