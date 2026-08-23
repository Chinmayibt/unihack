import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.api.routes import (
    attributes,
    classification,
    entities,
    jobs,
    output,
    products,
    rag,
    research,
    review,
    understanding,
    upload,
    validation,
)
from app.core.config import settings
from app.database.connection import Base, SessionLocal, engine
from app.database import models  # noqa: F401  — register ORM mappings
from app.database.schema import ensure_schema
from app.services.master_data import seed_master_data


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.TESTING:
        last_error: Exception | None = None
        for attempt in range(1, 16):
            try:
                Base.metadata.create_all(bind=engine)
                ensure_schema()
                db = SessionLocal()
                try:
                    seed_master_data(db)
                    db.commit()
                finally:
                    db.close()
                last_error = None
                break
            except OperationalError as exc:
                last_error = exc
                time.sleep(1)
        if last_error is not None:
            raise last_error
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Phase 1–12 product intelligence: ingestion through batch orchestration.",
    lifespan=lifespan,
)


@app.middleware("http")
async def strip_backend_prefix(request: Request, call_next):
    prefix = "/api/backend"

    if request.scope["path"].startswith(prefix):
        request.scope["path"] = request.scope["path"][len(prefix):] or "/"
        request.scope["raw_path"] = request.scope["path"].encode()

    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(understanding.router)
app.include_router(entities.router)
app.include_router(classification.router)
app.include_router(research.router)
app.include_router(rag.router)
app.include_router(attributes.router)
app.include_router(validation.router)
app.include_router(review.router)
app.include_router(output.router)
app.include_router(products.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
