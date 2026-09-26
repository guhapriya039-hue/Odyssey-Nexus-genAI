"""Transformation endpoints: run, list, inspect, provenance."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..constants import FORMAT_LABELS
from ..db import get_db
from ..models import Document, Output, Transformation
from ..rbac import Actor, current_actor, require
from ..schemas import (
    OutputResponse,
    ProvenanceResponse,
    TransformationResponse,
    TransformationSummary,
    TransformRequest,
)
from ..services import pipeline, provenance

router = APIRouter(prefix="/transformations", tags=["transformations"])


def _load(db: Session, transformation_id: str) -> Transformation:
    transformation = db.scalar(
        select(Transformation)
        .where(Transformation.transformation_id == transformation_id)
        .options(
            selectinload(Transformation.outputs),
            selectinload(Transformation.document),
        )
    )
    if transformation is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Transformation '{transformation_id}' not found",
        )
    return transformation


def _validate_formats(formats: list[str]) -> None:
    unknown = [f for f in formats if f not in FORMAT_LABELS]
    if unknown:
        raise HTTPException(
            422,
            detail=f"Unsupported output format(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(FORMAT_LABELS)}",
        )


@router.post("/document/{public_id}", response_model=TransformationResponse, status_code=status.HTTP_201_CREATED)
def create_for_document(
    public_id: str,
    payload: TransformRequest,
    actor: Actor = Depends(require("transform:run")),
    db: Session = Depends(get_db),
) -> Transformation:
    _validate_formats(payload.formats)
    document = db.scalar(select(Document).where(Document.public_id == public_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Document '{public_id}' not found")

    transformation = pipeline.run_transformation(db, actor, document, payload)
    db.commit()
    db.refresh(transformation)
    return _load(db, transformation.transformation_id)


@router.get("", response_model=list[TransformationSummary])
def list_transformations(
    limit: int = Query(default=25, ge=1, le=100),
    document_id: str | None = Query(default=None),
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = (
        select(Transformation, Document.public_id, Document.title)
        .join(Document, Document.id == Transformation.document_id)
        .order_by(desc(Transformation.created_at))
        .limit(limit)
    )
    if document_id:
        query = query.where(Document.public_id == document_id)

    results: list[dict] = []
    for transformation, doc_public_id, document_title in db.execute(query).all():
        outputs = list(transformation.outputs)
        grounding = [o.grounding_score for o in outputs if o.grounding_score is not None]
        results.append(
            {
                "transformation_id": transformation.transformation_id,
                "document_id": doc_public_id,
                "document_title": document_title,
                "status": transformation.status,
                "requested_formats": transformation.requested_formats,
                "generation_mode": transformation.generation_mode,
                "model_version": transformation.model_version,
                "duration_ms": transformation.duration_ms,
                "warnings": transformation.warnings,
                "output_count": len(outputs),
                "avg_grounding": round(sum(grounding) / len(grounding), 4) if grounding else 0.0,
                "created_at": transformation.created_at,
                "requested_by": transformation.requested_by,
            }
        )
    return results



@router.get("/{transformation_id}", response_model=TransformationResponse)
def get_transformation(
    transformation_id: str,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> Transformation:
    return _load(db, transformation_id)


@router.get("/{transformation_id}/provenance", response_model=ProvenanceResponse)
def get_provenance(
    transformation_id: str,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> ProvenanceResponse:
    transformation = _load(db, transformation_id)
    document = transformation.document
    manifest = provenance.build_provenance_manifest(
        transformation_id=transformation.transformation_id,
        source_hash=transformation.source_hash,
        source_title=document.title if document else "unknown",
        source_kind=document.source_kind if document else "unknown",
        outputs=[
            {
                "format": o.format,
                "output_hash": o.output_hash,
                "review_state": o.review_state,
                "grounding_score": o.grounding_score,
            }
            for o in transformation.outputs
        ],
        model_version=transformation.model_version,
        prompt_version=transformation.prompt_version,
        pipeline_version=transformation.pipeline_version,
        created_at=transformation.created_at,
    )
    return ProvenanceResponse(
        transformation_id=transformation.transformation_id,
        source_hash=transformation.source_hash,
        source_hash_algorithm=provenance.HASH_ALGORITHM,
        outputs=manifest["outputs"],
        model_version=transformation.model_version,
        prompt_version=transformation.prompt_version,
        pipeline_version=transformation.pipeline_version,
        created_at=transformation.created_at,
        manifest_hash=manifest["manifest_hash"],
        manifest=manifest,
    )


@router.get("/{transformation_id}/outputs", response_model=list[OutputResponse])
def list_outputs(
    transformation_id: str,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> list[Output]:
    transformation = _load(db, transformation_id)
    return sorted(transformation.outputs, key=lambda o: o.format)


@router.get("/{transformation_id}/compare")
def compare_outputs(
    transformation_id: str,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> dict:
    """Cross-format consistency view: shared facts vs divergent content."""
    transformation = _load(db, transformation_id)
    outputs = list(transformation.outputs)
    numbers: dict[str, list[str]] = {}
    for output in outputs:
        numbers[output.format] = sorted(
            {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", output.body)}
        )[:40]

    all_numbers: set[str] = set()
    for values in numbers.values():
        all_numbers.update(values)
    common = sorted(n for n in all_numbers if all(n in values for values in numbers.values())) if numbers else []
    divergent = sorted(n for n in all_numbers if n not in common)

    return {
        "transformation_id": transformation_id,
        "formats": [o.format for o in outputs],
        "char_counts": {o.format: o.char_count for o in outputs},
        "grounding_scores": {o.format: round(o.grounding_score, 4) for o in outputs},
        "hashes": {o.format: o.output_hash for o in outputs},
        "shared_figures": common,
        "format_specific_figures": {f: divergent for f in numbers} if divergent else {},
        "consistency_note": (
            "Figures present in every format are consistent with the shared knowledge layer."
            if common
            else "No figures are shared across formats; verify before release."
        ),
    }
