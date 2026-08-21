import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH, override=os.getenv("TESTING") != "1")


def _env(name: str, default: str | None = None) -> str | None:
    load_dotenv(ENV_PATH, override=os.getenv("TESTING") != "1")
    value = os.getenv(name, default)
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    return cleaned or None


class Settings:
    APP_NAME: str = "UniHack Product Intelligence"
    APP_VERSION: str = "0.1.0"

    @property
    def DATABASE_URL(self) -> str:
        return _env(
            "DATABASE_URL",
            "postgresql+psycopg2://unihack:unihack@127.0.0.1:5433/unihack",
        ) or "postgresql+psycopg2://unihack:unihack@127.0.0.1:5433/unihack"

    @property
    def TESTING(self) -> bool:
        return _env("TESTING", "0") == "1"

    @property
    def GROQ_API_KEY(self) -> str | None:
        return _env("GROQ_API_KEY")

    @property
    def GROQ_API_KEY_BACKUP(self) -> str | None:
        return _env("GROQ_API_KEY_BACKUP")

    @property
    def GROQ_API_KEY_BACKUP_2(self) -> str | None:
        return _env("GROQ_API_KEY_BACKUP_2")

    @property
    def OPENROUTER_API_KEY(self) -> str | None:
        return _env("OPENROUTER_API_KEY")

    @property
    def OPENROUTER_BASE_URL(self) -> str:
        return (
            _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            or "https://openrouter.ai/api/v1"
        )

    @property
    def LLM_PROVIDER(self) -> str | None:
        """openrouter | groq. Empty = auto (OpenRouter if key set, else Groq)."""
        return _env("LLM_PROVIDER")

    @property
    def LLM_MODEL(self) -> str:
        return _env("LLM_MODEL", "openai/gpt-oss-120b") or "openai/gpt-oss-120b"

    @property
    def ENTITY_STRONG_MATCH(self) -> int:
        return int(_env("ENTITY_STRONG_MATCH", "92") or 92)

    @property
    def ENTITY_POSSIBLE_MATCH(self) -> int:
        return int(_env("ENTITY_POSSIBLE_MATCH", "80") or 80)

    @property
    def CLASSIFY_HIGH_CONFIDENCE(self) -> float:
        return float(_env("CLASSIFY_HIGH_CONFIDENCE", "0.90") or 0.90)

    @property
    def CLASSIFY_REVIEW_CONFIDENCE(self) -> float:
        return float(_env("CLASSIFY_REVIEW_CONFIDENCE", "0.70") or 0.70)

    @property
    def RESEARCH_MAX_SOURCES(self) -> int:
        return int(_env("RESEARCH_MAX_SOURCES", "5") or 5)

    @property
    def QDRANT_URL(self) -> str:
        return _env("QDRANT_URL", "http://127.0.0.1:6333") or "http://127.0.0.1:6333"

    @property
    def QDRANT_COLLECTION(self) -> str:
        return _env("QDRANT_COLLECTION", "product_chunks") or "product_chunks"

    @property
    def EMBEDDING_MODEL(self) -> str:
        return _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5") or "BAAI/bge-small-en-v1.5"

    @property
    def CHUNK_SIZE(self) -> int:
        return int(_env("CHUNK_SIZE", "2400") or 2400)

    @property
    def CHUNK_OVERLAP(self) -> int:
        return int(_env("CHUNK_OVERLAP", "300") or 300)

    @property
    def ATTRIBUTE_EVIDENCE_TOP_K(self) -> int:
        return int(_env("ATTRIBUTE_EVIDENCE_TOP_K", "5") or 5)

    @property
    def JOB_WORKERS(self) -> int:
        return int(_env("JOB_WORKERS", "2") or 2)

    @property
    def JOB_MAX_RETRIES(self) -> int:
        return int(_env("JOB_MAX_RETRIES", "1") or 1)

    @property
    def LLM_RATE_LIMIT_RETRIES(self) -> int:
        return int(_env("LLM_RATE_LIMIT_RETRIES", "5") or 5)


settings = Settings()
