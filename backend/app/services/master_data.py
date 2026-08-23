from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.database.models import BrandRecord, ManufacturerRecord, TaxonomyRecord
from app.services.entity_normalize import normalize_entity_name

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference"


def _load_json(name: str) -> list[dict]:
    path = REFERENCE_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def seed_master_data(db: Session, replace: bool = False) -> dict[str, int]:
    if replace:
        db.query(BrandRecord).delete()
        db.query(ManufacturerRecord).delete()
        db.query(TaxonomyRecord).delete()
        db.flush()

    brand_count = db.query(BrandRecord).count()
    manufacturer_count = db.query(ManufacturerRecord).count()

    if brand_count == 0:
        for row in _load_json("brands.json"):
            canonical = row["canonical_name"]
            aliases = [alias for alias in row.get("aliases", []) if alias != canonical]
            db.add(
                BrandRecord(
                    canonical_name=canonical,
                    normalized_name=normalize_entity_name(canonical),
                    aliases=aliases,
                )
            )
    if manufacturer_count == 0:
        for row in _load_json("manufacturers.json"):
            canonical = row["canonical_name"]
            aliases = [alias for alias in row.get("aliases", []) if alias != canonical]
            db.add(
                ManufacturerRecord(
                    canonical_name=canonical,
                    normalized_name=normalize_entity_name(canonical),
                    aliases=aliases,
                )
            )

    if db.query(TaxonomyRecord).count() == 0:
        for row in _load_json("taxonomy.json"):
            db.add(
                TaxonomyRecord(
                    department=row["department"],
                    class_name=row["class_name"],
                    fine=row["fine"],
                    classpath=row["classpath"],
                    aliases=row.get("aliases") or [],
                )
            )
    db.flush()
    return {
        "brands": db.query(BrandRecord).count(),
        "manufacturers": db.query(ManufacturerRecord).count(),
        "taxonomy": db.query(TaxonomyRecord).count(),
    }
