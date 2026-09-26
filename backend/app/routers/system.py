"""System endpoints: health, capability metadata, security scanning."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import PIPELINE_VERSION, PROMPT_VERSION, get_settings
from ..constants import (
    AUDIENCE_LABELS,
    DEMO_ACTORS,
    DETAIL_LABELS,
    FORMAT_LABELS,
    FORMAT_MEDIA,
    LANGUAGES,
    OBJECTIVE_LABELS,
    TONE_LABELS,
)
from ..db import get_db
from ..models import AuditEvent, Document, Transformation
from ..rbac import Actor, current_actor
from ..schemas import Capability, HealthResponse, MetaResponse, ScanResponse, SecurityScanRequest
from ..services import embeddings, llm, pipeline, provenance, security

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    try:
        db.execute(select(func.count(Document.id)))
        database_state = "ok"
    except Exception as exc:
        database_state = f"error: {type(exc).__name__}"

    return HealthResponse(
        status="ok",
        version=PIPELINE_VERSION,
        environment=settings.environment,
        database=database_state,
        llm=llm.get_client().health(),
        documents=db.scalar(select(func.count(Document.id))) or 0,
        transformations=db.scalar(select(func.count(Transformation.id))) or 0,
        audit_head=provenance.head_hash(db),
        server_time=dt.datetime.now(dt.UTC),
    )


@router.get("/meta", response_model=MetaResponse)
def meta(actor: Actor = Depends(current_actor)) -> MetaResponse:
    settings = get_settings()
    provider = embeddings.get_provider()
    return MetaResponse(
        app_name=settings.app_name,
        version=PIPELINE_VERSION,
        pipeline_version=PIPELINE_VERSION,
        prompt_version=PROMPT_VERSION,
        environment=settings.environment,
        llm_configured=settings.llm_configured,
        llm_model=settings.llm_model or None,
        llm_model_chain=settings.model_chain,
        embedding_provider=provider.name,
        ocr_enabled=settings.ocr_enabled,
        speech_to_text_enabled=settings.speech_to_text_enabled,
        web_ingestion_enabled=settings.allow_web_ingestion,
        generation_modes=["llm", "extractive"],
        formats=[
            Capability(id=key, label=label, media=FORMAT_MEDIA.get(key, "document"))
            for key, label in FORMAT_LABELS.items()
        ],
        tones=[Capability(id=key, label=label, media="tone") for key, label in TONE_LABELS.items()],
        audiences=[
            Capability(id=key, label=label, media="audience") for key, label in AUDIENCE_LABELS.items()
        ],
        objectives=[
            Capability(id=key, label=label, media="objective") for key, label in OBJECTIVE_LABELS.items()
        ],
        details=[Capability(id=key, label=label, media="detail") for key, label in DETAIL_LABELS.items()],
        languages=LANGUAGES,
        demo_actors=DEMO_ACTORS,
    )


@router.get("/config")
def system_config(actor: Actor = Depends(current_actor)) -> dict:
    return pipeline.system_settings_summary()


@router.post("/security/scan", response_model=ScanResponse)
def scan(
    payload: SecurityScanRequest,
    actor: Actor = Depends(current_actor),
) -> ScanResponse:
    report = security.scan_text(payload.text, redact_enabled=True, sanitise=True)
    return ScanResponse(
        report={
            "injection_score": report.injection_score,
            "injection_patterns": report.injection_patterns,
            "pii_findings": report.pii_findings,
            "pii_count": report.pii_count,
            "risk_level": report.risk_level,
            "redactions_applied": report.redactions_applied,
            "sanitised_text": report.sanitised_text,
            "recommendations": report.recommendations,
        }
    )


@router.get("/audit/verify")
def verify_chain(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> dict:
    return provenance.verify_audit_chain(db)


@router.get("/stats")
def stats(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> dict:
    from ..constants import TransformationStatus
    from ..models import Output

    rows = db.execute(
        select(Transformation.status, func.count(Transformation.id)).group_by(Transformation.status)
    ).all()
    grounding = db.scalar(select(func.avg(Output.grounding_score))) or 0.0
    documents = db.scalar(select(func.count(Document.id))) or 0
    outputs = db.scalar(select(func.count(Output.id))) or 0
    audit_events = db.scalar(select(func.count(AuditEvent.id))) or 0
    completed = (
        db.scalar(
            select(func.count(Transformation.id)).where(
                Transformation.status.in_(
                    [
                        TransformationStatus.COMPLETED,
                        TransformationStatus.COMPLETED_WITH_WARNINGS,
                    ]
                )
            )
        )
        or 0
    )

    return {
        "documents": documents,
        "outputs": outputs,
        "audit_events": audit_events,
        "avg_grounding_score": round(float(grounding), 4),
        "status_breakdown": {row[0]: row[1] for row in rows},
        "completed": completed,
    }
