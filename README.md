# UniHack / ALETHEIA — Product Intelligence

**ALETHEIA** — The Truth Layer for Industrial Product Data.

CSV / JSON intake → agents → research → RAG → validation → HITL → delivery CSV.

```text
Intake → FastAPI → LangGraph agents → PostgreSQL + Qdrant → Review UI → Output CSV
```

## Deploy on Render

The repo includes a Blueprint at [`render.yaml`](render.yaml).

1. Push this repo to GitHub.
2. Open [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Select the repo → apply `render.yaml`.
4. When prompted, set API secrets:
   - `GROQ_API_KEY` (and optional `GROQ_API_KEY_BACKUP`)
   - optional `OPENROUTER_API_KEY` for Groq TPD failover
5. Wait for **aletheia-api**, **aletheia-web**, **aletheia-db**, and **aletheia-qdrant**.
6. Open the web service URL (e.g. `https://aletheia-web.onrender.com`).

Services created:

| Service | Role |
|---------|------|
| `aletheia-api` | FastAPI (Docker) |
| `aletheia-web` | Next.js UI |
| `aletheia-db` | PostgreSQL |
| `aletheia-qdrant` | Vector DB (private) |

If Qdrant private service is unavailable on your plan, create a [Qdrant Cloud](https://cloud.qdrant.io) cluster and set `QDRANT_URL` on `aletheia-api`.

If you rename `aletheia-api`, update `NEXT_PUBLIC_API_URL` on `aletheia-web` to match.

## Local run

### 1. PostgreSQL + Qdrant

A local Postgres is often already bound to `localhost:5432`, so the Docker database is published on **5433**.

```bash
docker compose up db qdrant -d
```

The API connects with:

```text
postgresql+psycopg2://unihack:unihack@127.0.0.1:5433/unihack
```

### 2. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

UI: http://localhost:3000

### 4. Or run API + Postgres together

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

## Tests

```bash
TESTING=1 GROQ_API_KEY="" PYTHONPATH=backend ./backend/venv/bin/pytest -q
```

## LLM keys

Add to `backend/.env` (never commit):

```text
GROQ_API_KEY=gsk-...
GROQ_API_KEY_BACKUP=
OPENROUTER_API_KEY=
LLM_MODEL=openai/gpt-oss-120b
```

## Sample input columns

```text
Mfg_Part_Num
Part_Desc
E1_Brand
Unilog_Brand
DIB_Brand
Part_Manuf
```

`index` is optional. Brand placeholders such as `-- Unbranded --` are stored as-is.
