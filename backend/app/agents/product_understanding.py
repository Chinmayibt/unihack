from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from app.core.config import settings
from app.schemas.understanding import LLMProductUnderstanding
from app.services.cache_store import get_cached_understanding, put_cached_understanding
from app.services.llm_retry import call_with_rate_limit_retry

SYSTEM_PROMPT = """You are a Product Understanding Agent for an industrial
product data enrichment system.

Your job is to interpret raw product information and extract
structured product understanding.

You must:

1. Identify the likely product type.
2. Identify possible brand names appearing in the description.
3. Extract meaningful product terminology.
4. Extract candidate attributes explicitly present in the input.
5. Identify possible category candidates.
6. Assign a confidence score.

Rules:

- Do not invent technical specifications.
- Do not search the internet.
- Do not assume information that is not present.
- Do not normalize values unless explicitly obvious (for example 1/2" → 1/2 in).
- Preserve ambiguity.
- Treat brand/manufacturer values as candidates.
- Do not overwrite source data.
- Return structured output only.
- If a brand field is a placeholder such as "-- Unbranded --", that is source data,
  not a brand name. A brand mentioned in the description is a brand_candidate only.
- Never copy or alter the MPN except as an extracted term if it appears in the description.
"""

USER_TEMPLATE = """Raw product input (source of truth — do not overwrite):

MPN: {mpn}
Description: {description}
E1_Brand: {e1_brand}
Unilog_Brand: {unilog_brand}
DIB_Brand: {dib_brand}
Manufacturer: {manufacturer}

Extract structured understanding from this input only.
If a value is not explicitly present, leave it null or omit it from attributes.
"""


class MissingLLMConfigError(RuntimeError):
    pass


def invoke_understanding_llm(raw_product: dict) -> LLMProductUnderstanding:
    cached = get_cached_understanding(raw_product)
    if cached is not None:
        return LLMProductUnderstanding.model_validate(cached)
    if not settings.GROQ_API_KEY:
        raise MissingLLMConfigError(
            "GROQ_API_KEY is not configured. Add it to backend/.env"
        )

    llm = ChatGroq(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.GROQ_API_KEY,
    )
    structured = llm.with_structured_output(LLMProductUnderstanding)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", USER_TEMPLATE),
        ]
    )
    chain = prompt | structured
    result = call_with_rate_limit_retry(
        lambda: chain.invoke(
            {
                "mpn": raw_product.get("mpn") or "",
                "description": raw_product.get("description") or "",
                "e1_brand": raw_product.get("e1_brand") or "",
                "unilog_brand": raw_product.get("unilog_brand") or "",
                "dib_brand": raw_product.get("dib_brand") or "",
                "manufacturer": raw_product.get("manufacturer") or "",
            }
        )
    )
    if isinstance(result, LLMProductUnderstanding):
        put_cached_understanding(raw_product, result.model_dump())
        return result
    parsed = LLMProductUnderstanding.model_validate(result)
    put_cached_understanding(raw_product, parsed.model_dump())
    return parsed
