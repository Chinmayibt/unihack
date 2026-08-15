# Product Requirements Document (PRD)

## 1. Product Overview

### Product Name

**AI-Powered Product Intelligence Engine**

### Product Vision

Build an AI-powered product enrichment platform that transforms incomplete, inconsistent, and unstructured industrial product information into **accurate, standardized, validated, traceable, and commerce-ready product records**.

The system will combine:

* Multi-agent AI
* RAG
* Manufacturer-source retrieval
* Entity resolution
* Product classification
* Attribute extraction
* Controlled vocabularies
* UOM normalization
* Deterministic validation
* Confidence scoring
* Human-in-the-loop review
* Automated content generation

### Core Value Proposition

> **Don't ask AI to invent product data. Make AI find, normalize, validate, and prove product data.**

---

# 2. Problem Statement

Industrial manufacturers and distributors maintain product information across:

* Websites
* Product catalogs
* Technical PDFs
* Specification sheets
* Installation manuals
* Digital assets
* Internal databases

Raw product data is often:

* Incomplete
* Abbreviated
* Inconsistent
* Duplicated
* Poorly categorized
* Missing attributes
* Inconsistent in units
* Inconsistent in manufacturer/brand names

For example:

**Input:**

`PDSH4816AF Dishwasher SS - Display Only`

The information is insufficient for direct e-commerce usage.

The platform should transform it into a structured product record containing:

* Manufacturer
* Brand
* MPN
* Product category
* Product attributes
* Dimensions
* UOM
* Technical specifications
* Product title
* Short description
* Long description
* Marketing content
* Digital assets
* Source evidence
* Confidence
* Validation status

---

# 3. Goals

## Primary Goals

### G1 — Product Data Enrichment

Convert limited product information into rich structured product intelligence.

### G2 — Accuracy

Ensure generated attributes are supported by authoritative evidence.

### G3 — Standardization

Normalize:

* Manufacturer names
* Brand names
* Attribute values
* Units of measure
* Fractions
* Product terminology
* Descriptions

### G4 — Explainability

For important generated fields, provide:

* Source
* Evidence
* Confidence
* Validation status

### G5 — Scalability

Process hundreds or thousands of products efficiently.

### G6 — Human Oversight

Automatically identify uncertain or conflicting records and route them to human reviewers.

### G7 — Commerce Readiness

Generate output conforming exactly to the provided delivery schema and content guidelines.

---

# 4. Non-Goals

The initial version will NOT attempt to:

* Perfectly populate every possible field for every product category.
* Generate unsupported product information.
* Use arbitrary marketplace websites as authoritative sources.
* Replace human review for ambiguous or conflicting products.
* Build a generic conversational chatbot.
* Rely entirely on an LLM for deterministic formatting and validation.

The MVP will prioritize **depth and accuracy over breadth**.

---

# 5. Target Users

## Primary User — Product Data Specialist

Needs to:

* Enrich product records
* Correct product attributes
* Validate AI-generated information
* Review uncertain records
* Export commerce-ready data

## Secondary User — Catalog Manager

Needs to:

* Monitor catalog quality
* Track enrichment progress
* Identify missing data
* Review validation metrics

## Technical User — Data/AI Engineer

Needs to:

* Configure pipelines
* Monitor agent performance
* Manage LOVs
* Manage manufacturer sources
* Evaluate model accuracy

---

# 6. Key Use Cases

## UC1 — Enrich Product

User uploads a raw product CSV.

System:

1. Reads product row.
2. Identifies MPN and product type.
3. Resolves manufacturer and brand.
4. Classifies product.
5. Searches manufacturer sources.
6. Retrieves relevant documents.
7. Extracts attributes.
8. Normalizes values.
9. Validates results.
10. Generates descriptions.
11. Produces final output.

---

## UC2 — Validate Existing Product Data

Given an already populated product record, the system should:

* Check LOV compliance
* Check UOM compliance
* Check character limits
* Check source evidence
* Detect conflicting values
* Identify unsupported claims

---

## UC3 — Human Review

When confidence is low or sources conflict:

```text
AI → Review Queue → Human Decision → Approved Record
```

---

## UC4 — Bulk Enrichment

User uploads:

```text
1,000 products
```

System processes them asynchronously and provides:

* Processing status
* Success count
* Review count
* Error count
* Validation metrics
* Final downloadable dataset

---

# 7. Product Workflow

```text
Raw Product
     ↓
Input Analysis
     ↓
Entity Resolution
     ↓
Classification
     ↓
Source Discovery
     ↓
Manufacturer RAG
     ↓
Attribute Extraction
     ↓
LOV/UOM Normalization
     ↓
Validation
     ↓
Confidence Scoring
     ↓
 ┌───────────────┐
 │               │
High Confidence  Low Confidence
 │               │
 ↓               ↓
Auto Approve   Human Review
 │               │
 └───────┬───────┘
         ↓
Content Generation
         ↓
Final Schema Validation
         ↓
Export
```

---

# 8. System Architecture

## High-Level Architecture

```text
                         FRONTEND
                            │
                            ▼
                         FastAPI
                            │
                            ▼
                     LANGGRAPH
                   ORCHESTRATOR
                            │
        ┌───────────────────┼────────────────────┐
        │                   │                    │
        ▼                   ▼                    ▼
  Understanding      Entity Resolution     Classification
      Agent                Agent                Agent
        │                   │                    │
        └───────────────────┼────────────────────┘
                            ▼
                      Research Agent
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
          Manufacturer Web        Documents/PDF
                 │                     │
                 └──────────┬──────────┘
                            ▼
                         RAG Layer
                            │
                            ▼
                    Attribute Agent
                            │
                            ▼
                  Normalization Engine
                            │
                            ▼
                     Validation Agent
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
             Auto Approval       Human Review
                  │                   │
                  └─────────┬─────────┘
                            ▼
                     Content Agent
                            │
                            ▼
                    Output Generator
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
             CSV/Excel             Dashboard
```

---

# 9. Agent Architecture

## 9.1 Product Understanding Agent

### Responsibility

Interpret raw product information.

### Input

* MPN
* Part description
* Existing brand
* Existing manufacturer
* SKU
* Category hints

### Output

Structured product understanding.

Example:

```json
{
  "mpn": "PDSH4816AF",
  "product_type": "Dishwasher",
  "possible_material": "Stainless Steel",
  "category_candidates": [
    "Built-In Dishwasher"
  ]
}
```

---

# 10. Entity Resolution Agent

### Responsibility

Resolve manufacturer and brand names against approved master data.

### Data Source

`UniCat_Manufacturer_and_Brand_List.xlsx`

### Processing

```text
Exact Match
    ↓
Normalized Match
    ↓
Fuzzy Match
    ↓
Embedding Similarity
    ↓
LLM Verification
    ↓
Canonical Entity
```

### Output

```json
{
  "manufacturer": "Rheem Manufacturing",
  "brand": "FRIGIDAIRE®",
  "confidence": 0.98
}
```

---

# 11. Classification Agent

### Responsibility

Determine:

* Department
* Class
* Fine
* Classpath
* Product type

### Constraints

Classification must be consistent with available taxonomy and LOV data.

### Output

```json
{
  "department": "Appliances & Consumer Electronics",
  "class": "Kitchen Appliances",
  "fine": "Built-In Dishwashers",
  "confidence": 0.96
}
```

---

# 12. Research Agent

### Responsibility

Find authoritative product information.

### Source Priority

1. Manufacturer product page
2. Manufacturer technical documentation
3. Manufacturer specification PDF
4. Manufacturer installation manual
5. Manufacturer catalog
6. Other permitted authoritative sources

### Source Restrictions

Marketplace/distributor sources should not be treated as authoritative when manufacturer sources are available.

### Output

```json
{
  "source": "manufacturer",
  "url": "...",
  "document": "PDSH4816AF_spec.pdf",
  "relevance": 0.97
}
```

---

# 13. RAG System

## Purpose

Retrieve evidence from manufacturer documentation.

### Pipeline

```text
Document
 ↓
Parse
 ↓
Chunk
 ↓
Embed
 ↓
Vector Database
 ↓
Semantic Retrieval
 ↓
Relevant Evidence
 ↓
LLM
```

### Stored Metadata

Each chunk should contain:

* Product
* Manufacturer
* MPN
* Document name
* Page
* URL
* Document type
* Timestamp

---

# 14. Attribute Extraction Agent

### Responsibility

Extract product attributes from retrieved evidence.

The agent should receive only the attributes applicable to the product's classpath.

Example:

```text
Product:
Built-In Dishwasher

Required Attributes:
- Series
- Mounting
- Wash Cycles
- Voltage
- Amperage
- Sound Level
- Material
- Width
- Depth
```

### Output

```json
{
  "voltage": {
    "value": "120",
    "uom": "V",
    "source": "spec.pdf",
    "page": 4,
    "confidence": 0.98
  }
}
```

---

# 15. Normalization Engine

Normalization should primarily use deterministic Python logic rather than LLM generation.

## UOM Normalization

```text
inch
inches
IN.
"
24in

        ↓

24 in
```

## Fraction Normalization

```text
24.25 in
     ↓
24-1/4 in
```

## Attribute Normalization

```text
BRS
Brass Construction
Brass Material

        ↓

Brass
```

### Data Sources

* `Unilog_Master_UOM_Standards_and_Abbreviations.xlsx`
* `Decimal_Fraction.xlsx`
* `Unicat_Lov_v1_0_Updated_With_Remarks.xlsx`

---

# 16. Validation Agent

The Validation Agent is a critical component.

Every generated field should be checked against:

### Source Validation

Does authoritative evidence support the value?

### LOV Validation

Is the value permitted?

### UOM Validation

Is the unit approved?

### Format Validation

Does the field follow the content guideline?

### Character Validation

Does the field stay within its limit?

### Consistency Validation

Does the value conflict with another attribute?

---

# 17. Confidence Engine

Each important field receives a confidence score.

Example:

```text
Manufacturer       99%
Brand              99%
Classification     96%
Voltage             98%
Material            96%
Sound Level         94%
Color               62%
```

### Routing Rules

```text
90–100% → Auto Approve

70–89% → Review Recommended

<70% → Human Review
```

The thresholds should be configurable.

---

# 18. Contradiction Detection

The system must detect conflicting evidence.

Example:

```text
Manufacturer PDF:
Voltage = 120 V

Manufacturer webpage:
Voltage = 240 V
```

System output:

```text
CONFLICT DETECTED

Attribute: Voltage

Source A: 120 V
Source B: 240 V

Status: HUMAN REVIEW REQUIRED
```

The system should never silently choose an arbitrary value.

---

# 19. Human-in-the-Loop Interface

The review interface should display:

### Product

`FRIGIDAIRE® PDSH4816AF`

### Attribute

`Voltage`

### AI Value

`120 V`

### Confidence

`98%`

### Evidence

`Manufacturer Specification Sheet — Page 4`

### Actions

* Approve
* Edit
* Reject
* Search Again

---

# 20. Content Generation Agent

The Content Agent operates only on validated structured data.

### Outputs

* Invoice Description
* Mobile Description
* Product Title
* Short Description
* Long Description
* Marketing Description
* Features
* Applications

### Principle

```text
Validated Data
      ↓
Content Templates + LLM
      ↓
Commerce Content
```

The content generator must not introduce attributes that are absent from validated data.

---

# 21. Output Generation

The final output must preserve the provided static headers.

### Critical Requirement

**Do not modify the expected output headers.**

The system maps its internal product intelligence object to the exact required schema.

```text
Internal Product Object
          ↓
Schema Mapper
          ↓
Expected Output Headers
          ↓
CSV
```

---

# 22. Technology Stack

## Backend

**Python + FastAPI**

## Agent Orchestration

**LangGraph**

## LLM/Agent Framework

**LangChain + LangGraph**

## Vector Database

**Qdrant or PostgreSQL + pgvector**

## Relational Database

**PostgreSQL**

## Data Processing

**Pandas / Polars**

## Validation

**Pydantic + Python rules**

## Entity Resolution

**RapidFuzz + embeddings + LLM verification**

## Document Processing

**PyMuPDF + OCR where necessary**

## Frontend

**React / Next.js**

## Background Processing

**Redis + Celery** or asynchronous workers

## Deployment

Docker-based deployment with cloud infrastructure.

---

# 23. Data Model

## Product

```text
product_id
sku
mpn
manufacturer
brand
department
class
fine
classpath
status
confidence
created_at
updated_at
```

## Attribute

```text
product_id
attribute_name
value
normalized_value
uom
source_id
evidence
confidence
validation_status
```

## Source

```text
source_id
url
manufacturer
document_name
document_type
page
retrieved_at
```

## Validation

```text
validation_id
product_id
field
rule
result
expected
actual
confidence
```

---

# 24. Functional Requirements

## FR1 — File Upload

System must support uploading the provided product datasets.

## FR2 — Product Parsing

System must correctly identify input columns and handle inconsistent spreadsheet structures.

## FR3 — Entity Resolution

System must normalize manufacturer and brand names against approved master data.

## FR4 — Classification

System must classify products into appropriate taxonomy/classpaths.

## FR5 — Source Discovery

System must identify relevant manufacturer sources.

## FR6 — Document Retrieval

System must retrieve and process relevant product documents.

## FR7 — Attribute Extraction

System must extract applicable attributes.

## FR8 — LOV Validation

System must validate attribute values against approved LOV values.

## FR9 — UOM Normalization

System must normalize all applicable units according to the UOM standard.

## FR10 — Fraction Conversion

System must convert supported decimal inch values into approved fractions.

## FR11 — Evidence Tracking

System must maintain evidence for generated values.

## FR12 — Confidence Scoring

System must assign confidence scores.

## FR13 — Human Review

System must route uncertain/conflicting records to review.

## FR14 — Content Generation

System must generate required commerce descriptions.

## FR15 — Output Validation

System must validate the final output against the expected schema.

## FR16 — Bulk Processing

System must support processing the 1,000-item dataset.

## FR17 — Export

System must export the final output without modifying required headers.

---

# 25. Non-Functional Requirements

## Accuracy

Target:

* > 90% attribute accuracy for MVP
* > 95% LOV compliance
* > 98% UOM compliance

Targets should be measured against the labelled 200-item dataset.

## Performance

The system should process products asynchronously and provide progress tracking.

## Scalability

Architecture should support scaling from:

```text
200 → 1,000 → 10,000+ products
```

## Reliability

Failed products should not stop the entire batch.

## Explainability

Important generated values must have source evidence whenever available.

## Security

Uploaded product files and manufacturer documents must be isolated and protected.

---

# 26. Evaluation Framework

The 200-item Input vs Delivery Format dataset is the primary evaluation dataset.

## Metrics

### Field-Level Accuracy

```text
Correct Fields / Total Evaluated Fields
```

### Manufacturer Accuracy

```text
Correct Manufacturer Matches / Total
```

### Brand Accuracy

```text
Correct Brand Matches / Total
```

### Classification Accuracy

```text
Correct Classifications / Total
```

### Attribute Accuracy

```text
Correct Attributes / Total
```

### LOV Compliance

```text
Valid LOV Values / Generated LOV Values
```

### UOM Compliance

```text
Valid UOM Values / Generated UOM Values
```

### Character Compliance

```text
Fields Within Limits / Total Fields
```

### Evidence Coverage

```text
Source-backed Fields / Generated Fields
```

### Human Review Rate

```text
Products Requiring Review / Total Products
```

---

# 27. MVP Scope

For the hackathon MVP, focus on **one category deeply**.

Recommended:

### Option 1 — Faucets

Use:

`FAUCETS_LOV.xlsx`

Pipeline:

```text
Input
 ↓
Classification
 ↓
Attribute Extraction
 ↓
LOV Mapping
 ↓
Source Retrieval
 ↓
Validation
 ↓
Description Generation
 ↓
Output
```

### Option 2 — Fittings

Use:

`Fittings_LOV.xlsx`

Focus on:

* Fitting Type
* Connection Type
* Material
* Canonical mapping

Fittings provides a particularly strong demonstration of entity resolution and normalization.

---

# 28. MVP Demo

The demo should show the following workflow.

### Step 1

Upload the sample dataset.

### Step 2

System displays:

```text
1,000 products detected
```

### Step 3

Processing dashboard:

```text
Processed:             720
Successfully enriched: 675
Needs review:           45
Failed:                  0
```

### Step 4

Select a product.

Show:

```text
RAW DATA
PDSH4816AF Dishwasher SS
```

Then:

```text
CLASSIFICATION
Built-In Dishwasher
```

Then:

```text
ATTRIBUTES
Voltage        120 V
Amperage       15 A
Material       Stainless Steel
Sound Level    47 dBA
Wash Cycles    5
```

Then:

```text
EVIDENCE
Manufacturer Specification Sheet
Page 4
```

Then:

```text
VALIDATION
✓ Source verified
✓ LOV compliant
✓ UOM compliant
✓ Character compliant
```

Finally:

```text
GENERATED CONTENT
Product Title
Short Description
Long Description
Invoice Description
```

---

# 29. Example End-to-End Product

### Input

```text
MPN:
PDSH4816AF

Description:
PDSH4816AF Dishwasher SS - Display Only
```

### AI Understanding

```text
Product Type:
Dishwasher

Material:
Stainless Steel
```

### Entity Resolution

```text
Brand:
FRIGIDAIRE®

Manufacturer:
Rheem Manufacturing
```

### Classification

```text
Appliances & Consumer Electronics
→ Kitchen Appliances
→ Built-In Dishwashers
```

### Retrieved Evidence

```text
Manufacturer Product Page
Manufacturer Specification Sheet
```

### Extracted Attributes

```text
Series = Professional Series
Mounting = Leg
Wash Cycles = 5
Voltage = 120 V
Amperage = 15 A
Sound Level = 47 dBA
Material = Stainless Steel
```

### Validation

```text
LOV = PASS
UOM = PASS
Source = PASS
Confidence = 96%
```

### Generated Output

Commerce-ready title and descriptions are generated from the validated attributes.

---

# 30. Success Criteria

The MVP is successful if it can:

1. Process the provided 200-item labelled dataset.
2. Produce the required output schema.
3. Demonstrate measurable field-level accuracy.
4. Normalize manufacturers and brands.
5. Normalize UOMs.
6. Map attributes to LOV values.
7. Retrieve manufacturer evidence.
8. Detect unsupported/conflicting information.
9. Provide confidence scores.
10. Route uncertain products to human review.
11. Generate commerce-ready descriptions.
12. Scale the same pipeline to the 1,000-item dataset.

---

# 31. Competitive Differentiator

The product should not be positioned as:

> **"An AI that generates product descriptions."**

It should be positioned as:

> **"An evidence-driven Product Intelligence Engine that transforms fragmented industrial product information into validated, standardized, explainable commerce data."**

The major differentiators are:

### 1. Evidence-first AI

Every important claim should have evidence.

### 2. Constrained generation

LLM outputs are constrained by:

* LOV
* UOM
* taxonomy
* content guidelines
* source evidence

### 3. Multi-agent architecture

Specialized agents perform specialized tasks.

### 4. Deterministic validation

Critical rules are handled by code rather than AI.

### 5. Confidence-aware automation

High-confidence records are automatically processed; uncertain records go to humans.

### 6. Measurable accuracy

The 200 labelled products provide objective evaluation.

---

# 32. Final Product Architecture

```text
                         ┌──────────────────────┐
                         │       USER UI        │
                         │ Upload / Review / KPI │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FASTAPI        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      LANGGRAPH       │
                         │    ORCHESTRATOR      │
                         └──────────┬───────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   Understanding             Entity Resolution          Classification
       Agent                      Agent                      Agent
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    ▼
                             Research Agent
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                  Manufacturer Web        Documents/PDFs
                         │                     │
                         └──────────┬──────────┘
                                    ▼
                               RAG Layer
                          Qdrant / pgvector
                                    │
                                    ▼
                            Attribute Agent
                                    │
                                    ▼
                          Normalization Layer
                      LOV + UOM + Fractions + Rules
                                    │
                                    ▼
                           Validation Agent
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                    AUTO APPROVE          HUMAN REVIEW
                         │                     │
                         └──────────┬──────────┘
                                    ▼
                             Content Agent
                                    │
                                    ▼
                         Schema Validation Layer
                                    │
                                    ▼
                          FINAL PRODUCT RECORD
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                       CSV/Excel            Analytics
```

# 33. One-Sentence Product Definition

**AI Product Intelligence Engine is a LangGraph-orchestrated multi-agent platform that uses manufacturer-grounded RAG, entity resolution, constrained attribute extraction, deterministic normalization, evidence-based validation, and human review to transform messy industrial product data into accurate, explainable, commerce-ready product records.**
