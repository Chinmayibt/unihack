# UniHack / ALETHEIA — Product Intelligence

**ALETHEIA** — The Truth Layer for Industrial Product Data.

CSV / JSON intake → agents → research → RAG → validation → HITL → delivery CSV.

```text
Intake → FastAPI → LangGraph agents → PostgreSQL + Qdrant → Review UI → Output CSV
```

## Deploy on Render (free)

The repo includes a free-tier Blueprint at [`render.yaml`](render.yaml).

1. Push this repo to GitHub.
2. Open [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Select the repo → apply `render.yaml`.
4. When prompted, set API secrets:
   - `GROQ_API_KEY` and/or `OPENROUTER_API_KEY`
5. Wait for **aletheia-api**, **aletheia-web**, and **aletheia-db**.
6. Open the web URL (e.g. `https://aletheia-web.onrender.com`).

| Service | Plan | Role |
|---------|------|------|
| `aletheia-api` | free | FastAPI (Docker) |
| `aletheia-web` | free | Next.js UI |
| `aletheia-db` | free | PostgreSQL |

**Free-tier tradeoffs**
- Services sleep after idle (~15 min); first request is slow.
- Free Postgres on Render is time-limited — check Render’s current free DB policy.
- No separate Qdrant server: the API uses in-memory Qdrant (`QDRANT_URL=:memory:`). RAG vectors are lost when the API restarts or sleeps. Good enough for demos; for persistence later, point `QDRANT_URL` at [Qdrant Cloud](https://cloud.qdrant.io) free cluster.
- Keep jobs small on free (1 worker). Don’t expect a full 998-row overnight run on a sleeping free instance.

If you rename `aletheia-api`, update `NEXT_PUBLIC_API_URL` on `aletheia-web`.


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
