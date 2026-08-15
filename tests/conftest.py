import os

os.environ["TESTING"] = "1"
os.environ["GROQ_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.connection import Base, get_db
from app.main import app
from app.services.cache_store import clear_runtime_caches
from app.services.qdrant_store import reset_qdrant_client
from app.services.standards import lov_alias_rows, lov_table, taxonomy_rows


@pytest.fixture()
def client():
    reset_qdrant_client()
    clear_runtime_caches()
    lov_table.cache_clear()
    lov_alias_rows.cache_clear()
    taxonomy_rows.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
