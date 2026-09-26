"""SQLAlchemy models: documents, chunks, knowledge, transformations, outputs, audit."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Document(Base):
    """A single ingested source artefact."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(160))
    source_kind: Mapped[str] = mapped_column(String(40))  # text|pdf|docx|image|web|audio|video
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)   # sha256 of raw bytes
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sha256 of normalised text
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    redaction_count: Mapped[int] = mapped_column(Integer, default=0)
    injection_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), default="none")
    pii_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_by: Mapped[str] = mapped_column(String(160), default="analyst@odyssey.team")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    knowledge: Mapped[Knowledge | None] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    transformations: Mapped[list[Transformation]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def short_id(self) -> str:
        return self.public_id[:8]


class Chunk(Base):
    """A retrievable, embedded slice of a document."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_ordinal", "document_id", "ordinal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    heading: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Knowledge(Base):
    """Structured knowledge representation derived once per document.

    Every output format is generated from this single object, which is what
    keeps multi-format output consistent ("one source, many outputs").
    """

    __tablename__ = "knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    key_facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    indicators: Mapped[list[str]] = mapped_column(JSON, default=list)
    dates: Mapped[list[str]] = mapped_column(JSON, default=list)
    figures: Mapped[list[str]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(400), default="")
    detected_objective: Mapped[str] = mapped_column(String(40), default="inform")
    reading_level: Mapped[str] = mapped_column(String(40), default="technical")
    build_mode: Mapped[str] = mapped_column(String(40), default="deterministic")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="knowledge")


class Transformation(Base):
    """One run of the pipeline for a set of requested output formats."""

    __tablename__ = "transformations"

    id: Mapped[int] = mapped_column(primary_key=True)
    transformation_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_formats: Mapped[list[str]] = mapped_column(JSON, default=list)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source_hash: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(200), default="offline-extractive")
    prompt_version: Mapped[str] = mapped_column(String(64))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    generation_mode: Mapped[str] = mapped_column(String(40), default="extractive")
    llm_attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    requested_by: Mapped[str] = mapped_column(String(160), default="analyst@odyssey.team")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="transformations")
    outputs: Mapped[list[Output]] = relationship(
        back_populates="transformation", cascade="all, delete-orphan"
    )


class Output(Base):
    """A generated communication artefact plus its verification record."""

    __tablename__ = "outputs"
    __table_args__ = (
        UniqueConstraint("transformation_id", "format", name="uq_output_per_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transformation_id: Mapped[int] = mapped_column(
        ForeignKey("transformations.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(400), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    edited_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_map: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    output_hash: Mapped[str] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    grounding_score: Mapped[float] = mapped_column(Float, default=0.0)
    factuality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    security: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    review_state: Mapped[str] = mapped_column(String(24), default="pending_review")
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transformation: Mapped[Transformation] = relationship(back_populates="outputs")

    @property
    def effective_body(self) -> str:
        return self.edited_body or self.body


class AuditEvent(Base):
    """Tamper-evident audit chain.

    Each row stores the hash of the previous row, so any modification or
    deletion breaks the chain and is detectable with :func:`verify_audit_chain`.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(160))
    actor_role: Mapped[str] = mapped_column(String(24))
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transformation_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettingKV(Base):
    """Small key/value store for counters and deployment metadata."""

    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
