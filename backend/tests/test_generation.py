"""Generation engine, factuality guard and provenance chain."""

from __future__ import annotations

import pytest

from app.constants import DetailLevel, OutputFormat
from app.services import factuality, generation, knowledge, llm, provenance, retrieval


def _evidence() -> list[retrieval.RetrievedChunk]:
    """Synthetic evidence objects; DB-backed retrieval is covered by the API tests."""
    from app.services.embeddings import embed

    class _Chunk:
        def __init__(self, ordinal: int, text: str, heading: str | None) -> None:
            self.id = ordinal
            self.ordinal = ordinal
            self.text = text
            self.heading = heading

    texts = [
        ("The campaign generated 412,000 authentication attempts, of which 9,180 succeeded.", "Executive Summary"),
        ("Estimated exposure is 9,180 customer accounts and no card data was accessed.", "Impact Assessment"),
        ("Enforce mandatory multi-factor authentication for all retail accounts.", "Recommended Actions"),
        ("The cafeteria menu changes weekly and includes a vegetarian option.", None),
    ]
    results: list[retrieval.RetrievedChunk] = []
    for ordinal, (text, heading) in enumerate(texts):
        chunk = _Chunk(ordinal, text, heading)
        chunk.embedding = embed(text)  # type: ignore[attr-defined]
        results.append(
            retrieval.RetrievedChunk(
                chunk=chunk,  # type: ignore[arg-type]
                score=1.0 - ordinal * 0.1,
                vector_score=0.9,
                keyword_score=0.5,
            )
        )
    return results


def _bundle():
    from tests.conftest import SAMPLE_SOURCE

    return knowledge.build_knowledge(SAMPLE_SOURCE)


def _config(**overrides) -> dict:
    config = {
        "audience": "executive",
        "tone": "neutral",
        "language": "en",
        "objective": "inform",
        "detail": DetailLevel.BALANCED,
        "user_instruction": "",
        "source_title": "Meridian Threat Report",
    }
    config.update(overrides)
    return config


def test_every_declared_format_produces_output() -> None:
    bundle = _bundle()
    evidence = _evidence()
    client = llm.get_client()
    assert not client.configured, "tests must run in deterministic extractive mode"

    for output_format in OutputFormat:
        generated, engine = generation.generate(output_format, _config(), bundle, evidence, client)
        assert engine == "extractive"
        assert generated.body.strip(), output_format
        assert generated.title
        assert generated.section_map
        assert "<<SOURCE>>" not in generated.body


def test_detail_level_changes_output_length() -> None:
    bundle = _bundle()
    evidence = _evidence()
    client = llm.get_client()
    brief, _ = generation.generate(
        OutputFormat.ADVISORY, _config(detail=DetailLevel.BRIEF), bundle, evidence, client
    )
    full, _ = generation.generate(
        OutputFormat.ADVISORY, _config(detail=DetailLevel.COMPREHENSIVE), bundle, evidence, client
    )
    assert len(full.body) > len(brief.body)


def test_x_post_respects_character_budget() -> None:
    generated, _ = generation.generate(
        OutputFormat.X_POST, _config(), _bundle(), _evidence(), llm.get_client()
    )
    assert len(generated.body) <= 270


def test_linkedin_post_respects_character_budget() -> None:
    generated, _ = generation.generate(
        OutputFormat.LINKEDIN, _config(), _bundle(), _evidence(), llm.get_client()
    )
    assert len(generated.body) <= 1400


def test_outputs_only_use_source_facts() -> None:
    """A number absent from the source must never appear in an output."""
    bundle = _bundle()
    evidence = _evidence()
    client = llm.get_client()
    for output_format in OutputFormat:
        generated, _ = generation.generate(output_format, _config(), bundle, evidence, client)
        for banned in ("47,000", "13,500", "99.9%", "acme"):
            assert banned not in generated.body, (output_format, banned)


def test_factuality_flags_invented_numbers() -> None:
    evidence = _evidence()
    grounded = factuality.check_output(
        "The campaign generated 412,000 authentication attempts, of which 9,180 succeeded.",
        evidence,
    )
    assert grounded.verdict == "grounded"
    assert grounded.grounding_score > 0.9

    drifted = factuality.check_output(
        "The campaign generated 47,000,000 authentication attempts across 91 countries.",
        evidence,
    )
    assert drifted.verdict in {"numeric_drift", "ungrounded", "weakly_grounded"}
    assert drifted.invented_numbers


def test_factuality_accepts_explicit_gap_markers() -> None:
    evidence = _evidence()
    report = factuality.check_output(
        "Total financial loss: Not stated in source.", evidence
    )
    assert report.verdict in {"grounded", "partially_grounded"}


def _source_evidence() -> list[retrieval.RetrievedChunk]:
    """Evidence covering the whole sample, so scoring is not truncated by a stub.

    ``_evidence()`` is a four-chunk stand-in. Pairing it with a bundle built
    from the full sample would make claims outside those four chunks count as
    unsupported, which says nothing about layout handling.
    """
    from app.services.chunking import chunk_text
    from app.services.embeddings import embed
    from tests.conftest import SAMPLE_SOURCE

    class _Chunk:
        def __init__(self, ordinal: int, text: str, heading: str | None) -> None:
            self.id = ordinal
            self.ordinal = ordinal
            self.text = text
            self.heading = heading
            self.embedding = embed(text)

    results: list[retrieval.RetrievedChunk] = []
    for ordinal, chunk in enumerate(chunk_text(SAMPLE_SOURCE)):
        results.append(
            retrieval.RetrievedChunk(
                chunk=_Chunk(ordinal, chunk.text, getattr(chunk, "heading", None)),  # type: ignore[arg-type]
                score=1.0,
                vector_score=1.0,
                keyword_score=1.0,
            )
        )
    return results


@pytest.mark.parametrize(
    "output_format",
    [
        OutputFormat.EXECUTIVE_SUMMARY,
        OutputFormat.INFOGRAPHIC,
        OutputFormat.PRESENTATION,
        OutputFormat.VIDEO_SCRIPT,
        OutputFormat.STORYBOARD,
        OutputFormat.NARRATION_SUBTITLES,
    ],
)
def test_every_layout_style_is_factuality_checked(output_format: OutputFormat) -> None:
    """Layout scaffolding must not hide a format's claims from the gate.

    Infographic, storyboard and video formats wrap content in bracketed scene
    tags and ``Label:`` fields. If the gate scores the layout instead of the
    prose it reports 0% grounding on artefacts that restate the source exactly,
    which would block approval in the UI.
    """
    bundle = _bundle()
    evidence = _source_evidence()
    client = llm.get_client()
    generated, _ = generation.generate(output_format, _config(), bundle, evidence, client)

    claims = factuality.extract_claims(generated.body)
    assert claims, f"{output_format} produced no checkable claims"

    report = factuality.check_output(generated.body, evidence)
    assert report.grounding_score > 0.9, (output_format, report.coverage_note)
    assert report.verdict == "grounded", (output_format, report.claims_unsupported)


def test_extract_claims_strips_layout_and_keeps_content() -> None:
    structured = (
        "# Meridian Financial Group - Storyboard\n"
        "\n"
        "[Frame 1 | Wide shot | Dashboard overlay]\n"
        "Body: The campaign generated 412,000 authentication attempts.\n"
        "Stat: Not stated in source\n"
        "[End card] On-screen text: The campaign generated 412,000 attempts.\n"
    )
    claims = factuality.extract_claims(structured)
    assert "The campaign generated 412,000 authentication attempts." in claims
    assert not any(c.startswith("[Frame") for c in claims)
    assert not any("Dashboard overlay" in c for c in claims)


def test_stat_lines_are_verified_numerically_not_semantically() -> None:
    evidence = _evidence()
    body = "Body: The campaign generated 412,000 authentication attempts.\n"
    supported = factuality.check_output(f"[Panel 1] Attempts\nStat: 412,000 (as stated in source)\n{body}", evidence)
    assert supported.verdict == "grounded", supported.coverage_note
    assert "412,000" not in supported.invented_numbers

    drifted = factuality.check_output(
        f"[Panel 1] Attempts\nStat: 47,000,000 (as stated in source)\n{body}", evidence
    )
    assert drifted.verdict in {"numeric_drift", "ungrounded", "weakly_grounded"}
    assert "47000000" in drifted.invented_numbers


def test_production_metadata_is_not_scored_as_a_claim() -> None:
    """Runtimes and confidence notes are true by construction."""
    evidence = _evidence()
    report = factuality.check_output(
        "[Scene 1 | Wide shot | ~14s]\n"
        "Narration: The campaign generated 412,000 authentication attempts.\n"
        "Total narration: approximately 87 seconds.\n",
        evidence,
    )
    assert report.grounding_score == 1.0
    assert report.invented_numbers == []
    assert not any("87" in c["text"] for c in report.claims_unsupported)


def test_audit_chain_verifies_and_detects_tampering() -> None:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import AuditEvent
    from app.services.provenance import (
        GENESIS_HASH,
        canonical_timestamp,
        chain_hash,
        record_audit,
        verify_audit_chain,
    )

    with session_scope() as db:
        record_audit(
            db,
            action="test.event",
            actor="tester",
            actor_role="admin",
            summary="chain test entry",
            detail={"n": 1},
        )

    with session_scope() as db:
        result = verify_audit_chain(db)
        assert result["valid"] is True
        assert result["length"] >= 1

        head = db.scalar(select(AuditEvent.entry_hash).order_by(AuditEvent.seq.desc()).limit(1))
        assert head

    # Tamper with the newest entry, then re-verify.
    with session_scope() as db:
        event = db.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
        event.summary = "quietly altered after the fact"

    with session_scope() as db:
        result = verify_audit_chain(db)
        assert result["valid"] is False
        assert result["broken_at_seq"] is not None

    # Restore so later tests see an intact chain.
    with session_scope() as db:
        event = db.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
        event.summary = "chain test entry"
        event.entry_hash = chain_hash(event.prev_hash, {
            "seq": event.seq,
            "action": event.action,
            "actor": event.actor,
            "actor_role": event.actor_role,
            "document_id": event.document_id,
            "transformation_id": event.transformation_id,
            "summary": event.summary,
            "detail": event.detail,
            "timestamp": canonical_timestamp(event.created_at),
        })
        assert event.prev_hash == GENESIS_HASH or event.prev_hash


def test_provenance_manifest_is_stable() -> None:
    import datetime as dt

    kwargs = dict(
        transformation_id="TRF-260101-120000-ABC123",
        source_hash="a" * 64,
        source_title="Report",
        source_kind="text",
        outputs=[
            {"format": "advisory", "output_hash": "b" * 64, "review_state": "pending_review", "grounding_score": 0.9},
            {"format": "x_post", "output_hash": "c" * 64, "review_state": "approved", "grounding_score": 0.8},
        ],
        model_version="offline-extractive-v1",
        prompt_version="2026.02-grounded-v3",
        pipeline_version="1.4.0",
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    first = provenance.build_provenance_manifest(**kwargs)
    second = provenance.build_provenance_manifest(**kwargs)
    assert first["manifest_hash"] == second["manifest_hash"]
    assert [o["format"] for o in first["outputs"]] == ["advisory", "x_post"]
