from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.product_understanding import MissingLLMConfigError, invoke_understanding_llm
from app.agents.state import ProductState
from app.agents.understanding_logic import assemble_understanding
from app.database.models import (
    ProductAttributeRecord,
    ProductDocumentRecord,
    ProductNormalizedAttributeRecord,
    ProductRecord,
    ProductSourceRecord,
    ProductUnderstandingRecord,
    TaxonomyRecord,
)
from app.models.product import ProductStatus
from app.schemas.classification import ClassificationResult
from app.schemas.entity_resolution import EntityResolution
from app.schemas.source import ProductSource, ResearchMetrics
from app.services.attribute_extraction import extract_product_attributes
from app.services.attribute_normalization import normalize_product_attributes
from app.services.validation import validate_product
from app.services.classification import classify_against_taxonomy, persist_classification
from app.services.entity_resolution import (
    _understanding_dict,
    build_entity_resolution,
    get_entities,
    persist_entity_resolution,
)
from app.services.master_data import seed_master_data
from app.services.research import (
    build_research_input,
    cached_research_metrics,
    discover_sources,
    persist_sources,
    research_status_for,
)
from app.services.indexing import index_manufacturer_document
from app.services.text_display import preserve_display_text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def product_to_raw(product: ProductRecord) -> dict:
    return {
        "id": product.id,
        "mpn": product.mpn,
        "description": product.description,
        "e1_brand": product.e1_brand,
        "unilog_brand": product.unilog_brand,
        "dib_brand": product.dib_brand,
        "manufacturer": product.manufacturer,
        "status": product.status,
    }


def _save_understanding_record(db: Session, product: ProductRecord, payload: dict) -> None:
    record = (
        db.query(ProductUnderstandingRecord)
        .filter(ProductUnderstandingRecord.product_id == product.id)
        .one_or_none()
    )
    fields = {
        "product_type": preserve_display_text(payload.get("product_type")),
        "brand_candidate": payload.get("brand_candidate"),
        "manufacturer_candidate": payload.get("manufacturer_candidate"),
        "category_candidates": payload.get("category_candidates") or [],
        "extracted_terms": payload.get("extracted_terms") or [],
        "candidate_attributes": payload.get("candidate_attributes") or {},
        "confidence": payload.get("confidence") or 0.0,
        "reasoning_summary": payload.get("reasoning_summary"),
        "source_brand": payload.get("source_brand"),
        "source_manufacturer": payload.get("source_manufacturer"),
        "brand_conflict": bool(payload.get("brand_conflict")),
        "updated_at": _utcnow(),
    }
    if record is None:
        db.add(ProductUnderstandingRecord(product_id=product.id, **fields))
    else:
        for key, value in fields.items():
            setattr(record, key, value)
    if product.status in {
        ProductStatus.INGESTED.value,
        ProductStatus.DUPLICATE_CANDIDATE.value,
    }:
        product.status = ProductStatus.UNDERSTOOD.value
    product.updated_at = _utcnow()
    db.flush()


def build_graph_nodes(db: Session):
    def load_product(state: ProductState) -> dict:
        product = db.get(ProductRecord, state["product_id"])
        if product is None:
            return {"errors": [f"Product {state['product_id']} not found"]}
        return {"raw_product": product_to_raw(product), "errors": []}

    def understand_product(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        try:
            llm_result = invoke_understanding_llm(state["raw_product"])
        except MissingLLMConfigError:
            raise
        except Exception as exc:
            return {"errors": [f"Understanding agent failed: {exc}"]}
        understanding = assemble_understanding(state["raw_product"], llm_result)
        return {
            "understanding": understanding.model_dump(),
            "confidence": understanding.confidence,
        }

    def save_understanding(state: ProductState) -> dict:
        if state.get("errors") or not state.get("understanding"):
            return {}
        product = db.get(ProductRecord, state["product_id"])
        if product is None:
            return {"errors": [f"Product {state['product_id']} not found"]}
        _save_understanding_record(db, product, state["understanding"])
        return {}

    def load_understanding(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        if state.get("understanding"):
            return {}
        record = (
            db.query(ProductUnderstandingRecord)
            .filter(ProductUnderstandingRecord.product_id == state["product_id"])
            .one_or_none()
        )
        if record is None:
            return {"errors": ["Product has not been understood yet"]}
        return {"understanding": _understanding_dict(record)}

    def resolve_entities(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        product = db.get(ProductRecord, state["product_id"])
        if product is None:
            return {"errors": [f"Product {state['product_id']} not found"]}
        result = build_entity_resolution(
            product,
            state["raw_product"],
            state["understanding"],
            db,
        )
        return {"entity_resolution": result.model_dump()}

    def save_resolution(state: ProductState) -> dict:
        if state.get("errors") or not state.get("entity_resolution"):
            return {}
        result = EntityResolution.model_validate(state["entity_resolution"])
        persist_entity_resolution(db, result)
        return {}

    def classify_product_node(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        product = db.get(ProductRecord, state["product_id"])
        if product is None:
            return {"errors": [f"Product {state['product_id']} not found"]}
        seed_master_data(db)
        nodes = db.query(TaxonomyRecord).all()
        result = classify_against_taxonomy(
            state["raw_product"],
            state.get("understanding") or {},
            nodes,
        )
        result.product_id = product.id
        return {"classification": result.model_dump()}

    def save_classification(state: ProductState) -> dict:
        if state.get("errors") or not state.get("classification"):
            return {}
        result = ClassificationResult.model_validate(state["classification"])
        persist_classification(db, result)
        return {}

    def load_resolution(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        if state.get("entity_resolution"):
            return {}
        try:
            result = get_entities(state["product_id"], db)
        except Exception:
            return {"entity_resolution": {}}
        return {"entity_resolution": result.model_dump()}

    def load_classification(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        if state.get("classification"):
            return {}
        from app.database.models import ProductClassificationRecord

        record = (
            db.query(ProductClassificationRecord)
            .filter(ProductClassificationRecord.product_id == state["product_id"])
            .one_or_none()
        )
        if record is None:
            return {"classification": {}}
        return {
            "classification": {
                "department": record.department,
                "class_name": record.class_name,
                "fine": record.fine,
                "classpath": record.classpath,
                "method": record.method,
                "status": record.status,
            }
        }

    def research_sources(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        context = build_research_input(
            state.get("raw_product") or {},
            state.get("understanding") or {},
            state.get("entity_resolution") or {},
            state.get("classification") or {},
        )
        from app.services.cache_store import get_cached_sources, put_cached_sources

        already_researched = (
            db.query(ProductSourceRecord)
            .filter(ProductSourceRecord.product_id == state["product_id"])
            .first()
            is not None
        )
        cached = None if already_researched else get_cached_sources(db, context)
        metrics = {}
        if cached is not None:
            sources = cached
            metrics = cached_research_metrics(context, sources).model_dump()
        else:
            try:
                discovered = discover_sources(context, state["product_id"])
                sources = discovered.sources
                metrics = discovered.metrics.model_dump()
            except Exception:
                sources = []
                metrics = ResearchMetrics().model_dump()
            if sources:
                put_cached_sources(db, context, sources)
        _status, requires_review = research_status_for(sources)
        return {
            "sources": [source.model_dump() for source in sources],
            "requires_review": requires_review,
            "confidence": sources[0].relevance_score if sources else 0.0,
            "research_metrics": metrics,
        }

    def save_sources(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        sources = [
            ProductSource.model_validate(item) for item in (state.get("sources") or [])
        ]
        persist_sources(db, state["product_id"], sources)
        return {}

    def index_documents(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        result = index_manufacturer_document(state["product_id"], db)
        return {"index_result": result.model_dump()}

    def extract_attributes(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        try:
            result = extract_product_attributes(state["product_id"], db)
        except LookupError as exc:
            return {"errors": [str(exc)]}
        except MissingLLMConfigError:
            raise
        except Exception as exc:
            return {"errors": [f"Attribute extraction failed: {exc}"]}
        return {
            "attributes": [item.model_dump() for item in result.attributes],
            "extraction_metrics": result.metrics.model_dump(),
            "evidence": [
                {
                    "label": item.label,
                    "evidence_text": item.evidence_text,
                    "source_id": item.source_id,
                    "document_id": item.document_id,
                    "retrieval_score": item.retrieval_score,
                }
                for item in result.attributes
                if item.evidence_text
            ],
        }

    def normalize_attributes(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        try:
            result = normalize_product_attributes(state["product_id"], db)
        except LookupError as exc:
            return {"errors": [str(exc)]}
        except Exception as exc:
            return {"errors": [f"Attribute normalization failed: {exc}"]}
        return {
            "normalized_attributes": [item.model_dump() for item in result.attributes],
            "requires_review": result.requires_review,
        }

    def validate_attributes(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        try:
            result = validate_product(state["product_id"], db)
        except LookupError as exc:
            return {"errors": [str(exc)]}
        except Exception as exc:
            return {"errors": [f"Attribute validation failed: {exc}"]}
        return {
            "validation": result.model_dump(),
            "requires_review": result.requires_review,
        }

    def extract_if_needed(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        product_id = state["product_id"]
        has_attributes = (
            db.query(ProductAttributeRecord)
            .filter(ProductAttributeRecord.product_id == product_id)
            .first()
            is not None
        )
        if has_attributes:
            return {}
        has_document = (
            db.query(ProductDocumentRecord)
            .filter(ProductDocumentRecord.product_id == product_id)
            .first()
            is not None
        )
        if not has_document:
            return {"errors": [f"Product {product_id} has not been indexed yet"]}
        return extract_attributes(state)

    def normalize_if_needed(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        has_normalized = (
            db.query(ProductNormalizedAttributeRecord)
            .filter(ProductNormalizedAttributeRecord.product_id == state["product_id"])
            .first()
            is not None
        )
        if has_normalized:
            return {}
        return normalize_attributes(state)

    def quality_gate_node(state: ProductState) -> dict:
        if state.get("errors"):
            return {}
        from app.services.review import quality_gate

        return quality_gate(db, state["product_id"])

    return {
        "load_product": load_product,
        "understand_product": understand_product,
        "save_understanding": save_understanding,
        "load_understanding": load_understanding,
        "resolve_entities": resolve_entities,
        "save_resolution": save_resolution,
        "classify_product": classify_product_node,
        "save_classification": save_classification,
        "load_resolution": load_resolution,
        "load_classification": load_classification,
        "research_sources": research_sources,
        "save_sources": save_sources,
        "index_documents": index_documents,
        "extract_attributes": extract_attributes,
        "normalize_attributes": normalize_attributes,
        "validate_attributes": validate_attributes,
        "extract_if_needed": extract_if_needed,
        "normalize_if_needed": normalize_if_needed,
        "quality_gate": quality_gate_node,
    }


def build_understanding_graph(db: Session):
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("understand_product", nodes["understand_product"])
    graph.add_node("save_understanding", nodes["save_understanding"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "understand",
        {"end": END, "understand": "understand_product"},
    )
    graph.add_conditional_edges(
        "understand_product",
        lambda state: "end" if state.get("errors") else "save",
        {"end": END, "save": "save_understanding"},
    )
    graph.add_edge("save_understanding", END)
    return graph.compile()


def build_resolution_graph(db: Session):
    """Load product + understanding → entity resolution → save."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("load_understanding", nodes["load_understanding"])
    graph.add_node("resolve_entities", nodes["resolve_entities"])
    graph.add_node("save_resolution", nodes["save_resolution"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "understanding",
        {"end": END, "understanding": "load_understanding"},
    )
    graph.add_conditional_edges(
        "load_understanding",
        lambda state: "end" if state.get("errors") else "resolve",
        {"end": END, "resolve": "resolve_entities"},
    )
    graph.add_edge("resolve_entities", "save_resolution")
    graph.add_edge("save_resolution", END)
    return graph.compile()


def build_classification_graph(db: Session):
    """Load product + understanding → classify against allowed taxonomy → save."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("load_understanding", nodes["load_understanding"])
    graph.add_node("classify_product", nodes["classify_product"])
    graph.add_node("save_classification", nodes["save_classification"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "understanding",
        {"end": END, "understanding": "load_understanding"},
    )
    graph.add_conditional_edges(
        "load_understanding",
        lambda state: "end" if state.get("errors") else "classify",
        {"end": END, "classify": "classify_product"},
    )
    graph.add_edge("classify_product", "save_classification")
    graph.add_edge("save_classification", END)
    return graph.compile()


def build_research_graph(db: Session):
    """Load product context → discover ranked sources → save. Search misses are not errors."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("load_understanding", nodes["load_understanding"])
    graph.add_node("load_resolution", nodes["load_resolution"])
    graph.add_node("load_classification", nodes["load_classification"])
    graph.add_node("research_sources", nodes["research_sources"])
    graph.add_node("save_sources", nodes["save_sources"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "understanding",
        {"end": END, "understanding": "load_understanding"},
    )
    graph.add_conditional_edges(
        "load_understanding",
        lambda state: "end" if state.get("errors") else "resolution",
        {"end": END, "resolution": "load_resolution"},
    )
    graph.add_edge("load_resolution", "load_classification")
    graph.add_edge("load_classification", "research_sources")
    graph.add_edge("research_sources", "save_sources")
    graph.add_edge("save_sources", END)
    return graph.compile()


def build_index_graph(db: Session):
    """Load product → fetch top manufacturer source → chunk/embed → Qdrant."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("index_documents", nodes["index_documents"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "index",
        {"end": END, "index": "index_documents"},
    )
    graph.add_edge("index_documents", END)
    return graph.compile()


def build_extract_graph(db: Session):
    """Load product → classpath template → attribute RAG → extract → save."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("extract_attributes", nodes["extract_attributes"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "extract",
        {"end": END, "extract": "extract_attributes"},
    )
    graph.add_edge("extract_attributes", END)
    return graph.compile()


def build_normalize_graph(db: Session):
    """Load product → consolidate input+manufacturer evidence → Python normalize."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("normalize_attributes", nodes["normalize_attributes"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "normalize",
        {"end": END, "normalize": "normalize_attributes"},
    )
    graph.add_edge("normalize_attributes", END)
    return graph.compile()


def build_validate_graph(db: Session):
    """Load product → validate → quality gate. Does not wait for a human."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("validate_attributes", nodes["validate_attributes"])
    graph.add_node("quality_gate", nodes["quality_gate"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "validate",
        {"end": END, "validate": "validate_attributes"},
    )
    graph.add_edge("validate_attributes", "quality_gate")
    graph.add_edge("quality_gate", END)
    return graph.compile()


def build_process_graph(db: Session):
    """Extract if needed → normalize if needed → validate → quality gate → PAUSE or output."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("extract_if_needed", nodes["extract_if_needed"])
    graph.add_node("normalize_if_needed", nodes["normalize_if_needed"])
    graph.add_node("validate_attributes", nodes["validate_attributes"])
    graph.add_node("quality_gate", nodes["quality_gate"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "extract",
        {"end": END, "extract": "extract_if_needed"},
    )
    graph.add_conditional_edges(
        "extract_if_needed",
        lambda state: "end" if state.get("errors") else "normalize",
        {"end": END, "normalize": "normalize_if_needed"},
    )
    graph.add_conditional_edges(
        "normalize_if_needed",
        lambda state: "end" if state.get("errors") else "validate",
        {"end": END, "validate": "validate_attributes"},
    )
    graph.add_edge("validate_attributes", "quality_gate")
    graph.add_edge("quality_gate", END)
    return graph.compile()


def build_resume_graph(db: Session):
    """After a human decision: re-validate and either approve or keep paused."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("validate_attributes", nodes["validate_attributes"])
    graph.add_node("quality_gate", nodes["quality_gate"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "validate",
        {"end": END, "validate": "validate_attributes"},
    )
    graph.add_edge("validate_attributes", "quality_gate")
    graph.add_edge("quality_gate", END)
    return graph.compile()


def build_pipeline_graph(db: Session):
    """Full graph: load → understand → resolve → classify → research → save."""
    nodes = build_graph_nodes(db)
    graph = StateGraph(ProductState)
    graph.add_node("load_product", nodes["load_product"])
    graph.add_node("understand_product", nodes["understand_product"])
    graph.add_node("save_understanding", nodes["save_understanding"])
    graph.add_node("resolve_entities", nodes["resolve_entities"])
    graph.add_node("save_resolution", nodes["save_resolution"])
    graph.add_node("classify_product", nodes["classify_product"])
    graph.add_node("save_classification", nodes["save_classification"])
    graph.add_node("research_sources", nodes["research_sources"])
    graph.add_node("save_sources", nodes["save_sources"])
    graph.add_edge(START, "load_product")
    graph.add_conditional_edges(
        "load_product",
        lambda state: "end" if state.get("errors") else "understand",
        {"end": END, "understand": "understand_product"},
    )
    graph.add_conditional_edges(
        "understand_product",
        lambda state: "end" if state.get("errors") else "save_understanding",
        {"end": END, "save_understanding": "save_understanding"},
    )
    graph.add_edge("save_understanding", "resolve_entities")
    graph.add_edge("resolve_entities", "save_resolution")
    graph.add_edge("save_resolution", "classify_product")
    graph.add_edge("classify_product", "save_classification")
    graph.add_edge("save_classification", "research_sources")
    graph.add_edge("research_sources", "save_sources")
    graph.add_edge("save_sources", END)
    return graph.compile()
