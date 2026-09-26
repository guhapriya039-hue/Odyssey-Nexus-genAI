"""Pydantic request/response contracts."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Requests ---------------------------------------------------------


class TransformRequest(BaseModel):
    formats: list[str] = Field(min_length=1, max_length=9)
    audience: str = "executive"
    tone: str = "neutral"
    language: str = "en"
    objective: str = "inform"
    detail: str = "balanced"
    user_instruction: str = Field(default="", max_length=2000)
    include_pii: bool = False
    auto_approve: bool = False

    @field_validator("formats")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        return seen


class TextIngestRequest(BaseModel):
    title: str = Field(default="Pasted source", max_length=300)
    text: str = Field(min_length=1, max_length=400_000)


class UrlIngestRequest(BaseModel):
    url: str = Field(max_length=2000)
    title: str = Field(default="", max_length=300)


class OutputEditRequest(BaseModel):
    body: str = Field(min_length=1, max_length=200_000)
    note: str = Field(default="", max_length=1000)


class ReviewRequest(BaseModel):
    state: str
    note: str = Field(default="", max_length=1000)

    @field_validator("state")
    @classmethod
    def _valid_state(cls, value: str) -> str:
        allowed = {"draft", "pending_review", "approved", "rejected"}
        if value not in allowed:
            raise ValueError(f"state must be one of {sorted(allowed)}")
        return value


class SecurityScanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class VerifyRequest(BaseModel):
    source_text: str = Field(default="", max_length=400_000)


# ---- Responses --------------------------------------------------------


class Capability(BaseModel):
    id: str
    label: str
    media: str


class MetaResponse(BaseModel):
    app_name: str
    version: str
    pipeline_version: str
    prompt_version: str
    environment: str
    llm_configured: bool
    llm_model: str | None
    llm_model_chain: list[str]
    embedding_provider: str
    ocr_enabled: bool
    speech_to_text_enabled: bool
    web_ingestion_enabled: bool
    generation_modes: list[str]
    formats: list[Capability]
    tones: list[Capability]
    audiences: list[Capability]
    objectives: list[Capability]
    details: list[Capability]
    languages: dict[str, str]
    demo_actors: dict[str, str]


class SecurityFinding(BaseModel):
    category: str
    label: str
    severity: str
    evidence: str
    position: int
    redacted_value: str | None = None


class SecurityReport(BaseModel):
    injection_score: float
    injection_patterns: list[str]
    pii_findings: list[SecurityFinding]
    pii_count: int
    risk_level: str
    redactions_applied: int
    sanitised_text: str | None = None
    recommendations: list[str]


class DocumentResponse(ORMModel):
    id: int
    public_id: str
    title: str
    filename: str
    media_type: str
    source_kind: str
    status: str
    status_detail: str | None = None
    byte_size: int
    file_hash: str
    text_hash: str | None = None
    char_count: int
    word_count: int
    chunk_count: int
    redaction_count: int
    injection_score: float
    risk_level: str
    pii_types: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: dt.datetime
    indexed_at: dt.datetime | None = None


class DocumentDetail(DocumentResponse):
    preview: str
    security: SecurityReport | None = None
    topics: list[str] = Field(default_factory=list)
    key_facts: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeResponse(BaseModel):
    summary: str
    subject: str
    topics: list[str]
    key_facts: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    indicators: list[str]
    dates: list[str]
    figures: list[str]
    detected_objective: str
    reading_level: str
    build_mode: str


class EvidenceItem(BaseModel):
    chunk_id: int
    ordinal: int
    heading: str | None = None
    score: float
    quote: str


class OutputResponse(ORMModel):
    id: int
    format: str
    title: str
    body: str
    edited_body: str | None = None
    section_map: list[dict[str, Any]] = Field(default_factory=list)
    output_hash: str
    char_count: int
    evidence: list[EvidenceItem] = Field(default_factory=list)
    grounding_score: float
    factuality: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    review_state: str
    reviewed_by: str | None = None
    review_note: str | None = None
    reviewed_at: dt.datetime | None = None
    version: int
    created_at: dt.datetime

    @property
    def effective_body(self) -> str:
        return self.edited_body or self.body


class TransformationResponse(ORMModel):
    id: int
    transformation_id: str
    document_id: int
    status: str
    stage: str
    error: str | None = None
    requested_formats: list[str]
    config: dict[str, Any]
    source_hash: str
    model_version: str
    prompt_version: str
    pipeline_version: str
    generation_mode: str
    llm_attempts: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)
    requested_by: str
    created_at: dt.datetime
    completed_at: dt.datetime | None = None
    document: DocumentResponse | None = None
    outputs: list[OutputResponse] = Field(default_factory=list)


class TransformationSummary(ORMModel):
    transformation_id: str
    # Public document id, not the internal FK: the dashboard links runs to
    # sources by the same id it used to upload them.
    document_id: str
    document_title: str | None = None
    status: str
    requested_formats: list[str]
    generation_mode: str
    model_version: str
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)
    output_count: int
    avg_grounding: float
    created_at: dt.datetime
    requested_by: str


class AuditEventResponse(ORMModel):
    seq: int
    action: str
    actor: str
    actor_role: str
    document_id: str | None = None
    transformation_id: str | None = None
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    entry_hash: str
    verified: bool
    created_at: dt.datetime


class ChainVerification(BaseModel):
    valid: bool
    length: int
    head_hash: str
    broken_at_seq: int | None = None
    message: str


class ScanResponse(BaseModel):
    report: SecurityReport


class ProvenanceResponse(BaseModel):
    transformation_id: str
    source_hash: str
    source_hash_algorithm: str
    outputs: list[dict[str, Any]]
    model_version: str
    prompt_version: str
    pipeline_version: str
    created_at: dt.datetime
    manifest_hash: str
    manifest: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    llm: str
    documents: int
    transformations: int
    audit_head: str | None = None
    server_time: dt.datetime
