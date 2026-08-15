from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import ProductRecord
from app.schemas.final_output import (
    EXPECTED_OUTPUT_COLUMNS,
    STATUS_COMPLETED,
    STATUS_OUTPUT_FAILED,
    OutputGenerateResponse,
)
from app.services.output_assemble import assemble_output
from app.services.output_validate import OutputContractError, validate_headers, validate_output_rows

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "output"


def default_output_path() -> Path:
    name = (
        "test_unihack_delivery_format.csv"
        if settings.TESTING
        else "unihack_delivery_format.csv"
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / name


def generate_output(db: Session, output_path: Path | None = None) -> OutputGenerateResponse:
    path = output_path or default_output_path()
    products = db.query(ProductRecord).order_by(ProductRecord.id).all()
    approved = 0
    partial = 0
    review_pending = 0
    skipped = 0
    rows: list[dict[str, str]] = []
    errors: list[str] = []

    for product in products:
        try:
            envelope = assemble_output(product.id, db)
        except Exception as exc:
            errors.append(f"Product {product.id}: {exc}")
            skipped += 1
            continue
        if envelope.eligibility_reason == "review_pending":
            review_pending += 1
            skipped += 1
            continue
        if not envelope.eligible_for_csv:
            skipped += 1
            continue
        if envelope.eligibility_reason == "approved":
            approved += 1
        elif envelope.eligibility_reason == "partial":
            partial += 1
        rows.append(envelope.output)

    if errors:
        return OutputGenerateResponse(
            status=STATUS_OUTPUT_FAILED,
            total_products=len(products),
            approved=approved,
            partial=partial,
            review_pending=review_pending,
            skipped=skipped,
            errors=errors,
        )

    try:
        validate_headers(list(EXPECTED_OUTPUT_COLUMNS))
        validate_output_rows(rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(EXPECTED_OUTPUT_COLUMNS),
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)
        written_headers = []
        with path.open(newline="", encoding="utf-8") as handle:
            written_headers = list(csv.reader(handle))[0] if path.stat().st_size else []
        validate_headers(written_headers)
    except (OutputContractError, ValueError, OSError) as exc:
        if path.exists():
            path.unlink()
        return OutputGenerateResponse(
            status=STATUS_OUTPUT_FAILED,
            total_products=len(products),
            approved=approved,
            partial=partial,
            review_pending=review_pending,
            skipped=skipped,
            errors=[str(exc)],
        )

    return OutputGenerateResponse(
        status=STATUS_COMPLETED,
        total_products=len(products),
        approved=approved,
        partial=partial,
        review_pending=review_pending,
        skipped=skipped,
        output_file=str(path),
    )
