"""Domain vocabulary: output formats, communication controls, RBAC.

Keeping these as plain string constants (instead of DB enums) keeps the
schemas JSON-serialisable for the dashboard and the audit trail.
"""

from __future__ import annotations

from enum import StrEnum


class OutputFormat(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    ADVISORY = "advisory"
    LINKEDIN = "linkedin"
    X_POST = "x_post"
    INFOGRAPHIC = "infographic"
    PRESENTATION = "presentation"
    VIDEO_SCRIPT = "video_script"
    STORYBOARD = "storyboard"
    NARRATION_SUBTITLES = "narration_subtitles"


FORMAT_LABELS: dict[str, str] = {
    OutputFormat.EXECUTIVE_SUMMARY: "Executive Summary",
    OutputFormat.ADVISORY: "Structured Advisory",
    OutputFormat.LINKEDIN: "LinkedIn Post",
    OutputFormat.X_POST: "X / Twitter Post",
    OutputFormat.INFOGRAPHIC: "Infographic Content",
    OutputFormat.PRESENTATION: "Presentation Deck",
    OutputFormat.VIDEO_SCRIPT: "Video Script",
    OutputFormat.STORYBOARD: "Storyboard",
    OutputFormat.NARRATION_SUBTITLES: "Narration & Subtitles",
}

FORMAT_MEDIA: dict[str, str] = {
    OutputFormat.EXECUTIVE_SUMMARY: "document",
    OutputFormat.ADVISORY: "document",
    OutputFormat.LINKEDIN: "social",
    OutputFormat.X_POST: "social",
    OutputFormat.INFOGRAPHIC: "visual",
    OutputFormat.PRESENTATION: "slides",
    OutputFormat.VIDEO_SCRIPT: "video",
    OutputFormat.STORYBOARD: "visual",
    OutputFormat.NARRATION_SUBTITLES: "video",
}


class Tone(StrEnum):
    FORMAL = "formal"
    ANALYTICAL = "analytical"
    NEUTRAL = "neutral"
    PERSUASIVE = "persuasive"
    URGENT = "urgent"
    EDUCATIONAL = "educational"


TONE_LABELS: dict[str, str] = {
    Tone.FORMAL: "Formal",
    Tone.ANALYTICAL: "Analytical",
    Tone.NEUTRAL: "Neutral",
    Tone.PERSUASIVE: "Persuasive",
    Tone.URGENT: "Urgent",
    Tone.EDUCATIONAL: "Educational",
}


class Objective(StrEnum):
    INFORM = "inform"
    BRIEF = "brief"
    ADVISE = "advise"
    AWARENESS = "awareness"
    REPORT = "report"
    ESCALATE = "escalate"
    EDUCATE = "educate"


OBJECTIVE_LABELS: dict[str, str] = {
    Objective.INFORM: "Inform",
    Objective.BRIEF: "Brief",
    Objective.ADVISE: "Advise action",
    Objective.AWARENESS: "Build awareness",
    Objective.REPORT: "Report findings",
    Objective.ESCALATE: "Escalate concern",
    Objective.EDUCATE: "Educate",
}


class DetailLevel(StrEnum):
    BRIEF = "brief"
    BALANCED = "balanced"
    COMPREHENSIVE = "comprehensive"


DETAIL_LABELS: dict[str, str] = {
    DetailLevel.BRIEF: "Brief",
    DetailLevel.BALANCED: "Balanced",
    DetailLevel.COMPREHENSIVE: "Comprehensive",
}


class Audience(StrEnum):
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    OPERATIONS = "operations"
    SECURITY_ANALYST = "security_analyst"
    MEDIA_PUBLIC = "media_public"
    PARTNER = "partner"


AUDIENCE_LABELS: dict[str, str] = {
    Audience.EXECUTIVE: "Executive leadership",
    Audience.TECHNICAL: "Technical team",
    Audience.OPERATIONS: "Operations team",
    Audience.SECURITY_ANALYST: "Security analyst",
    Audience.MEDIA_PUBLIC: "Media & public",
    Audience.PARTNER: "Partner organisation",
}

AUDIENCE_GUIDANCE: dict[str, str] = {
    Audience.EXECUTIVE: (
        "Decision-makers with limited time. Lead with impact, decisions required and risk. "
        "Avoid technical jargon; expand any unavoidable acronym."
    ),
    Audience.TECHNICAL: (
        "Engineers and analysts. Keep precise terminology, indicators, artefacts and version detail. "
        "Include enough evidence to reproduce findings."
    ),
    Audience.OPERATIONS: (
        "Operational teams who must act. Emphasise sequence of actions, owners, dependencies and rollback."
    ),
    Audience.SECURITY_ANALYST: (
        "Threat-intelligence readers. Preserve IOCs, CVEs, confidence levels, attribution caveats and TTP language."
    ),
    Audience.MEDIA_PUBLIC: (
        "General audience. Plain language, no jargon, no sensitive technical identifiers or personal data."
    ),
    Audience.PARTNER: (
        "External partner. Share only what is safe to disclose; avoid internal-only detail and raw indicators."
    ),
}


LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ar": "Arabic",
    "zh": "Chinese (Mandarin)",
    "ja": "Japanese",
}


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    INDEXED = "indexed"
    REJECTED = "rejected"
    FAILED = "failed"


class TransformationStatus(StrEnum):
    QUEUED = "queued"
    ANALYSING = "analysing"
    GENERATING = "generating"
    VALIDATING = "validating"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    BLOCKED = "blocked"
    FAILED = "failed"


class ReviewState(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


RISK_ORDER: dict[str, int] = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


def max_risk(levels: list[str]) -> str:
    if not levels:
        return RiskLevel.NONE
    return max(levels, key=lambda level: RISK_ORDER.get(level, 0))


# ---- RBAC -------------------------------------------------------------

class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    APPROVER = "approver"
    ADMIN = "admin"


ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.VIEWER: {"document:read", "output:read", "audit:read"},
    Role.ANALYST: {
        "document:read",
        "document:write",
        "output:read",
        "output:write",
        "transform:run",
        "audit:read",
    },
    Role.APPROVER: {
        "document:read",
        "output:read",
        "output:write",
        "output:approve",
        "transform:run",
        "audit:read",
    },
    Role.ADMIN: {
        "document:read",
        "document:write",
        "output:read",
        "output:write",
        "output:approve",
        "transform:run",
        "audit:read",
        "system:admin",
    },
}

DEMO_ACTORS: dict[str, str] = {
    "analyst": "analyst@odyssey.team",
    "approver": "approver@odyssey.team",
    "viewer": "viewer@odyssey.team",
    "admin": "admin@odyssey.team",
}
