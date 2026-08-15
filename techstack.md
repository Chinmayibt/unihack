For this project, I recommend keeping the tech stack **practical and hackathon-friendly** rather than using too many technologies.

# Recommended Tech Stack

```text
┌─────────────────────────────────────────────────────────────┐
│                         FRONTEND                            │
│                  Next.js + React + Tailwind                │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST / WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                         BACKEND                             │
│                    Python + FastAPI                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     AI ORCHESTRATION                        │
│                       LangGraph                             │
│                  LangChain + Pydantic                       │
└───────────────────────────┬─────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
     LLM Agents          RAG Agent       Validation
          │                 │                 │
          ▼                 ▼                 ▼
       GPT-5.6          Qdrant /          Python
       / Gemini         pgvector          Rules
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                         DATA LAYER                          │
│              PostgreSQL + Qdrant + Redis                    │
└─────────────────────────────────────────────────────────────┘
```

## 1. Backend — Python + FastAPI

**Python** should be the main backend language.

Why:

* Excellent AI/ML ecosystem
* Pandas/Polars for CSV/Excel
* LangGraph
* LangChain
* PyMuPDF
* RapidFuzz
* Pydantic
* Easy integration with LLM APIs

**FastAPI** exposes APIs such as:

```text
POST /upload
POST /products/enrich
GET  /products/{id}
GET  /products/{id}/evidence
POST /products/{id}/review
GET  /evaluation
GET  /export
```

---

# 2. Agent Orchestration — LangGraph ⭐

This is the **core of the AI architecture**.

Use:

**LangGraph + LangChain**

LangGraph manages the workflow:

```text
Input
 ↓
Understanding Agent
 ↓
Entity Resolution
 ↓
Classification
 ↓
Research
 ↓
RAG
 ↓
Attribute Extraction
 ↓
Normalization
 ↓
Validation
 ↓
 ┌───────────────┐
 │               │
PASS           FAIL
 │               │
 ↓               ↓
Generate       Research /
Content        Human Review
 ↓
Output
```

### Why LangGraph?

Because your agents need:

* State
* Conditional routing
* Retry
* Loops
* Human approval
* Validation checkpoints

This is much better suited than simply creating several independent chatbot agents.

---

# 3. LLM — GPT / Gemini / Claude

You need an LLM for:

### Product understanding

```text
"3/8 CPLG BRS 150#"
       ↓
3/8 in Brass Coupling, 150 PSI
```

### Classification

Determine the product category.

### Attribute extraction

Extract technical information from documents.

### Semantic matching

Resolve ambiguous terminology.

### Description generation

Generate:

* Product title
* Short description
* Long description
* Mobile description
* Invoice description

---

# 4. Structured Output — Pydantic ⭐

Use **Pydantic** heavily.

Instead of allowing an agent to return:

```text
The product seems to be a brass coupling...
```

force it to return:

```json
{
  "product_type": "Coupling",
  "material": "Brass",
  "size": "3/8",
  "confidence": 0.96
}
```

Pydantic then validates the structure.

This makes your agent pipeline much more reliable.

---

# 5. RAG — Qdrant / pgvector

You have a large amount of reference material:

* Manufacturer documents
* PDFs
* Catalogs
* LOV
* Guidelines
* Product documentation

Put searchable content into a vector database.

### My recommendation

For the hackathon:

**Qdrant**

because it is simple and purpose-built for vector search.

Alternative:

**PostgreSQL + pgvector**

if you want fewer infrastructure components.

---

# 6. PostgreSQL

Use PostgreSQL for your structured data.

Store:

```text
Products
Manufacturers
Brands
Categories
Attributes
Sources
Evidence
Validation Results
Human Reviews
Processing Jobs
```

Example:

```text
products
    │
    ├── product_attributes
    │
    ├── sources
    │
    ├── evidence
    │
    └── validation_results
```

---

# 7. Entity Resolution — RapidFuzz + Embeddings

For manufacturer and brand matching:

### Layer 1

Exact match.

### Layer 2

Normalized string match.

### Layer 3

**RapidFuzz**

### Layer 4

Embedding similarity.

### Layer 5

LLM verification for ambiguous cases.

Example:

```text
"Frigidaire Inc."
       ↓
RapidFuzz
       ↓
Top candidates
       ↓
Embedding similarity
       ↓
LLM verification
       ↓
FRIGIDAIRE®
```

Don't use an LLM alone for this.

---

# 8. Data Processing — Pandas / Polars

For:

* CSV
* Excel
* Batch processing
* Column mapping
* Cleaning
* Output generation

Use:

**Pandas**

for simplicity.

If processing becomes large:

**Polars**

can improve performance.

---

# 9. Document Processing

For PDFs:

**PyMuPDF**

Pipeline:

```text
PDF
 ↓
PyMuPDF
 ↓
Text + page number
 ↓
Chunking
 ↓
Embedding
 ↓
Qdrant
```

For scanned documents:

```text
PDF
 ↓
OCR
 ↓
Text
 ↓
RAG
```

You can add OCR only when necessary.

---

# 10. UOM + LOV — Python Rules ⭐

Do **not** make an LLM responsible for this.

Use Python.

### UOM

```text
inches
IN
IN.
inch
"
 ↓
in
```

### Fraction

```text
24.25 in
 ↓
24-1/4 in
```

### LOV

```text
BRS
Brass Construction
Brass
 ↓
Brass
```

Load the provided Excel files into lookup tables.

---

# 11. Validation — Pydantic + Python

Validation should happen after the AI generates attributes.

Check:

```text
✓ Correct schema
✓ Correct data type
✓ LOV value
✓ UOM
✓ Character length
✓ Required field
✓ Source evidence
✓ Contradictions
✓ Confidence
```

Example:

```text
Voltage = 120 V

✓ Source found
✓ Manufacturer source
✓ UOM valid
✓ Format valid
✓ No conflict

→ APPROVED
```

---

# 12. Redis — Optional but useful

For bulk processing:

```text
1,000 products
     ↓
Job Queue
     ↓
Redis
     ↓
Workers
     ↓
LangGraph
```

This prevents the API from blocking while processing thousands of products.

For a small MVP, you can skip Redis initially.

---

# 13. Celery — Optional

If you use Redis:

**Celery + Redis**

can handle:

* Background jobs
* Batch processing
* Retries
* Parallel processing

Example:

```text
Upload 1,000 products
        ↓
Create job
        ↓
Celery
 ├── Product 1
 ├── Product 2
 ├── Product 3
 ├── ...
 └── Product 1000
```

---

# 14. Frontend — Next.js + React

The UI should have three main screens.

### 1. Upload

```text
┌─────────────────────────────┐
│ Upload Product Dataset      │
│                             │
│       Drop CSV / Excel      │
│                             │
│          [Process]          │
└─────────────────────────────┘
```

### 2. Processing Dashboard

```text
Products             1,000
Processed              824
Approved               761
Needs Review            63
Failed                   0

LOV Compliance        97.8%
UOM Compliance         99.1%
Evidence Coverage      94.3%
```

### 3. Product Review

```text
FRIGIDAIRE® PDSH4816AF

Voltage       120 V      98% ✓
Amperage       15 A      97% ✓
Material      Stainless  96% ✓
Color              ?     54% ⚠

Evidence:
Manufacturer Specification Sheet
Page 4

[Approve] [Edit] [Reject]
```

---

# 15. Styling — Tailwind CSS

Use:

**Tailwind CSS**

Keep the UI clean and enterprise-looking.

You don't need a complicated design system for the hackathon.

---

# 16. Deployment

For the hackathon:

### Backend

Docker + FastAPI

### Frontend

Next.js

### Database

PostgreSQL

### Vector DB

Qdrant

### Cache/Queue

Redis

### Cloud

AWS / Azure / GCP

You can also run most of it locally during development.

---

# 17. Complete Stack

| Layer               | Technology                 | Purpose                       |
| ------------------- | -------------------------- | ----------------------------- |
| Frontend            | **Next.js + React**        | Dashboard                     |
| UI                  | **Tailwind CSS**           | Styling                       |
| Backend             | **Python + FastAPI**       | APIs                          |
| Agent orchestration | **LangGraph** ⭐            | Agent workflow                |
| Agent/LLM utilities | **LangChain**              | Tools/RAG/LLM integration     |
| LLM                 | **GPT / Gemini / Claude**  | Reasoning                     |
| Structured output   | **Pydantic**               | JSON/schema validation        |
| Vector DB           | **Qdrant**                 | RAG                           |
| SQL DB              | **PostgreSQL**             | Product/evidence data         |
| Embeddings          | LLM embedding model        | Semantic search               |
| Entity matching     | **RapidFuzz + embeddings** | Brand/manufacturer resolution |
| PDF                 | **PyMuPDF**                | Document extraction           |
| OCR                 | **Tesseract / cloud OCR**  | Scanned documents             |
| Data                | **Pandas**                 | CSV/Excel processing          |
| Rules               | **Python**                 | UOM/LOV/fractions             |
| Queue               | **Redis**                  | Job queue/cache               |
| Workers             | **Celery**                 | Batch processing              |
| Deployment          | **Docker**                 | Containerization              |
| Evaluation          | **Python/Pandas**          | Ground-truth comparison       |

---

# The stack I would actually use for the hackathon

Don't implement every optional technology on day 1.

Start with:

```text
Python
   +
FastAPI
   +
LangGraph
   +
LangChain
   +
LLM
   +
Pydantic
   +
Pandas
   +
RapidFuzz
   +
Qdrant
   +
PostgreSQL
   +
PyMuPDF
   +
Next.js
```

Then add:

```text
Redis + Celery
```

only when you need bulk/parallel processing.

### Final architecture

**Next.js → FastAPI → LangGraph → Specialized Agents → Qdrant/PostgreSQL → Validation → Human Review → Output CSV**

That's the stack I'd recommend because it is **technically strong enough for the judges but still realistic to build during a hackathon.**
