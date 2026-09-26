"""Preprocessing: chunking, knowledge extraction, embeddings, retrieval."""

from __future__ import annotations

from app.services import chunking, embeddings, knowledge, textutils
from tests.conftest import SAMPLE_SOURCE


def test_normalise_whitespace_removes_noise() -> None:
    raw = "Line   one\t\twith  spaces\r\n\r\n\r\n\r\nLine two\r\nLine  three"
    cleaned = textutils.normalise_whitespace(raw)
    assert "\r" not in cleaned
    assert "Line   one" not in cleaned
    assert cleaned.count("\n\n") == 1


def test_sentence_splitting_handles_bullets() -> None:
    text = "First point. Second point!\n- A bullet item\n- Another bullet"
    sentences = textutils.split_sentences(text)
    assert "First point." in sentences
    assert "A bullet item" in sentences
    assert "Another bullet" in sentences


def test_segmentation_detects_headings() -> None:
    sections = chunking.segment(SAMPLE_SOURCE)
    headings = [h for h, _ in sections if h]
    assert any("Executive Summary" in h for h in headings)
    assert any("Key Findings" in h for h in headings)
    assert any("Recommended Actions" in h for h in headings)


def test_chunking_respects_target_and_keeps_headings() -> None:
    chunks = chunking.chunk_text(SAMPLE_SOURCE, target_chars=300, overlap_chars=60)
    assert len(chunks) > 1
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.text.strip() for c in chunks)
    assert any(c.heading for c in chunks)
    assert all(c.char_end > c.char_start for c in chunks)


def test_chunking_keeps_every_content_character() -> None:
    chunks = chunking.chunk_text(SAMPLE_SOURCE, target_chars=400, overlap_chars=80)
    joined = " ".join(c.text for c in chunks)
    for marker in ("412,000", "9,180", "CVE-2026-21887", "45.77.201.19"):
        assert marker in joined, marker


def test_hashing_embeddings_are_deterministic_and_normalised() -> None:
    a = embeddings.hashing_embed("credential stuffing attack on retail portal", 512)
    b = embeddings.hashing_embed("credential stuffing attack on retail portal", 512)
    assert a == b
    assert len(a) == 512
    norm = sum(v * v for v in a) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_embedding_similarity_orders_sensibly() -> None:
    query = embeddings.hashing_embed("how many authentication attempts were observed")
    same = embeddings.hashing_embed(
        "The campaign generated 412,000 authentication attempts, of which 9,180 succeeded."
    )
    other = embeddings.hashing_embed(
        "The cafeteria opens at eight and serves vegetarian options daily."
    )
    assert textutils.cosine_similarity(query, same) > textutils.cosine_similarity(query, other)


def test_knowledge_extraction_finds_structure() -> None:
    bundle = knowledge.build_knowledge(SAMPLE_SOURCE)
    assert bundle.subject
    assert bundle.summary
    assert bundle.topics
    assert len(bundle.key_facts) >= 5
    categories = {f["category"] for f in bundle.key_facts}
    assert categories & {"finding", "impact", "recommendation", "context"}
    assert "CVE-2026-21887" in bundle.indicators
    assert "45.77.201.19" in bundle.indicators
    assert any("412,000" in f for f in bundle.figures)
    assert bundle.dates
    assert bundle.detected_objective in {"advise", "report", "escalate", "inform"}


def test_knowledge_is_deterministic() -> None:
    first = knowledge.build_knowledge(SAMPLE_SOURCE)
    second = knowledge.build_knowledge(SAMPLE_SOURCE)
    assert first.summary == second.summary
    assert [f["text"] for f in first.key_facts] == [f["text"] for f in second.key_facts]
    assert first.topics == second.topics
