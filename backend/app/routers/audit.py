"""Audit trail endpoints (read-only, hash-chain backed)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditEvent
from ..rbac import Actor, current_actor, require
from ..schemas import AuditEventResponse
from ..services import provenance

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventResponse])
def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    transformation_id: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> list[AuditEvent]:
    query = select(AuditEvent).order_by(desc(AuditEvent.seq)).limit(limit)
    if transformation_id:
        query = query.where(AuditEvent.transformation_id == transformation_id)
    if document_id:
        query = query.where(AuditEvent.document_id == document_id)
    return list(db.scalars(query))


@router.get("/chain")
def chain_status(
    actor: Actor = Depends(require("audit:read")),
    db: Session = Depends(get_db),
) -> dict:
    result = provenance.verify_audit_chain(db)
    head = db.scalar(select(AuditEvent.entry_hash).order_by(desc(AuditEvent.seq)).limit(1))
    result["head_hash"] = head or result["head_hash"]
    return result
