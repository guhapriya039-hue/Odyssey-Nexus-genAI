"""Segmentation and chunking for retrieval.

Heading-aware first (so a chunk keeps its section title as context), then a
sentence-aware recursive splitter with overlap so facts spanning a boundary are
still retrievable from at least one chunk.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from .textutils import (
    estimate_tokens,
    heading_of,
    is_boilerplate,
    normalise_whitespace,
)


@dataclass
class TextChunk:
    ordinal: int
    text: str
    heading: str | None
    char_start: int
    char_end: int
    token_estimate: int

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "text": self.text,
            "heading": self.heading,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "token_estimate": self.token_estimate,
        }


def segment(text: str) -> list[tuple[str | None, list[str]]]:
    """Split into (heading, body-lines) sections."""
    text = normalise_whitespace(text)
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    buffer: list[str] = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or is_boilerplate(line):
            continue
        heading = heading_of(line)
        if heading is not None:
            if any(b.strip() for b in buffer):
                sections.append((current_heading, buffer))
            current_heading = heading
            buffer = []
            continue
        buffer.append(line)

    if any(b.strip() for b in buffer):
        sections.append((current_heading, buffer))

    if not sections:
        return [(None, [text])] if text else []
    return [(heading, lines) for heading, lines in sections]


def _split_sentences(block: str) -> list[str]:
    from .textutils import split_sentences

    sentences = split_sentences(block)
    return sentences or [block.strip()]


def _pack(sentences: list[str], target: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        addition = len(sentence) + 1
        if current and length + addition > target:
            chunks.append(" ".join(current))
            if overlap > 0:
                tail: list[str] = []
                tail_len = 0
                for previous in reversed(current):
                    if tail_len + len(previous) > overlap:
                        break
                    tail.insert(0, previous)
                    tail_len += len(previous) + 1
                current = tail
                length = tail_len
            else:
                current = []
                length = 0
        current.append(sentence)
        length += addition
    if current:
        chunks.append(" ".join(current))
    return chunks


def _hard_split(text: str, target: int, overlap: int) -> list[str]:
    step = max(1, target - overlap)
    return [text[i : i + target] for i in range(0, len(text), step)]


def chunk_text(text: str, target_chars: int | None = None, overlap_chars: int | None = None) -> list[TextChunk]:
    settings = get_settings()
    target = target_chars or settings.chunk_target_chars
    overlap = overlap_chars if overlap_chars is not None else settings.chunk_overlap_chars
    overlap = min(overlap, max(0, target // 3))

    results: list[TextChunk] = []
    cursor = 0
    ordinal = 0

    for heading, lines in segment(text):
        block = "\n".join(lines)
        if len(block) <= target:
            pieces = [block]
        else:
            pieces = _pack(_split_sentences(block.replace("\n", " ")), target, overlap)
            expanded: list[str] = []
            for piece in pieces:
                expanded.extend(_hard_split(piece, target, overlap) if len(piece) > target else [piece])
            pieces = expanded

        for piece in pieces:
            piece = piece.strip()
            if len(piece) < 40 and results:
                # Fold tiny trailing fragments into the previous chunk.
                previous = results[-1]
                if len(previous.text) + len(piece) <= target * 1.3:
                    previous.text = f"{previous.text} {piece}".strip()
                    previous.char_end = previous.char_start + len(previous.text)
                    previous.token_estimate = estimate_tokens(previous.text)
                    cursor = previous.char_end
                    continue
            if not piece:
                continue
            start = text.find(piece[:80], cursor) if piece else -1
            if start < 0:
                start = cursor
            results.append(
                TextChunk(
                    ordinal=ordinal,
                    text=piece,
                    heading=heading,
                    char_start=start,
                    char_end=start + len(piece),
                    token_estimate=estimate_tokens(piece),
                )
            )
            ordinal += 1
            cursor = start + len(piece)

    return results
