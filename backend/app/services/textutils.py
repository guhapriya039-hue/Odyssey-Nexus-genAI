"""Text normalisation, sentence handling and lightweight NLP helpers.

Pure standard library on purpose: the platform must run on private
infrastructure with a minimal dependency footprint.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

WHITESPACE_RE = re.compile(r"[ \t   ]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")
SOFT_HYPHEN_RE = re.compile(r"(\w)-\n(\w)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
BULLET_RE = re.compile(r"^\s*(?:[-*•‣▪●]|\d+[.)]|[a-z][.)])\s+", re.IGNORECASE)
REPEAT_CHAR_RE = re.compile(r"(.)\1{4,}")

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+(?=[\"'“‘(\[]?[A-Z0-9])")

# Very small English function-word list: enough to keep entity/key-term
# extraction honest without shipping a full NLP dependency.
STOPWORDS: frozenset[str] = frozenset(
    ["a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "cannot", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself", "yourselves", "may", "might", "must", "shall", "upon"]
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{1,}")
NUMBER_RE = re.compile(r"\b\d[\d,]*\.?\d*\s?(?:%|percent|k|m|bn|billion|million|thousand)?\b", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{0,4}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{0,4})\b",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s<>\"')]+")
INDICATOR_PATTERNS = (
    re.compile(r"\b(?:CVE-\d{4}-\d{4,7})\b", re.IGNORECASE),
    re.compile(r"\bCWE-\d{1,4}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b"),
    re.compile(r"\b[0-9a-f]{64}\b"),
    re.compile(r"\b[0-9a-f]{40}\b"),
    re.compile(r"\bMITRE ATT&CK\b", re.IGNORECASE),
    re.compile(r"\bT\d{4}(?:\.\d{3})?\b"),
)


def normalise_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = CONTROL_RE.sub(" ", text)
    text = SOFT_HYPHEN_RE.sub(r"\1\2", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return BLANK_LINES_RE.sub("\n\n", text).strip()


def strip_repeated_chars(text: str) -> str:
    return REPEAT_CHAR_RE.sub(r"\1\1\1", text)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


# ---------------------------------------------------------------------------
# Structure detection
#
# Lives here (rather than in chunking) because sentence splitting needs it too:
# hard-wrapped documents must be re-joined into whole sentences, and a heading
# line is a block boundary, not part of the sentence that follows it.
# ---------------------------------------------------------------------------

HEADING_PATTERNS = (
    re.compile(r"^(#{1,6})\s+(.*)$"),
    re.compile(r"^\[?(?:\d+|[IVXLC]+)[.)]\s+\S.{0,110}$"),
    re.compile(r"^(?:chapter|section|part|annex|appendix)\s+[\dIVXLC.]+\b.{0,110}$", re.IGNORECASE),
    re.compile(r"^[A-Z][A-Z0-9 /&,'()\-]{6,90}$"),
    re.compile(r"^(?:page|slide|table)\s+\d+\s*$", re.IGNORECASE),
    re.compile(
        r"^(?:[A-Z][A-Za-z0-9&'/-]*)(?:\s+(?:[A-Z][A-Za-z0-9&'/-]*|of|and|the|to|for|in|on|with|vs|or)){0,6}$"
    ),
    # Title Case lines that carry an ordinal or count, e.g. "Incident Note 44",
    # "Quarter 3 Findings". Without this they fall through and get glued onto
    # the following sentence.
    re.compile(
        r"^(?:[A-Z0-9][A-Za-z0-9&'/-]*)(?:\s+(?:[A-Z0-9][A-Za-z0-9&'/-]*|of|and|the|to|for|in|on|with|vs|or)){0,6}$"
    ),
)

# A line that is nothing but a redaction/suppression marker is a whole block,
# not a fragment to be joined onto its neighbours.
PLACEHOLDER_LINE_RE = re.compile(r"^(?:\[[A-Z][A-Z0-9_]{3,}\]|<[A-Z][A-Z0-9_]{3,}>)$")

# Patterns that need a sentence-vs-heading sanity check: a numbered list item
# ("1. Rotate the token") is indistinguishable from a numbered heading
# ("1. Introduction") by regex alone.
AMBIGUOUS_HEADING_INDEXES = {1, 5, 6}

HEADING_MAX_CHARS = 70
HEADING_MAX_WORDS = 7
TITLE_CASE_RE = HEADING_PATTERNS[6]
SENTENCE_END_RE = re.compile(r"[.,;:!?]$")

BOILERPLATE_RE = re.compile(
    r"^(?:confidential|draft|internal use only|page \d+ of \d+|©.*|all rights reserved.*)$",
    re.IGNORECASE,
)


def heading_of(line: str) -> str | None:
    """Return the heading text if ``line`` is a standalone heading, else ``None``."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None

    for index, pattern in enumerate(HEADING_PATTERNS):
        found = pattern.match(stripped)
        if not found:
            continue
        heading = found.group(found.lastindex or 0) if found.lastindex else stripped
        heading = re.sub(r"^#+\s*", "", heading).strip(" .:-")
        heading = re.sub(r"^\[?(?:\d+|[IVXLC]+)[.)]\s+", "", heading, flags=re.IGNORECASE)
        if not heading or len(heading) < 2:
            continue

        if index in AMBIGUOUS_HEADING_INDEXES:
            if (
                len(stripped) > HEADING_MAX_CHARS
                or len(stripped.split()) > HEADING_MAX_WORDS
                or SENTENCE_END_RE.search(stripped)
            ):
                continue
            if index == 1 and not TITLE_CASE_RE.match(heading):
                continue
        return heading
    return None


def is_boilerplate(line: str) -> bool:
    return bool(BOILERPLATE_RE.match(line.strip()))


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 2]


def split_sentences(text: str) -> list[str]:
    """Whole sentences, even when the source is hard-wrapped mid-sentence.

    Three things are treated as block boundaries: blank lines, headings, and
    list markers. A list marker opens a block that the following wrapped lines
    join onto, so ``1. 61 percent of logins came\\nfrom three networks`` comes
    back as one sentence instead of two fragments.
    """
    text = normalise_whitespace(text)
    if not text:
        return []

    units: list[str] = []
    accumulated: list[str] = []

    def flush() -> None:
        if accumulated:
            units.append(" ".join(accumulated))
            accumulated.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if PLACEHOLDER_LINE_RE.match(line):
            flush()
            units.append(line)
            continue
        if BULLET_RE.match(line):
            flush()
            accumulated.append(re.sub(r"^\s*(?:[-*•‣▪●]|\d+[.)])\s+", "", line))
            continue
        if heading_of(line) is not None:
            flush()
            units.append(line)
            continue
        accumulated.append(line)
    flush()

    parts: list[str] = []
    for unit in units:
        if len(unit.split()) <= 2:
            parts.append(unit)
            continue
        for sentence in SENTENCE_SPLIT_RE.split(unit):
            sentence = sentence.strip()
            if sentence:
                parts.append(sentence)
    return parts


def strip_bullet(text: str) -> str:
    return re.sub(r"^\s*(?:[-*•‣▪●]|\d+[.)])\s+", "", text).strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimate that works for any model family."""
    return max(1, int(len(text) / 3.6))


def word_count(text: str) -> int:
    return len(text.split())


def term_frequencies(texts: list[str]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(set(content_tokens(text)))
    return counter


def idf_scores(texts: list[str]) -> dict[str, float]:
    total = max(1, len(texts))
    document_frequency: Counter[str] = Counter()
    for text in texts:
        document_frequency.update(set(content_tokens(text)))
    scores: dict[str, float] = {}
    for term, freq in document_frequency.items():
        scores[term] = 1.0 + (total / (1.0 + freq))
    return scores


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(size):
        x = a[i]
        y = b[i]
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def safe_snippet(text: str, limit: int = 220) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",;:") + "…"


def slugify(text: str, max_length: int = 60) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (text[:max_length].strip("-")) or "item"


def title_case_heading(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text.isupper() and len(text) > 3:
        return text.title()
    return text[0].upper() + text[1:]
