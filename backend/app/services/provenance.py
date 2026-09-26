"""Provenance: content hashing, transformation identity, tamper-evident audit.

Every artefact carries a SHA-256. The audit log is a hash chain, so an entry
that is edited or removed afterwards is detectable without a trusted clock or
third party - which is the practical, deployable version of "tamper-evident
content provenance".
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..models import AuditEvent

GENESIS_HASH = "0" * 64
HASH_ALGORITHM = "sha256"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(payload: Any) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _b36(number: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"
    out: list[str] = []
    while number:
        number, remainder = divmod(number, 36)
        out.append(alphabet[remainder])
    return "".join(reversed(out))


def new_transformation_id(now: dt.datetime | None = None) -> str:
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%y%m%d-%H%M%S")
    return f"TRF-{stamp}-{secrets.token_hex(3).upper()}"


def new_public_id(prefix: str = "DOC") -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


def chain_hash(prev_hash: str, payload: Any) -> str:
    return sha256_text(f"{prev_hash}|{canonical_json(payload)}")


def canonical_timestamp(value: dt.datetime) -> str:
    """Stable UTC ISO-8601 form, tolerant of naive values from SQLite."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC).isoformat()


def head_hash(db: Session) -> str:
    value = db.scalars(
        select(AuditEvent.entry_hash).order_by(desc(AuditEvent.seq)).limit(1)
    ).first()
    return value or GENESIS_HASH


def next_seq(db: Session) -> int:
    current = db.scalar(select(func.max(AuditEvent.seq)))
    return int(current or 0) + 1


def record_audit(
    db: Session,
    *,
    action: str,
    actor: str,
    actor_role: str,
    summary: str,
    detail: dict[str, Any] | None = None,
    document_id: str | None = None,
    transformation_id: str | None = None,
) -> AuditEvent:
    """Append one link to the audit chain."""
    detail = detail or {}
    seq = next_seq(db)
    prev = head_hash(db)
    created_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    payload = {
        "seq": seq,
        "action": action,
        "actor": actor,
        "actor_role": actor_role,
        "document_id": document_id,
        "transformation_id": transformation_id,
        "summary": summary,
        "detail": detail,
        "timestamp": canonical_timestamp(created_at),
    }
    event = AuditEvent(
        seq=seq,
        action=action,
        actor=actor,
        actor_role=actor_role,
        document_id=document_id,
        transformation_id=transformation_id,
        summary=summary,
        detail=detail,
        prev_hash=prev,
        entry_hash=chain_hash(prev, payload),
        verified=True,
        created_at=created_at,
    )
    db.add(event)
    return event


def verify_audit_chain(db: Session, limit: int | None = None) -> dict[str, Any]:
    """Recompute the chain from the genesis link."""
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.seq.asc()).limit(limit or -1)))
    if not events:
        return {
            "valid": True,
            "length": 0,
            "head_hash": GENESIS_HASH,
            "broken_at_seq": None,
            "message": "Audit log is empty; chain is intact by definition.",
        }

    prev = GENESIS_HASH
    for index, event in enumerate(events):
        if event.prev_hash != prev:
            return {
                "valid": False,
                "length": len(events),
                "head_hash": events[-1].entry_hash,
                "broken_at_seq": event.seq,
                "message": f"Chain break at seq {event.seq}: prev_hash does not match the preceding entry.",
            }
        expected = chain_hash(
            event.prev_hash,
            {
                "seq": event.seq,
                "action": event.action,
                "actor": event.actor,
                "actor_role": event.actor_role,
                "document_id": event.document_id,
                "transformation_id": event.transformation_id,
                "summary": event.summary,
                "detail": event.detail,
                "timestamp": canonical_timestamp(event.created_at) if event.created_at else "",
            },
        )
        if expected != event.entry_hash:
            return {
                "valid": False,
                "length": len(events),
                "head_hash": events[-1].entry_hash,
                "broken_at_seq": event.seq,
                "message": f"Entry at seq {event.seq} has been modified after it was written.",
            }
        prev = event.entry_hash
        if index == 0 and event.seq != 1:
            return {
                "valid": False,
                "length": len(events),
                "head_hash": events[-1].entry_hash,
                "broken_at_seq": event.seq,
                "message": "Chain does not start at seq 1; earlier entries are missing.",
            }

    return {
        "valid": True,
        "length": len(events),
        "head_hash": events[-1].entry_hash,
        "broken_at_seq": None,
        "message": f"All {len(events)} audit entries verified against the hash chain.",
    }


def build_provenance_manifest(
    *,
    transformation_id: str,
    source_hash: str,
    source_title: str,
    source_kind: str,
    outputs: list[dict[str, Any]],
    model_version: str,
    prompt_version: str,
    pipeline_version: str,
    created_at: dt.datetime,
) -> dict[str, Any]:
    manifest = {
        "transformation_id": transformation_id,
        "algorithm": HASH_ALGORITHM,
        "source": {
            "title": source_title,
            "kind": source_kind,
            "hash": source_hash,
        },
        "engine": {
            "model_version": model_version,
            "prompt_version": prompt_version,
            "pipeline_version": pipeline_version,
        },
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        "outputs": sorted(
            (
                {
                    "format": item["format"],
                    "hash": item["output_hash"],
                    "review_state": item.get("review_state", "pending_review"),
                    "grounding_score": item.get("grounding_score", 0.0),
                }
                for item in outputs
            ),
            key=lambda item: item["format"],
        ),
    }
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    return manifest


def short_hash(value: str, length: int = 12) -> str:
    return value[:length]


def encode_hash(value: str) -> str:
    return base64.b16encode(bytes.fromhex(value)).decode("ascii")
