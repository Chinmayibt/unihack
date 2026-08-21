from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass, field

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database.models import IngestionJob, ProductRecord
from app.models.product import ProductStatus
from app.schemas.product import (
    IngestionStats,
    Product,
    RawProduct,
    RowError,
    UploadResponse,
)
from app.services.normalization import normalize_raw_product

REQUIRED_COLUMNS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]

CSV_FIELD_NAMES = {
    "mfg_part_num": "Mfg_Part_Num",
    "part_desc": "Part_Desc",
}

BRAND_PLACEHOLDERS = {
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
}


class MissingColumnError(ValueError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "CSV is missing required columns: " + ", ".join(missing)
        )


@dataclass
class ParsedBatch:
    products: list[Product] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    stats: IngestionStats = field(default_factory=IngestionStats)


def is_missing_brand_value(value: str | None) -> bool:
    if value is None or not str(value).strip():
        return True
    return str(value).strip().lower() in BRAND_PLACEHOLDERS


def is_missing_brand(product: Product) -> bool:
    return (
        is_missing_brand_value(product.e1_brand)
        and is_missing_brand_value(product.unilog_brand)
        and is_missing_brand_value(product.dib_brand)
    )


def read_csv_bytes(contents: bytes) -> pd.DataFrame:
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc

    df = pd.read_csv(
        io.StringIO(text),
        dtype=str,
        keep_default_na=False,
    )
    df.columns = [str(column).strip() for column in df.columns]
    return df


def validate_headers(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise MissingColumnError(missing)


def _source_index_for_row(row: dict, fallback: int) -> int:
    raw_index = row.get("index", row.get("Index"))
    if raw_index is None or str(raw_index).strip() == "":
        return fallback
    try:
        return int(str(raw_index).strip())
    except ValueError:
        return fallback


def _error_from_validation(source_index: int, exc: ValidationError) -> RowError:
    messages: list[str] = []
    for error in exc.errors():
        loc = error.get("loc", ())
        field = str(loc[0]) if loc else "row"
        csv_name = CSV_FIELD_NAMES.get(field, field)
        message = error.get("msg", "is invalid")
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        if error.get("type") == "missing" or message in {"Field required", "is missing"}:
            message = "is missing"
        messages.append(f"{csv_name} {message}")
    return RowError(row=source_index, error="; ".join(messages) or "invalid row")


def parse_and_validate(df: pd.DataFrame) -> ParsedBatch:
    """CSV → DataFrame → header check → row validation → Product objects."""
    validate_headers(df)

    batch = ParsedBatch()
    batch.stats.total_rows = len(df)

    for position, row in enumerate(df.to_dict(orient="records"), start=1):
        source_index = _source_index_for_row(row, fallback=position)
        try:
            raw = RawProduct.model_validate(row)
        except ValidationError as exc:
            error = _error_from_validation(source_index, exc)
            batch.errors.append(error)
            batch.stats.invalid_rows += 1
            lowered = error.error.lower()
            if "mfg_part_num" in lowered:
                batch.stats.missing_mpn += 1
            if "part_desc" in lowered:
                batch.stats.missing_description += 1
            continue

        product = normalize_raw_product(raw, source_index=source_index)
        batch.products.append(product)

        if is_missing_brand(product):
            batch.stats.missing_brand += 1
        if product.manufacturer is None:
            batch.stats.missing_manufacturer += 1

    batch.stats.valid_rows = len(batch.products)
    return batch


def mark_duplicate_candidates(
    products: list[Product], existing_mpns: set[str]
) -> int:
    """Mark duplicate MPNs without merging. Returns distinct duplicated MPN count."""
    counts: dict[str, int] = {}
    for product in products:
        counts[product.mpn] = counts.get(product.mpn, 0) + 1

    duplicated_values = {
        mpn
        for mpn, count in counts.items()
        if count > 1 or mpn in existing_mpns
    }

    for product in products:
        if product.mpn in duplicated_values:
            product.status = ProductStatus.DUPLICATE_CANDIDATE

    return len(duplicated_values)


def persist_products(db: Session, products: list[Product]) -> list[int]:
    records = [
        ProductRecord(
            source_index=product.source_index,
            mpn=product.mpn,
            description=product.description,
            e1_brand=product.e1_brand,
            unilog_brand=product.unilog_brand,
            dib_brand=product.dib_brand,
            manufacturer=product.manufacturer,
            status=product.status.value,
        )
        for product in products
    ]
    db.add_all(records)
    db.flush()
    return [record.id for record in records]


def _finalize_ingestion(
    db: Session,
    *,
    filename: str,
    batch: ParsedBatch,
) -> UploadResponse:
    existing_mpns = {mpn for (mpn,) in db.query(ProductRecord.mpn).all()}
    duplicate_mpns = mark_duplicate_candidates(batch.products, existing_mpns)
    batch.stats.duplicate_mpns = duplicate_mpns
    batch.stats.valid_rows = len(batch.products)

    product_ids = persist_products(db, batch.products)

    job_id = str(uuid.uuid4())
    db.add(
        IngestionJob(
            id=job_id,
            filename=filename,
            status="success",
            total_rows=batch.stats.total_rows,
            valid_rows=batch.stats.valid_rows,
            invalid_rows=batch.stats.invalid_rows,
            missing_mpn=batch.stats.missing_mpn,
            missing_description=batch.stats.missing_description,
            duplicate_mpns=batch.stats.duplicate_mpns,
            missing_manufacturer=batch.stats.missing_manufacturer,
            missing_brand=batch.stats.missing_brand,
            errors_json=json.dumps([error.model_dump() for error in batch.errors]),
        )
    )
    db.commit()

    return UploadResponse(
        status="success",
        job_id=job_id,
        total_rows=batch.stats.total_rows,
        valid_rows=batch.stats.valid_rows,
        invalid_rows=batch.stats.invalid_rows,
        missing_mpn=batch.stats.missing_mpn,
        missing_description=batch.stats.missing_description,
        duplicate_mpns=batch.stats.duplicate_mpns,
        missing_manufacturer=batch.stats.missing_manufacturer,
        missing_brand=batch.stats.missing_brand,
        errors=batch.errors,
        product_ids=product_ids,
    )


def ingest_csv(contents: bytes, filename: str, db: Session) -> UploadResponse:
    df = read_csv_bytes(contents)
    batch = parse_and_validate(df)
    return _finalize_ingestion(db, filename=filename, batch=batch)


def _normalize_json_row(raw: dict, position: int) -> dict:
    aliases = {
        "mpn": "Mfg_Part_Num",
        "mfg_part_num": "Mfg_Part_Num",
        "description": "Part_Desc",
        "part_desc": "Part_Desc",
        "e1_brand": "E1_Brand",
        "unilog_brand": "Unilog_Brand",
        "dib_brand": "DIB_Brand",
        "manufacturer": "Part_Manuf",
        "part_manuf": "Part_Manuf",
    }
    row: dict = {}
    for key, value in raw.items():
        text = str(key).strip()
        mapped = aliases.get(text.lower(), text)
        row[mapped] = value
    for column in REQUIRED_COLUMNS:
        row.setdefault(column, None)
    if "index" not in row and "Index" not in row:
        row["index"] = position
    return row


def parse_json_records(payload: object) -> ParsedBatch:
    if isinstance(payload, dict):
        records = [payload]
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValueError("JSON must be an object or an array of objects")

    batch = ParsedBatch()
    batch.stats.total_rows = len(records)
    for position, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            batch.errors.append(RowError(row=position, error="row must be an object"))
            batch.stats.invalid_rows += 1
            continue
        row = _normalize_json_row(item, position)
        source_index = _source_index_for_row(row, fallback=position)
        try:
            raw = RawProduct.model_validate(row)
        except ValidationError as exc:
            error = _error_from_validation(source_index, exc)
            batch.errors.append(error)
            batch.stats.invalid_rows += 1
            lowered = error.error.lower()
            if "mfg_part_num" in lowered:
                batch.stats.missing_mpn += 1
            if "part_desc" in lowered:
                batch.stats.missing_description += 1
            continue
        product = normalize_raw_product(raw, source_index=source_index)
        batch.products.append(product)
        if is_missing_brand(product):
            batch.stats.missing_brand += 1
        if product.manufacturer is None:
            batch.stats.missing_manufacturer += 1
    batch.stats.valid_rows = len(batch.products)
    return batch


def ingest_json_payload(payload: object, filename: str, db: Session) -> UploadResponse:
    batch = parse_json_records(payload)
    return _finalize_ingestion(db, filename=filename, batch=batch)


def ingest_json_bytes(contents: bytes, filename: str, db: Session) -> UploadResponse:
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("JSON must be UTF-8 encoded") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    return ingest_json_payload(payload, filename, db)
