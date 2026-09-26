"""Output endpoints: read, edit, regenerate, review, export, verify."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..constants import FORMAT_LABELS
from ..db import get_db
from ..models import Output, Transformation
from ..rbac import Actor, current_actor, require
from ..schemas import OutputEditRequest, OutputResponse, ReviewRequest, VerifyRequest
from ..services import pipeline, provenance

router = APIRouter(prefix="/outputs", tags=["outputs"])


def _load(db: Session, output_id: int) -> Output:
    output = db.scalar(
        select(Output)
        .where(Output.id == output_id)
        .options(selectinload(Output.transformation).selectinload(Transformation.document))
    )
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Output {output_id} not found")
    return output


@router.get("/{output_id}", response_model=OutputResponse)
def get_output(
    output_id: int,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> Output:
    return _load(db, output_id)


@router.put("/{output_id}", response_model=OutputResponse)
def edit_output(
    output_id: int,
    payload: OutputEditRequest,
    actor: Actor = Depends(require("output:write")),
    db: Session = Depends(get_db),
) -> Output:
    output = _load(db, output_id)
    previous_hash = output.output_hash
    transformation = output.transformation

    output.edited_body = payload.body
    output.body = payload.body
    output.output_hash = provenance.sha256_text(payload.body)
    output.char_count = len(payload.body)
    output.version += 1
    output.review_state = "pending_review"
    output.reviewed_by = None
    output.reviewed_at = None
    output.validation = {
        **(output.validation or {}),
        "edited": True,
        "edit_note": payload.note,
        "pre_edit_hash": previous_hash,
        "post_edit_hash": output.output_hash,
        "edited_by": actor.name,
    }
    db.flush()

    provenance.record_audit(
        db,
        action="output.edited",
        actor=actor.name,
        actor_role=actor.role,
        document_id=transformation.document.public_id if transformation.document else None,
        transformation_id=transformation.transformation_id,
        summary=f"Human-edited '{output.format}' (v{output.version}); approval reset",
        detail={
            "output_id": output.id,
            "format": output.format,
            "pre_edit_hash": previous_hash,
            "post_edit_hash": output.output_hash,
            "note": payload.note,
        },
    )
    db.commit()
    db.refresh(output)
    return output


@router.post("/{output_id}/regenerate", response_model=OutputResponse)
def regenerate(
    output_id: int,
    actor: Actor = Depends(require("transform:run")),
    db: Session = Depends(get_db),
) -> Output:
    output = _load(db, output_id)
    transformation = output.transformation
    if transformation.document is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Source document is no longer available")

    try:
        output, _engine = pipeline.regenerate_output(db, actor, transformation, output)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    db.refresh(output)
    return output


@router.post("/{output_id}/review", response_model=OutputResponse)
def review(
    output_id: int,
    payload: ReviewRequest,
    actor: Actor = Depends(require("output:approve")),
    db: Session = Depends(get_db),
) -> Output:
    import datetime as dt

    output = _load(db, output_id)
    output.review_state = payload.state
    output.review_note = payload.note
    output.reviewed_by = actor.name
    output.reviewed_at = dt.datetime.now(dt.UTC)
    db.flush()

    transformation = output.transformation
    provenance.record_audit(
        db,
        action=f"output.{payload.state}",
        actor=actor.name,
        actor_role=actor.role,
        document_id=transformation.document.public_id if transformation.document else None,
        transformation_id=transformation.transformation_id,
        summary=f"'{output.format}' marked {payload.state} by {actor.name}",
        detail={
            "output_id": output.id,
            "format": output.format,
            "state": payload.state,
            "note": payload.note,
            "output_hash": output.output_hash,
            "grounding_score": round(output.grounding_score, 4),
        },
    )
    db.commit()
    db.refresh(output)
    return output


@router.get("/{output_id}/export")
def export_output(
    output_id: int,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> Response:
    output = _load(db, output_id)
    label = FORMAT_LABELS.get(output.format, output.format)
    body = output.effective_body
    header = (
        f"-- ODYSSEY TRANSFORM CORE EXPORT\n"
        f"-- format: {label}\n"
        f"-- transformation: {output.transformation.transformation_id}\n"
        f"-- model: {output.transformation.model_version}\n"
        f"-- prompt: {output.transformation.prompt_version}\n"
        f"-- source_hash: {output.transformation.source_hash}\n"
        f"-- output_hash: {output.output_hash}\n"
        f"-- grounding: {output.grounding_score:.2f}\n"
        f"-- review: {output.review_state}\n"
        f"-- generated: {output.created_at.isoformat()}\n"
        f"{'-' * 60}\n\n"
    )
    filename = f"{output.transformation.transformation_id}-{output.format}.md"
    return Response(
        content=header + body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{output_id}/verify")
def verify(
    output_id: int,
    payload: VerifyRequest,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> dict:
    output = _load(db, output_id)
    return pipeline.verify_source_binding(db, output, payload.source_text)
