"""Vector + keyword retrieval over an indexed document."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Chunk
from .textutils import (
    STOPWORDS,
    content_tokens,
    cosine_similarity,
    idf_scores,
    safe_snippet,
)


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    vector_score: float
    keyword_score: float

    @property
    def text(self) -> str:
        return self.chunk.text

    def as_evidence(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk.id,
            "ordinal": self.chunk.ordinal,
            "heading": self.chunk.heading,
            "score": round(self.score, 4),
            "quote": safe_snippet(self.chunk.text),
        }


def _keyword_score(query_tokens: set[str], text: str, idf: dict[str, float], max_idf: float) -> float:
    if not query_tokens:
        return 0.0
    tokens = [t for t in content_tokens(text) if t not in STOPWORDS]
    if not tokens:
        return 0.0
    hits = 0.0
    for token in set(tokens):
        if token in query_tokens:
            hits += idf.get(token, max_idf)
    possible = sum(idf.get(t, max_idf) for t in query_tokens) or 1.0
    return min(1.0, hits / possible)


def _mmr(
    candidates: list[RetrievedChunk],
    query_vector: list[float],
    limit: int,
    diversity: float = 0.35,
) -> list[RetrievedChunk]:
    """Maximal marginal relevance: keep the best evidence without repeats."""
    if not candidates:
        return []
    selected: list[RetrievedChunk] = []
    remaining = list(candidates)
    while remaining and len(selected) < limit:
        best: RetrievedChunk | None = None
        best_value = -1e9
        for item in remaining:
            redundancy = 0.0
            for chosen in selected:
                redundancy = max(
                    redundancy,
                    cosine_similarity(
                        item.chunk.embedding or [], chosen.chunk.embedding or []
                    ),
                )
            value = (1 - diversity) * item.score - diversity * redundancy
            if value > best_value:
                best_value = value
                best = item
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return selected


def retrieve(
    db: Session,
    document_id: int,
    query: str,
    top_k: int | None = None,
    min_score: float | None = None,
    extra_terms: Sequence[str] = (),
) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    min_score = settings.retrieval_min_score if min_score is None else min_score

    chunks = list(
        db.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.ordinal)
        )
    )
    if not chunks:
        return []

    from .embeddings import embed

    query_tokens = set(content_tokens(query)) | {
        t for t in content_tokens(" ".join(extra_terms)) if t not in STOPWORDS
    }
    query_vector = embed(query)

    texts = [c.text for c in chunks]
    idf = idf_scores(texts)
    max_idf = max(idf.values()) if idf else 1.0

    scored: list[RetrievedChunk] = []
    for chunk in chunks:
        vector = chunk.embedding or []
        vector_score = cosine_similarity(query_vector, vector) if vector else 0.0
        keyword_score = _keyword_score(query_tokens, chunk.text, idf, max_idf)
        score = round(0.68 * vector_score + 0.32 * keyword_score, 6)
        if chunk.heading:
            heading_tokens = set(content_tokens(chunk.heading))
            if heading_tokens & query_tokens:
                score = round(min(1.0, score + 0.08), 6)
        scored.append(
            RetrievedChunk(
                chunk=chunk,
                score=score,
                vector_score=round(vector_score, 6),
                keyword_score=round(keyword_score, 6),
            )
        )

    scored.sort(key=lambda r: r.score, reverse=True)
    pool = [r for r in scored if r.score >= min_score][: max(top_k * 3, top_k)]
    if not pool:
        pool = scored[:top_k]

    selected = _mmr(pool, query_vector, top_k)
    if selected:
        return selected
    return scored[:top_k]


def build_context(results: list[RetrievedChunk], max_chars: int | None = None) -> str:
    settings = get_settings()
    budget = max_chars or settings.retrieval_max_context_chars
    blocks: list[str] = []
    used = 0
    for result in results:
        header = f"[chunk {result.chunk.ordinal}"
        if result.chunk.heading:
            header += f" | section: {result.chunk.heading}"
        header += f" | relevance {result.score:.2f}]"
        block = f"{header}\n{result.chunk.text.strip()}"
        if used + len(block) > budget:
            remaining = budget - used
            if remaining > 400:
                blocks.append(block[:remaining])
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)
