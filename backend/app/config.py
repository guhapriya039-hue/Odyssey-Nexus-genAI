"""Runtime configuration for ODYSSEY TRANSFORM CORE.

All settings are read from environment variables so the same image can run
on a laptop, in Docker, or on private infrastructure without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PIPELINE_VERSION = "1.4.0"
PROMPT_VERSION = "2026.02-grounded-v3"
EMBEDDING_SCHEMA_VERSION = "hash-ngram-v1"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = _env(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "ODYSSEY TRANSFORM CORE"))
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    api_prefix: str = "/api"

    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))

    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "sqlite:///./odyssey.db")
    )
    upload_dir: Path = field(
        default_factory=lambda: Path(_env("UPLOAD_DIR", "./storage/uploads")).resolve()
    )
    max_upload_bytes: int = field(
        default_factory=lambda: _env_int("MAX_UPLOAD_BYTES", 40 * 1024 * 1024)
    )
    retention_days: int = field(default_factory=lambda: _env_int("RETENTION_DAYS", 90))

    cors_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "CORS_ORIGINS",
            ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"],
        )
    )

    # ---- LLM -----------------------------------------------------------
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    llm_fallback_models: list[str] = field(
        default_factory=lambda: _env_list("LLM_FALLBACK_MODELS", [])
    )
    llm_timeout_seconds: float = field(
        default_factory=lambda: _env_float("LLM_TIMEOUT_SECONDS", 60.0)
    )
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 3))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))
    llm_max_output_tokens: int = field(
        default_factory=lambda: _env_int("LLM_MAX_OUTPUT_TOKENS", 1400)
    )
    llm_enabled: bool = field(default_factory=lambda: _env_bool("LLM_ENABLED", True))

    # ---- Embeddings ----------------------------------------------------
    embedding_provider: str = field(
        default_factory=lambda: _env("EMBEDDING_PROVIDER", "auto")
    )
    embedding_dimensions: int = field(
        default_factory=lambda: _env_int("EMBEDDING_DIMENSIONS", 512)
    )
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )

    # ---- Retrieval -----------------------------------------------------
    retrieval_top_k: int = field(default_factory=lambda: _env_int("RETRIEVAL_TOP_K", 6))
    retrieval_min_score: float = field(
        default_factory=lambda: _env_float("RETRIEVAL_MIN_SCORE", 0.12)
    )
    retrieval_max_context_chars: int = field(
        default_factory=lambda: _env_int("RETRIEVAL_MAX_CONTEXT_CHARS", 9000)
    )

    # ---- Guardrails ----------------------------------------------------
    chunk_target_chars: int = field(default_factory=lambda: _env_int("CHUNK_TARGET_CHARS", 1100))
    chunk_overlap_chars: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP_CHARS", 180))
    injection_block_threshold: float = field(
        default_factory=lambda: _env_float("INJECTION_BLOCK_THRESHOLD", 0.45)
    )
    pii_redaction_enabled: bool = field(default_factory=lambda: _env_bool("PII_REDACTION", True))
    grounding_min_score: float = field(
        default_factory=lambda: _env_float("GROUNDING_MIN_SCORE", 0.55)
    )
    numeric_grounding_enabled: bool = field(
        default_factory=lambda: _env_bool("NUMERIC_GROUNDING", True)
    )
    allow_web_ingestion: bool = field(default_factory=lambda: _env_bool("ALLOW_WEB_INGESTION", True))
    allow_private_network_fetch: bool = field(
        default_factory=lambda: _env_bool("ALLOW_PRIVATE_NETWORK_FETCH", False)
    )
    ocr_enabled: bool = field(default_factory=lambda: _env_bool("OCR_ENABLED", True))
    speech_to_text_enabled: bool = field(
        default_factory=lambda: _env_bool("SPEECH_TO_TEXT_ENABLED", True)
    )

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.llm_base_url and self.llm_model)

    @property
    def model_chain(self) -> list[str]:
        chain = [self.llm_model] if self.llm_model else []
        chain.extend(m for m in self.llm_fallback_models if m not in chain)
        return chain

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
