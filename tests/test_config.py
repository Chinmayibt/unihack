from app.core.config import normalize_database_url


def test_normalize_database_url_accepts_render_postgres_scheme():
    assert (
        normalize_database_url("postgres://u:p@host:5432/db?sslmode=require")
        == "postgresql+psycopg2://u:p@host:5432/db?sslmode=require"
    )
    assert (
        normalize_database_url("postgresql://u:p@host/db")
        == "postgresql+psycopg2://u:p@host/db"
    )
    assert (
        normalize_database_url("postgresql+psycopg2://u:p@host/db")
        == "postgresql+psycopg2://u:p@host/db"
    )
