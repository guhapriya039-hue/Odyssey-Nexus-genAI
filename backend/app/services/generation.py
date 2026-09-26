"""Output generation for every supported communication format.

Two engines behind one interface:

* **LLM engine** - source-grounded prompting of the configured model chain.
* **Extractive engine** - a deterministic composer driven by a per-format
  section spec. It needs no model and no network, which is what lets the
  platform demo end-to-end (and stay inside an air-gapped private deployment)
  while still producing structured, source-faithful artefacts.

Both engines read from the *same* knowledge bundle and the *same* retrieved
evidence, so all formats stay consistent with each other and with the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..constants import (
    AUDIENCE_LABELS,
    DETAIL_LABELS,
    LANGUAGES,
    OBJECTIVE_LABELS,
    TONE_LABELS,
    DetailLevel,
    OutputFormat,
)
from .knowledge import KnowledgeBundle
from .llm import LLMClient
from .prompts import build_prompt
from .retrieval import RetrievedChunk
from .textutils import safe_snippet, split_sentences, truncate_words

DETAIL_MULTIPLIER = {
    DetailLevel.BRIEF: 0.6,
    DetailLevel.BALANCED: 1.0,
    DetailLevel.COMPREHENSIVE: 1.5,
}

LANGUAGE_DIRECTIVE = {
    "en": "Write in English.",
    "hi": "लिखिए हिन्दी में। (Write in Hindi, using Devanagari script.)",
    "ta": "தமிழில் எழுதவும். (Write in Tamil.)",
    "te": "తెలుగులో రాయండి. (Write in Telugu.)",
    "kn": "ಕನ್ನಡದಲ್ಲಿ ಬರೆಯಿರಿ. (Write in Kannada.)",
    "ml": "മലയാളത്തിൽ എഴുതുക. (Write in Malayalam.)",
    "bn": "বাংলায় লিখুন। (Write in Bengali.)",
    "mr": "मराठीत लिहा. (Write in Marathi.)",
    "gu": "ગુજરાતીમાં લખો. (Write in Gujarati.)",
    "es": "Escribe en español. (Write in Spanish.)",
    "fr": "Rédigez en français. (Write in French.)",
    "de": "Schreibe auf Deutsch. (Write in German.)",
    "ar": "اكتب بالعربية. (Write in Arabic.)",
    "zh": "请用中文撰写。 (Write in Chinese.)",
    "ja": "日本語で書いてください。 (Write in Japanese.)",
}


@dataclass
class SectionSpec:
    key: str
    label: str | None
    style: str = "paragraph"      # paragraph | bullets | numbered | stats | timeline | note
    source: str = "summary"       # knowledge field selector
    limit: int = 4
    max_words: int = 30


@dataclass
class FormatSpec:
    format: str
    title_template: str
    sections: list[SectionSpec]
    char_budget: int = 20_000
    footer: str | None = None


@dataclass
class GeneratedOutput:
    format: str
    title: str
    body: str
    section_map: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "extractive"
    model: str = "offline-extractive"
    warnings: list[str] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)


FORMAT_SPECS: dict[str, FormatSpec] = {
    OutputFormat.EXECUTIVE_SUMMARY: FormatSpec(
        format=OutputFormat.EXECUTIVE_SUMMARY,
        title_template="{subject} - Executive Summary",
        sections=[
            SectionSpec("situation", "Situation", "paragraph", "summary", 3, 34),
            SectionSpec("why_it_matters", "Why it matters", "paragraph", "impact", 2, 30),
            SectionSpec("key_points", "Key points", "bullets", "facts", 5, 24),
            SectionSpec("action", "Decision / action required", "numbered", "recommendation", 3, 26),
            SectionSpec("confidence", "Confidence", "note", "confidence", 1, 26),
        ],
        char_budget=2_600,
        footer="Prepared by ODYSSEY TRANSFORM CORE from a single verified source. Not stated in source = absent from the source.",
    ),
    OutputFormat.ADVISORY: FormatSpec(
        format=OutputFormat.ADVISORY,
        title_template="{subject} - Advisory",
        sections=[
            SectionSpec("classification", None, "note", "classification", 1, 24),
            SectionSpec("summary", "Summary", "paragraph", "summary", 3, 36),
            SectionSpec("context", "Context and background", "paragraph", "context", 3, 34),
            SectionSpec("findings", "Key findings", "numbered", "finding", 6, 32),
            SectionSpec("impact", "Impact assessment", "bullets", "impact", 4, 30),
            SectionSpec("actions", "Recommended actions", "numbered", "recommendation", 6, 30),
            SectionSpec("indicators", "Indicators / artefacts of interest", "bullets", "indicators", 6, 24),
            SectionSpec("caveats", "Caveats and limitations", "bullets", "caveats", 3, 28),
        ],
        char_budget=6_500,
        footer="Source: {source}. Generated from verified source evidence; no external information was added.",
    ),
    OutputFormat.LINKEDIN: FormatSpec(
        format=OutputFormat.LINKEDIN,
        title_template="{subject} - LinkedIn post",
        sections=[
            SectionSpec("hook", None, "paragraph", "hook", 2, 26),
            SectionSpec("body", None, "paragraph", "facts", 4, 30),
            SectionSpec("takeaway", None, "paragraph", "recommendation", 1, 26),
            SectionSpec("hashtags", None, "note", "hashtags", 1, 12),
        ],
        char_budget=1_400,
    ),
    OutputFormat.X_POST: FormatSpec(
        format=OutputFormat.X_POST,
        title_template="{subject} - X post",
        sections=[SectionSpec("post", None, "paragraph", "compact", 2, 26)],
        char_budget=270,
    ),
    OutputFormat.INFOGRAPHIC: FormatSpec(
        format=OutputFormat.INFOGRAPHIC,
        title_template="{subject} - Infographic content",
        sections=[SectionSpec("panels", None, "panels", "facts", 6, 20)],
        char_budget=3_000,
        footer="Source: {source}",
    ),
    OutputFormat.PRESENTATION: FormatSpec(
        format=OutputFormat.PRESENTATION,
        title_template="{subject} - Presentation deck",
        sections=[
            SectionSpec("title_slide", None, "note", "title_slide", 1, 18),
            SectionSpec("situation_slide", "Situation", "bullets", "summary", 3, 14),
            SectionSpec("findings_slide", "Key findings", "bullets", "finding", 4, 14),
            SectionSpec("impact_slide", "Impact", "bullets", "impact", 3, 14),
            SectionSpec("action_slide", "Recommended actions", "bullets", "recommendation", 4, 14),
            SectionSpec("indicators_slide", "Indicators", "bullets", "indicators", 4, 12),
            SectionSpec("takeaways", "Key takeaways", "bullets", "takeaways", 3, 16),
        ],
        char_budget=5_000,
        footer="Generated by ODYSSEY TRANSFORM CORE. Every bullet traces to the source document.",
    ),
    OutputFormat.VIDEO_SCRIPT: FormatSpec(
        format=OutputFormat.VIDEO_SCRIPT,
        title_template="{subject} - Video script",
        sections=[
            SectionSpec("scenes", None, "scenes", "facts", 6, 34),
        ],
        char_budget=4_200,
        footer="Total narration: approximately {seconds} seconds.",
    ),
    OutputFormat.STORYBOARD: FormatSpec(
        format=OutputFormat.STORYBOARD,
        title_template="{subject} - Storyboard",
        sections=[SectionSpec("frames", None, "frames", "facts", 9, 26)],
        char_budget=4_200,
    ),
    OutputFormat.NARRATION_SUBTITLES: FormatSpec(
        format=OutputFormat.NARRATION_SUBTITLES,
        title_template="{subject} - Narration and subtitles",
        sections=[
            SectionSpec("narration", "NARRATION", "paragraph", "facts", 6, 30),
            SectionSpec("subtitles", "SUBTITLES", "subtitles", "facts", 8, 8),
        ],
        char_budget=3_400,
    ),
}


# ---------------------------------------------------------------------------
# Source selectors
# ---------------------------------------------------------------------------


def _facts(bundle: KnowledgeBundle, category: str, limit: int) -> list[str]:
    wanted = {
        "impact": {"impact"},
        "recommendation": {"recommendation"},
        "finding": {"finding"},
        "timeline": {"timeline"},
        "context": {"context"},
    }.get(category, {category})
    matched = [f["text"] for f in bundle.key_facts if f["category"] in wanted]
    if len(matched) < max(2, limit // 2):
        for fact in bundle.key_facts:
            if fact["category"] not in wanted and fact["text"] not in matched:
                matched.append(fact["text"])
    return matched[:limit]


def select(bundle: KnowledgeBundle, source: str, limit: int) -> list[str]:
    if source == "summary":
        sentences = split_sentences(bundle.summary)
        return sentences[:limit] or [safe_snippet(bundle.summary, 240)]
    if source in {"impact", "recommendation", "finding", "timeline", "context"}:
        return _facts(bundle, source, limit)
    if source == "facts":
        return [f["text"] for f in bundle.key_facts][:limit]
    if source == "risks":
        return bundle.risk_markers[:limit] or ["No risk-specific statement was found in the source."]
    if source == "indicators":
        return bundle.indicators[:limit] or []
    if source == "entities":
        return [e["name"] for e in bundle.entities][:limit]
    if source == "takeaways":
        picks = [f["text"] for f in bundle.key_facts[:limit]]
        return picks or ["Not stated in source"]
    if source == "hashtags":
        tags = []
        for topic in bundle.topics[:4]:
            cleaned = re.sub(r"[^A-Za-z0-9]", "", topic.title())
            if cleaned and cleaned.lower() not in {"the", "and", "for"}:
                tags.append(f"#{cleaned}")
        return [" ".join(tags)] if tags else []
    if source == "classification":
        return [
            f"Reference: TRF-based advisory generated from the source below | "
            f"Handling: derived from {'a public' if bundle.reading_level == 'general' else 'a restricted'} source"
        ]
    if source == "caveats":
        caveats = ["This advisory reflects only what the source states; it does not add external context."]
        if not bundle.indicators:
            caveats.append("The source contains no machine-readable indicators, so none are listed.")
        if not bundle.dates:
            caveats.append("The source states no explicit dates; timing should be confirmed separately.")
        return caveats[:limit]
    if source == "confidence":
        marker = "the source is explicit and quantitative" if bundle.figures else "the source is narrative and partial"
        return [f"Confidence: {'Medium' if bundle.figures else 'Low'} - {marker}."[:240]]
    if source == "hook":
        facts = [f["text"] for f in bundle.key_facts[:2]]
        return [truncate_words(f, 22) for f in facts] or [safe_snippet(bundle.summary, 120)]
    if source == "compact":
        facts = [f["text"] for f in bundle.key_facts[:2]]
        return [truncate_words(f, 24) for f in facts]
    if source == "title_slide":
        return [bundle.subject or "Untitled source"]
    if source == "panels" or source == "scenes" or source == "frames":
        return [f["text"] for f in bundle.key_facts][:limit]
    return [safe_snippet(bundle.summary, 240)]


# ---------------------------------------------------------------------------
# Extractive composer
# ---------------------------------------------------------------------------

SHOT_TYPES = ("wide", "medium", "close-up", "over-the-shoulder", "motion graphic", "b-roll")
VISUALS = (
    "Context establishing shot with source document on screen",
    "Key statistic revealed as motion graphic",
    "Diagram of the affected system or process",
    "Comparison view: before and after",
    "Map or timeline of the event sequence",
    "Action checklist animating in",
    "Closing title card with the core takeaway",
)


def _panel_stat(panel_text: str, figures: list[str]) -> str:
    """Only report a statistic the panel itself states.

    Falling back to "the next unused figure in the document" would attach an
    unrelated number to a panel - precisely the hallucination this platform
    exists to prevent.
    """
    for figure in figures:
        if figure in panel_text:
            return f"{figure} (as stated in source)"
    return "Not stated in source"


def _scale(limit: int, detail: str) -> int:
    multiplier = DETAIL_MULTIPLIER.get(detail, 1.0)
    return max(1, round(limit * multiplier))


def _fit(text: str, budget: int) -> str:
    text = text.strip()
    if len(text) <= budget:
        return text
    clipped = text[: max(0, budget - 1)]
    if " " in clipped:
        clipped = clipped[: clipped.rfind(" ")]
    return clipped.rstrip(" ,;:-") + "…"


def compose(
    spec: FormatSpec,
    bundle: KnowledgeBundle,
    config: dict[str, Any],
) -> GeneratedOutput:
    detail = config.get("detail", DetailLevel.BALANCED)
    source_title = config.get("source_title") or bundle.subject or "source document"
    title = spec.title_template.format(subject=bundle.subject or "Untitled source")

    blocks: list[str] = [f"# {title}"]
    section_map: list[dict[str, Any]] = []
    words_total = 0

    for section in spec.sections:
        limit = _scale(section.limit, detail)
        items = select(bundle, section.source, limit)
        items = [truncate_words(item, section.max_words) for item in items if item.strip()]
        if not items and section.style not in {"note"}:
            items = ["Not stated in source"]

        body_lines: list[str] = []
        if section.style == "bullets":
            body_lines = [f"- {item}" for item in items]
        elif section.style == "numbered":
            body_lines = [f"{i}. {item}" for i, item in enumerate(items, start=1)]
        elif section.style == "panels":
            for index, item in enumerate(items, start=1):
                headline = truncate_words(item, 9)
                body = truncate_words(item, 16)
                body_lines += [
                    f"[Panel {index}] {headline}",
                    f"Stat: {_panel_stat(item, bundle.figures)}",
                    f"Body: {body}",
                    "",
                ]
        elif section.style == "scenes":
            for index, item in enumerate(items, start=1):
                seconds = 10 + (index % 4) * 4
                body_lines += [
                    f"[Scene {index} | {VISUALS[(index - 1) % len(VISUALS)]} | ~{seconds}s]",
                    f"Narration: {item}",
                    f"On-screen text: {truncate_words(item, 6)}",
                    "",
                ]
        elif section.style == "frames":
            for index, item in enumerate(items, start=1):
                shot = SHOT_TYPES[(index - 1) % len(SHOT_TYPES)]
                body_lines += [
                    f"[Frame {index} | {shot} | {VISUALS[(index - 1) % len(VISUALS)]}]",
                    f"Body: {item}",
                    "",
                ]
            takeaway = bundle.summary or "Not stated in source"
            body_lines.append(f"[End card] On-screen text: {truncate_words(takeaway, 8)}")
        elif section.style == "subtitles":
            for index, item in enumerate(items, start=1):
                cue = truncate_words(item, 11)
                body_lines.append(f"{index}. {cue}")
        else:
            body_lines = list(items)

        section_text = "\n".join(body_lines).strip()
        if not section_text:
            continue

        if section.label:
            blocks.append(f"## {section.label}\n{section_text}")
        else:
            blocks.append(section_text)

        words_total += len(section_text.split())
        section_map.append(
            {
                "key": section.key,
                "label": section.label or section.key.replace("_", " ").title(),
                "style": section.style,
                "items": items,
                "char_count": len(section_text),
            }
        )

    if spec.footer:
        seconds = max(45, int(words_total / 2.4))
        blocks.append("---")
        blocks.append(spec.footer.format(source=source_title, seconds=seconds))

    body = _fit("\n\n".join(blocks), spec.char_budget)
    return GeneratedOutput(
        format=spec.format,
        title=title,
        body=body,
        section_map=section_map,
        mode="extractive",
        model="offline-extractive-v1",
    )


# ---------------------------------------------------------------------------
# LLM composer
# ---------------------------------------------------------------------------

FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n|\n```\s*$")


def clean_llm_text(text: str) -> str:
    cleaned = FENCE_RE.sub("", text.strip())
    cleaned = re.sub(r"^(?:here (?:is|are)|sure[,!]?|certainly[,!]?)[^\n:]{0,80}:\s*\n+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def build_section_map_from_llm(body: str) -> list[dict[str, Any]]:
    section_map: list[dict[str, Any]] = []
    current = "body"
    buffer: list[str] = []
    for line in body.split("\n"):
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line) or re.match(
            r"^\s*(?:\d+\.\s*)?([A-Z][A-Za-z /&]{3,48}):\s*$", line
        )
        if heading:
            if buffer:
                section_map.append(
                    {
                        "key": re.sub(r"\W+", "_", current.lower()).strip("_"),
                        "label": current,
                        "style": "paragraph",
                        "items": [b for b in buffer if b.strip()],
                        "char_count": len("\n".join(buffer)),
                    }
                )
            current = heading.group(1).strip()
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        section_map.append(
            {
                "key": re.sub(r"\W+", "_", current.lower()).strip("_"),
                "label": current,
                "style": "paragraph",
                "items": [b for b in buffer if b.strip()],
                "char_count": len("\n".join(buffer)),
            }
        )
    return section_map


def generate_with_llm(
    output_format: str,
    config: dict[str, Any],
    bundle: KnowledgeBundle,
    evidence: list[RetrievedChunk],
    client: LLMClient,
) -> GeneratedOutput | None:
    system, user = build_prompt(
        output_format=output_format,
        audience=config.get("audience", "executive"),
        tone=config.get("tone", "neutral"),
        language=config.get("language", "en"),
        objective=config.get("objective", "inform"),
        detail=config.get("detail", DetailLevel.BALANCED),
        bundle=bundle,
        evidence=evidence,
        user_instruction=config.get("user_instruction", ""),
    )
    directive = LANGUAGE_DIRECTIVE.get(config.get("language", "en"), "")
    if directive and config.get("language") != "en":
        system = f"{system}\n{directive}"

    result = client.complete(system, user)
    if result is None or not result.text.strip():
        return None

    body = clean_llm_text(result.text)
    if not body:
        return None

    spec = FORMAT_SPECS.get(output_format)
    title = f"{bundle.subject or 'Untitled source'} - {output_format.replace('_', ' ').title()}"
    if body.lstrip().startswith("#"):
        first_line = body.lstrip().split("\n", 1)[0].lstrip("# ").strip()
        if first_line:
            title = truncate_words(first_line, 14)

    warnings: list[str] = []
    if spec and len(body) > spec.char_budget * 1.6:
        warnings.append(f"Model output exceeded the expected length for {output_format}.")

    return GeneratedOutput(
        format=output_format,
        title=title[:380],
        body=body,
        section_map=build_section_map_from_llm(body),
        mode="llm",
        model=result.model,
        warnings=warnings,
        attempts=result.attempts,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate(
    output_format: str,
    config: dict[str, Any],
    bundle: KnowledgeBundle,
    evidence: list[RetrievedChunk],
    client: LLMClient,
    allow_llm: bool = True,
) -> tuple[GeneratedOutput, str]:
    """Return ``(output, engine_used)``; falls back to the extractive engine."""
    spec = FORMAT_SPECS.get(output_format)
    if spec is None:
        raise ValueError(f"Unsupported output format '{output_format}'")

    if allow_llm and client.configured:
        generated = generate_with_llm(output_format, config, bundle, evidence, client)
        if generated is not None:
            return generated, "llm"

    return compose(spec, bundle, config), "extractive"


def config_summary(config: dict[str, Any]) -> str:
    return (
        f"{AUDIENCE_LABELS.get(config.get('audience', ''), config.get('audience'))} | "
        f"{TONE_LABELS.get(config.get('tone', ''), config.get('tone'))} | "
        f"{LANGUAGES.get(config.get('language', ''), config.get('language'))} | "
        f"{OBJECTIVE_LABELS.get(config.get('objective', ''), config.get('objective'))} | "
        f"{DETAIL_LABELS.get(config.get('detail', ''), config.get('detail'))}"
    )
