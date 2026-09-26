"""Document endpoints: upload, paste, fetch, knowledge view, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Document, Transformation
from ..rbac import Actor, require
from ..schemas import (
    DocumentDetail,
    DocumentResponse,
    KnowledgeResponse,
    TextIngestRequest,
    UrlIngestRequest,
)
from ..services import ingestion, knowledge, pipeline, provenance, security

router = APIRouter(prefix="/documents", tags=["documents"])


def _detail(document: Document) -> DocumentDetail:
    record = document.knowledge
    return DocumentDetail(
        **DocumentResponse.model_validate(document).model_dump(),
        preview=str(document.meta.get("text_preview", ""))[:1500],
        security=document.meta.get("security"),
        topics=list(record.topics or []) if record else [],
        key_facts=list(record.key_facts or []) if record else [],
        entities=list(record.entities or []) if record else [],
    )


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(require("document:read")),
    db: Session = Depends(get_db),
) -> list[Document]:
    return list(
        db.scalars(
            select(Document).order_by(desc(Document.created_at)).limit(limit).offset(offset)
        )
    )


@router.get("/{public_id}", response_model=DocumentDetail)
def get_document(
    public_id: str,
    actor: Actor = Depends(require("document:read")),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    document = db.scalar(select(Document).where(Document.public_id == public_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Document '{public_id}' not found")
    return _detail(document)


@router.get("/{public_id}/knowledge", response_model=KnowledgeResponse)
def get_knowledge(
    public_id: str,
    actor: Actor = Depends(require("document:read")),
    db: Session = Depends(get_db),
) -> KnowledgeResponse:
    document = db.scalar(select(Document).where(Document.public_id == public_id))
    if document is None or document.knowledge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Knowledge record not found")
    record = document.knowledge
    return KnowledgeResponse(
        summary=record.summary,
        subject=record.subject,
        topics=list(record.topics or []),
        key_facts=list(record.key_facts or []),
        entities=list(record.entities or []),
        indicators=list(record.indicators or []),
        dates=list(record.dates or []),
        figures=list(record.figures or []),
        detected_objective=record.detected_objective,
        reading_level=record.reading_level,
        build_mode=record.build_mode,
    )


@router.post("/upload", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    actor: Actor = Depends(require("document:write")),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    settings = get_settings()
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit",
        )

    filename = file.filename or "upload"
    try:
        content = ingestion.ingest_bytes(
            data, filename, file.content_type, title or None
        )
    except ingestion.IngestionError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    document = pipeline.ingest_source(db, actor, content, raw_bytes=data)
    db.commit()
    db.refresh(document)
    return _detail(document)


@router.post("/text", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def ingest_text(
    payload: TextIngestRequest,
    actor: Actor = Depends(require("document:write")),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    content = ingestion.IngestedContent(
        text=payload.text,
        kind="text",
        title=payload.title,
        media_type="text/plain",
        meta={"filename": f"{payload.title}.txt", "channel": "pasted_text"},
    )
    document = pipeline.ingest_source(db, actor, content)
    db.commit()
    db.refresh(document)
    return _detail(document)


@router.post("/url", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def ingest_url(
    payload: UrlIngestRequest,
    actor: Actor = Depends(require("document:write")),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    try:
        content = ingestion.ingest_url(payload.url, payload.title)
    except ingestion.IngestionError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    document = pipeline.ingest_source(db, actor, content)
    db.commit()
    db.refresh(document)
    return _detail(document)


@router.post("/preview")
def preview_scan(
    text: str = Form(...),
    actor: Actor = Depends(require("document:read")),
) -> dict:
    report = security.scan_text(text, redact_enabled=True, sanitise=True)
    bundle = knowledge.build_knowledge(text)
    return {
        "security": report.to_dict(),
        "preview": {
            "subject": bundle.subject,
            "summary": bundle.summary,
            "topics": bundle.topics[:8],
            "key_facts": bundle.key_facts[:5],
            "figures": bundle.figures[:8],
        },
    }


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    public_id: str,
    actor: Actor = Depends(require("system:admin")),
    db: Session = Depends(get_db),
) -> None:
    document = db.scalar(select(Document).where(Document.public_id == public_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Document '{public_id}' not found")

    transformations = (
        db.scalar(select(func.count(Transformation.id)).where(Transformation.document_id == document.id)) or 0
    )
    provenance.record_audit(
        db,
        action="document.deleted",
        actor=actor.name,
        actor_role=actor.role,
        document_id=document.public_id,
        summary=(
            f"Deleted '{document.title}' and {transformations} transformation record(s); "
            f"source hash {provenance.short_hash(document.file_hash)} retained in the audit chain"
        ),
        detail={
            "file_hash": document.file_hash,
            "text_hash": document.text_hash,
            "transformations": transformations,
        },
    )
    db.delete(document)
    db.commit()
