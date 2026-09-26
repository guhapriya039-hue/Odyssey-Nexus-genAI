"""Automated content understanding: build the shared knowledge representation.

This runs once per document and is the single source every output format is
generated from - that is what makes "one source, many outputs, one consistent
truth" true rather than aspirational.

The extractor is deterministic (extractive, no model required) so the platform
works with zero API keys. When an LLM is configured the pipeline can enrich the
result, but never replaces it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .textutils import (
    DATE_RE,
    INDICATOR_PATTERNS,
    NUMBER_RE,
    STOPWORDS,
    content_tokens,
    idf_scores,
    normalise_whitespace,
    safe_snippet,
    split_sentences,
    strip_bullet,
    title_case_heading,
    tokenize,
    truncate_words,
)

TITLE_SIGNALS = re.compile(
    r"^\s*(?:report|white\s*paper|advisory|bulletin|brief|note|memorandum|memo|"
    r"press\s*release|announcement|incident\s*report|assessment|analysis|"
    r"situation\s*report|research\s*paper|guideline|notice|summary)\b",
    re.IGNORECASE,
)

SECTION_SIGNALS = {
    "recommendation": re.compile(r"\b(recommend|recommendation|mitigation|remediation|next\s+steps?|action\s+items?)\b", re.IGNORECASE),
    "impact": re.compile(r"\b(impact|consequence|severity|risk\s+rating|blast\s+radius|affected)\b", re.IGNORECASE),
    "finding": re.compile(r"\b(finding|we\s+observed|analysis\s+shows|evidence|indicator|detected)\b", re.IGNORECASE),
    "context": re.compile(r"\b(context|background|overview|introduction|scope|this\s+document)\b", re.IGNORECASE),
    "timeline": re.compile(r"\b(timeline|on\s+\d|first\s+reported|subsequently|then|followed\s+by)\b", re.IGNORECASE),
}

ACTION_VERBS = re.compile(
    r"^\s*(?:[A-Za-z]+\s+)?(?:should|must|needs?\s+to|is\s+required\s+to|are\s+required\s+to|"
    r"ought\s+to|recommend(?:ed)?|ensure|verify|validate|monitor|block|patch|rotate|isolate|"
    r"audit|escalate|notify|contain|remediate|enforce|invalidate|require|apply|restrict|"
    r"disable|upgrade|implement|review|assess|investigate)\b",
    re.IGNORECASE,
)

# Capitalised words that open sentences but are not named entities.
NON_ENTITY_WORDS = frozenset(
    {
        "audit", "contact", "enforce", "estimated", "invalidate", "notify", "malicious",
        "suspected", "confirmed", "observed", "reported", "detected", "identified",
        "disclosed", "recommended", "required", "following", "overall", "based", "given",
        "since", "while", "during", "between", "within", "without", "across", "through",
        "against", "because", "therefore", "however", "this", "that", "these", "those",
        "there", "their", "they", "them", "then", "when", "where", "which", "will",
        "would", "could", "should", "must", "may", "might", "can", "cannot", "first",
        "second", "third", "finally", "additionally", "note", "notes",
    }
)

MONTHS = frozenset(
    {
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    }
)

RISK_WORDS = re.compile(
    r"\b(critical|severe|high\s+risk|urgent|immediate(?:ly)?|outage|breach|exploit(?:ed|ation)?|"
    r"compromise[ds]?|attack|critical\s+vulnerability|zero[-\s]day|data\s+loss)\b",
    re.IGNORECASE,
)

PROPER_NOUN_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9&.\-]+)(?:\s+[A-Z][a-zA-Z0-9&.\-]+){0,3}\b")


@dataclass
class KnowledgeBundle:
    summary: str = ""
    subject: str = ""
    topics: list[str] = field(default_factory=list)
    key_facts: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    indicators: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    detected_objective: str = "inform"
    reading_level: str = "technical"
    build_mode: str = "deterministic"
    sentences: list[str] = field(default_factory=list)
    section_signals: dict[str, list[str]] = field(default_factory=dict)
    risk_markers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "subject": self.subject,
            "topics": self.topics,
            "key_facts": self.key_facts,
            "entities": self.entities,
            "indicators": self.indicators,
            "dates": self.dates,
            "figures": self.figures,
            "detected_objective": self.detected_objective,
            "reading_level": self.reading_level,
            "build_mode": self.build_mode,
        }


def _score_sentences(sentences: list[str], idf: dict[str, float], max_idf: float) -> list[float]:
    """Centroid + position weighted scoring (TextRank-lite, deterministic)."""
    if not sentences:
        return []
    token_sets = [set(content_tokens(s)) for s in sentences]
    scores: list[float] = []
    for i, tokens in enumerate(token_sets):
        if not tokens:
            scores.append(0.0)
            continue
        weight = sum(idf.get(t, max_idf) for t in tokens) / (len(tokens) ** 0.5)
        length_penalty = 1.0 if 8 <= len(sentences[i].split()) <= 45 else 0.72
        position_bonus = 1.22 if i == 0 else (1.10 if i < 3 else 1.0)
        scores.append(weight * length_penalty * position_bonus)
    return scores


def _classify_sentence(sentence: str) -> str:
    if ACTION_VERBS.search(sentence):
        return "recommendation"
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|percent)\b", sentence, re.IGNORECASE):
        return "impact"
    if re.search(r"\b(?:is|are|was|were|has|have|had)\b", sentence, re.IGNORECASE) and NUMBER_RE.search(sentence):
        return "finding"
    if re.search(r"\b(?:reported|detected|observed|discovered|identified|confirmed)\b", sentence, re.IGNORECASE):
        return "finding"
    if DATE_RE.search(sentence):
        return "timeline"
    if re.search(r"\b(?:this (?:document|report|advisory|note)|the following|we (?:find|conclude))\b", sentence, re.IGNORECASE):
        return "finding"
    return "context"


def _heading_set(text: str) -> set[str]:
    from .textutils import heading_of

    return {
        h.lower()
        for line in text.split("\n")
        if (h := heading_of(line)) is not None
    }


def _extract_entities(
    sentences: list[str],
    headings: set[str],
    indicators: list[str],
    subject: str = "",
    limit: int = 18,
) -> list[dict[str, Any]]:
    from collections import Counter

    subject_key = re.sub(r"\W+", " ", subject.lower()).strip()
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for sentence in sentences:
        for candidate in PROPER_NOUN_RE.findall(sentence):
            cleaned = candidate.strip(" .,-")
            words = cleaned.split()
            while words and words[0].lower() in STOPWORDS:
                words.pop(0)
            while words and words[-1].lower() in STOPWORDS:
                words.pop()
            if not words or len(words) > 4:
                continue
            key = " ".join(words)
            lower = key.lower()
            if lower in STOPWORDS or len(key) < 3:
                continue
            if lower in headings or lower in NON_ENTITY_WORDS or lower in MONTHS:
                continue
            if subject_key and lower == subject_key:
                continue
            if any(lower in indicator.lower() or indicator.lower() in lower for indicator in indicators):
                continue
            counts[key] += 1
            first_seen.setdefault(key, safe_snippet(sentence, 160))

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    entities: list[dict[str, Any]] = []
    seen_lower: set[str] = set()
    for name, freq in ranked:
        lower = name.lower()
        if lower in seen_lower or any(lower in existing for existing in seen_lower):
            continue
        # A single mention of a single common word is usually just capitalisation,
        # not an entity. Multi-word names, acronyms and repeated names survive.
        is_acronym = name.isupper() and len(name) >= 2
        if " " not in name and freq < 2 and not is_acronym:
            continue
        seen_lower.add(lower)
        kind = (
            "document"
            if TITLE_SIGNALS.search(name) or (subject_key and lower in subject_key)
            else (
                "organisation"
                if re.search(
                    r"\b(inc|ltd|llp|corp|corporation|group|university|ministry|department|agency|"
                    r"bank|committee|authority|centre|center|institute)\b",
                    name,
                    re.IGNORECASE,
                )
                else (
                    "product"
                    if re.search(
                        r"\b(api|platform|system|software|service|tool|framework|portal|gateway)\b",
                        name,
                        re.IGNORECASE,
                    )
                    else "term"
                )
            )
        )
        entities.append(
            {
                "name": title_case_heading(name),
                "mentions": freq,
                "kind": kind,
                "context": first_seen[name],
            }
        )
        if len(entities) >= limit:
            break
    return entities


def _guess_objective(text: str, section_signals: dict[str, list[str]]) -> str:
    lowered = text[:6000].lower()
    if section_signals.get("recommendation"):
        return "advise"
    if re.search(r"\b(immediately|urgent|critical|asap|escalate|without\s+delay|within \d+ hours?)\b", lowered):
        return "escalate"
    if re.search(r"\b(we (?:find|conclude)|findings?\b|analysis\s+shows|assessment\s+of|this\s+(?:paper|assessment))\b", lowered):
        return "report"
    if re.search(r"\b(educat\w+|public\s+awareness|awareness\s+campaign|outreach|"
                 r"explain\s+to\s+(?:the\s+)?(?:public|students?|staff))\b", lowered):
        return "awareness"
    return "inform"


def _guess_reading_level(sentences: list[str]) -> str:
    if not sentences:
        return "general"
    words = [w for s in sentences for w in tokenize(s)]
    if not words:
        return "general"
    long_words = sum(1 for w in words if len(w) >= 9)
    ratio = long_words / len(words)
    return "technical" if ratio > 0.09 else "general"


def _guess_subject(text: str, entities: list[dict[str, Any]]) -> str:
    first_block = "\n".join(text.split("\n")[:12]).strip()
    for line in first_block.split("\n"):
        stripped = strip_bullet(line)
        if TITLE_SIGNALS.search(stripped) and 12 <= len(stripped) <= 220:
            return stripped
    for line in first_block.split("\n"):
        stripped = strip_bullet(line)
        words = stripped.split()
        if 3 <= len(words) <= 18 and not stripped.endswith("."):
            return stripped
    if entities:
        return entities[0]["name"]
    return safe_snippet(text, 120) or "Untitled source"


LIST_NUMBER_RE = re.compile(r"^\d+[.)]?$")
MEASURE_RE = re.compile(r"(?:%|percent|x\b|million|billion|thousand|hours?|days?|minutes?|accounts?|users?|requests?)", re.IGNORECASE)


SUPPRESSION_TOKEN = "[UNTRUSTED_INSTRUCTION_SUPPRESSED]"


def _is_noise(sentence: str, headings: set[str]) -> bool:
    """Reject text that must never become a fact or reach a generated artefact."""
    stripped = sentence.strip()
    if not stripped:
        return True
    if stripped == SUPPRESSION_TOKEN:
        return True
    key = re.sub(r"\W+", " ", stripped.lower()).strip()
    if key in headings:
        return True
    # Too short to carry meaning and without a number to justify it.
    return len(stripped) < 25 and not re.search(r"\d", stripped)


def _clean_figures(text: str, indicators: list[str]) -> list[str]:
    """Numeric highlights worth surfacing - not every digit run in the document."""
    figures: list[str] = []
    for raw in NUMBER_RE.findall(text):
        value = raw.strip().rstrip(".").strip()
        if not value or value in figures:
            continue
        digits = re.sub(r"\D", "", value)
        # Skip list numbering ("1.", "2.") and bare 1-2 digit counts; both are
        # noise in a figure list and one of them is how invented stats sneak in.
        if LIST_NUMBER_RE.match(value) or len(digits) < 3:
            continue
        # Skip fragments of identifiers (CVE-2026-21887, 45.77.201.19).
        if any(value in indicator or indicator in value for indicator in indicators):
            continue
        figures.append(value)
    figures.sort(key=lambda v: (-len(re.sub(r"\D", "", v)), v))
    return figures[:25]


def build_knowledge(text: str, max_facts: int = 16) -> KnowledgeBundle:
    text = normalise_whitespace(text)
    sentences = split_sentences(text)
    idf = idf_scores(sentences)
    max_idf = max(idf.values()) if idf else 1.0
    scores = _score_sentences(sentences, idf, max_idf)

    bundle = KnowledgeBundle(sentences=sentences)
    headings = _heading_set(text)

    # Topics: highest aggregate IDF mass.
    topic_scores: dict[str, float] = {}
    for sentence, score in zip(sentences, scores, strict=False):
        for token in set(content_tokens(sentence)):
            topic_scores[token] = topic_scores.get(token, 0.0) + score * (idf.get(token, max_idf) / max_idf)
    bundle.topics = [
        term for term, _ in sorted(topic_scores.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    ]

    indicators: list[str] = []
    for pattern in INDICATOR_PATTERNS:
        for found in pattern.findall(text):
            value = found if isinstance(found, str) else found[0]
            if value not in indicators:
                indicators.append(value)
    bundle.indicators = indicators[:25]

    dates: list[str] = []
    for found in DATE_RE.findall(text):
        value = found.strip()
        if value and value not in dates:
            dates.append(value)
    bundle.dates = dates[:20]
    bundle.figures = _clean_figures(text, bundle.indicators)

    # The document title is metadata, not a finding: keeping it in the fact list
    # would repeat it in every generated artefact.
    subject = _guess_subject(text, [])
    subject_key = re.sub(r"\W+", " ", subject.lower()).strip()

    def is_title_line(sentence: str) -> bool:
        key = re.sub(r"\W+", " ", sentence.lower()).strip()
        return bool(subject_key) and (key.startswith(subject_key) or subject_key.startswith(key))

    usable = [
        (index, score)
        for index, score in enumerate(scores)
        if score > 0
        and not is_title_line(sentences[index])
        and not _is_noise(sentences[index], headings)
    ]

    # Summary: top sentences, kept in document order.
    top_indices = sorted(sorted(usable, key=lambda pair: pair[1], reverse=True)[:6])
    summary_sentences = [sentences[i] for i, _ in top_indices]
    bundle.summary = " ".join(truncate_words(s, 34) for s in summary_sentences)

    # Key facts with categories and evidence pointers.
    candidates = sorted(usable, key=lambda pair: pair[1], reverse=True)[: max_facts * 3]
    ordered = sorted(index for index, _ in candidates[:max_facts])
    seen_facts: set[str] = set()
    for i in ordered:
        sentence = sentences[i]
        signature = re.sub(r"\W+", " ", sentence.lower()).strip()[:90]
        if signature in seen_facts:
            continue
        seen_facts.add(signature)
        category = _classify_sentence(sentence)
        bundle.key_facts.append(
            {
                "text": safe_snippet(sentence, 320),
                "category": category,
                "score": round(scores[i], 4),
                "position": i,
                "has_number": bool(NUMBER_RE.search(sentence)),
            }
        )
    for category, pattern in SECTION_SIGNALS.items():
        matches = [safe_snippet(s, 260) for s in sentences if pattern.search(s)][:4]
        if matches:
            bundle.section_signals[category] = matches

    bundle.entities = _extract_entities(sentences, headings, bundle.indicators, subject)
    bundle.subject = subject

    bundle.risk_markers = [safe_snippet(s, 200) for s in sentences if RISK_WORDS.search(s)][:6]
    bundle.detected_objective = _guess_objective(text, bundle.section_signals)
    bundle.reading_level = _guess_reading_level(sentences)
    return bundle



def evidence_sentences(bundle: KnowledgeBundle, limit: int = 8) -> list[str]:
    return [fact["text"] for fact in bundle.key_facts[:limit]]
