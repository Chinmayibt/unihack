from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from app.agents.product_understanding import MissingLLMConfigError
from app.core.config import settings
from app.schemas.attribute import LLMAttributeExtraction
from app.services.llm_retry import call_with_rate_limit_retry

SYSTEM_PROMPT = """You are an Attribute Extraction Agent for industrial product data.

You receive:
- the product title/description and classification
- a list of allowed attribute labels for that classpath
- retrieved manufacturer evidence for each attribute

Rules:
1. Extract only attributes supported by the provided evidence or the product title.
2. Never invent missing values, even if they are common for the product type.
3. Preserve source meaning. Do not normalize UOM, fractions, or LOV values.
4. If evidence is insufficient, set supported=false and value=null.
5. evidence_text must be a short quote copied from the provided evidence or title.
6. Return structured output only.
7. Do not use outside knowledge.
8. Product Type is the product kind (for example Cut-Off Disc or Sanding Belt),
   not a specification code such as Type 1 or Type 27. If evidence only mentions
   a type code, use the product title/classification for Product Type.
"""

USER_TEMPLATE = """Product context:
{product_context}

Classification:
{classpath}

Allowed attributes and retrieved evidence:

{attribute_blocks}

Extract a slot for every allowed attribute label. Do not add extra labels.
"""


def invoke_attribute_llm(
    classpath: str,
    attribute_blocks: str,
    product_context: str = "",
) -> LLMAttributeExtraction:
    if not settings.GROQ_API_KEY:
        raise MissingLLMConfigError(
            "GROQ_API_KEY is not configured. Add it to backend/.env"
        )
    llm = ChatGroq(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.GROQ_API_KEY,
    )
    structured = llm.with_structured_output(LLMAttributeExtraction)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", USER_TEMPLATE),
        ]
    )
    result = call_with_rate_limit_retry(
        lambda: (prompt | structured).invoke(
            {
                "classpath": classpath or "unknown",
                "attribute_blocks": attribute_blocks,
                "product_context": product_context or "(none)",
            }
        )
    )
    if isinstance(result, LLMAttributeExtraction):
        return result
    return LLMAttributeExtraction.model_validate(result)
