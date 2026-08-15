# UniHack Product Intelligence — Phase 1

CSV upload → validate → Product objects → PostgreSQL → Product API.

This phase does **not** include agents, RAG, entity resolution, or a dashboard.

```text
CSV → FastAPI → Pandas → Pydantic → Product → SQLAlchemy → PostgreSQL → Product API
```

## Project layout

```text
backend/app/     FastAPI app, schemas, ingestion services, SQLAlchemy models
data/input/       Sample upload CSVs
tests/            Phase 1 ingestion tests
docker-compose.yml
```

## Sample input columns

The provided dataset uses these headers:

```text
Mfg_Part_Num
Part_Desc
E1_Brand
Unilog_Brand
DIB_Brand
Part_Manuf
```

`index` is optional. If it is absent, `source_index` is assigned from the 1-based row number.

Brand placeholders such as `-- Unbranded --` are stored as-is. Phase 1 preserves source truth; later phases resolve a canonical brand.

## Run locally

### 1. PostgreSQL

A local Postgres is often already bound to `localhost:5432`, so the Docker database is published on **5433**.

```bash
docker compose up db -d
```

The API connects with:

```text
postgresql+psycopg2://unihack:unihack@127.0.0.1:5433/unihack
```

Run this from the repo root. If you are already in `backend/`, use `docker compose up db -d` from the parent directory.

### 2. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### 3. Or run API + Postgres together

```bash
docker compose up --build
```

## Try the pipeline

```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@data/input/Unihack_Sample_Dataset_Input.csv"
```

```bash
curl http://localhost:8000/products/1
```

`POST /upload` returns job statistics:

```json
{
  "status": "success",
  "job_id": "...",
  "total_rows": 1000,
  "valid_rows": 1000,
  "invalid_rows": 0,
  "missing_mpn": 0,
  "missing_description": 0,
  "duplicate_mpns": 1,
  "missing_manufacturer": 0,
  "missing_brand": 554
}
```

Invalid rows are reported and skipped. Duplicate MPNs are stored and marked `DUPLICATE_CANDIDATE` — they are not merged.

## Tests

```bash
cd backend
source venv/bin/activate
cd ..
pip install -r backend/requirements.txt
pytest
```

Coverage:

1. Valid CSV → products stored
2. Missing column → error
3. Missing MPN → `INVALID` (not stored)
4. Duplicate MPN → `DUPLICATE_CANDIDATE`
5. Empty / placeholder brands survive
6. Special characters (`"`, `-`, `/`, `&`, `®`, `™`) survive

## Phase 2 — Product Understanding

Interpret an ingested product into **candidates**, without overwriting source rows.

```text
PostgreSQL product
        ↓
LangGraph: load → understand → save
        ↓
product_understanding table
```

Add your Groq key to `backend/.env`:

```text
GROQ_API_KEY=gsk-...
LLM_MODEL=openai/gpt-oss-120b
```

Single product:

```bash
curl -X POST http://127.0.0.1:8000/products/1/understand
curl http://127.0.0.1:8000/products/1/understanding
```

Start with a small batch before all 1,000:

```bash
curl -X POST "http://127.0.0.1:8000/products/understand?limit=20"
```

Source fields (`Mfg_Part_Num`, `Part_Desc`, brand columns, `Part_Manuf`) stay untouched. Brand placeholders such as `-- Unbranded --` can sit beside a `brand_candidate` like `Diablo` with `brand_conflict: true` for Phase 3.

## Phase 3A — Entity Resolution

Map brand and manufacturer **candidates** to canonical master entities.

```text
Candidate → Exact → Normalized → RapidFuzz → Canonical (only if in master data)
```

Embeddings and LLM verification are not in this layer.

```bash
curl -X POST http://127.0.0.1:8000/products/1/resolve
curl http://127.0.0.1:8000/products/1/entities
```

If a name is not in `data/reference/brands.json` or `manufacturers.json`, `canonical` stays `null` and status is `REVIEW_REQUIRED`. Source product fields are never overwritten.

Resolve responses keep source-vs-description conflict even after a successful match:

```json
{
  "brand_conflict": true,
  "conflict_resolved": true
}
```

## Phase 4 — Classification

Assign `Dept / Class / Fine / Classpath` from the allowed taxonomy in `data/reference/taxonomy.json`. The classifier does not invent paths.

```bash
curl -X POST http://127.0.0.1:8000/products/1/classify
curl http://127.0.0.1:8000/products/1/classification
```



