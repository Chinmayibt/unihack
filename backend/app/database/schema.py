from sqlalchemy import inspect, text

from app.database.connection import engine


def _add_column_if_missing(
    table: str, column: str, ddl: str, existing_tables: set[str]
) -> str | None:
    if table not in existing_tables:
        return None
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column in columns:
        return None
    return f"ALTER TABLE {table} ADD COLUMN {ddl}"


def ensure_schema() -> None:
    """Add columns that create_all will not alter on existing tables."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    bool_default = "FALSE" if dialect == "postgresql" else "0"

    statements = [
        _add_column_if_missing(
            "entity_resolution",
            "brand_conflict",
            f"brand_conflict BOOLEAN DEFAULT {bool_default}",
            tables,
        ),
        _add_column_if_missing(
            "entity_resolution",
            "conflict_resolved",
            f"conflict_resolved BOOLEAN DEFAULT {bool_default}",
            tables,
        ),
        _add_column_if_missing(
            "product_sources",
            "content_type",
            "content_type VARCHAR(64) DEFAULT 'OTHER'",
            tables,
        ),
        _add_column_if_missing(
            "product_attributes",
            "retrieval_score",
            "retrieval_score FLOAT DEFAULT 0",
            tables,
        ),
        _add_column_if_missing(
            "product_normalized_attributes",
            "ai_value",
            "ai_value VARCHAR(512)",
            tables,
        ),
        _add_column_if_missing(
            "product_normalized_attributes",
            "human_value",
            "human_value VARCHAR(512)",
            tables,
        ),
        _add_column_if_missing(
            "product_normalized_attributes",
            "review_decision",
            "review_decision VARCHAR(64)",
            tables,
        ),
        _add_column_if_missing(
            "product_normalized_attributes",
            "reviewed_by",
            "reviewed_by VARCHAR(255)",
            tables,
        ),
        _add_column_if_missing(
            "product_normalized_attributes",
            "review_reason",
            "review_reason TEXT",
            tables,
        ),
        _add_column_if_missing(
            "review_queue",
            "diagnostics",
            "diagnostics JSON DEFAULT '{}'",
            tables,
        ),
        _add_column_if_missing(
            "product_stage_runs",
            "metrics",
            "metrics JSON DEFAULT '{}'",
            tables,
        ),
    ]
    statements = [item for item in statements if item]
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
