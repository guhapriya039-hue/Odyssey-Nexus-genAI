"""Security layer: prompt-injection detection, PII detection and redaction.

Two independent jobs, both applied *before* any text reaches a model:

1. ``scan_text``     – classify risk, produce findings for the dashboard.
2. ``sanitise``      – return text that is safe to embed inside a prompt.
   Untrusted content is wrapped in a fenced data block and instruction-like
   lines are neutralised, so the model treats it as data rather than orders.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ..constants import RiskLevel, max_risk
from .textutils import normalise_whitespace

# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: tuple[tuple[str, str, float], ...] = (
    ("instruction_override", r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
                             r"(?:instructions?|prompts?|rules?|directions?)", 0.85),
    ("instruction_override", r"disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|"
                             r"earlier|system)\s+(?:instructions?|prompts?|rules?)", 0.85),
    ("system_prompt_probe", r"(?:reveal|show|print|repeat|output|display|dump)\s+(?:me\s+)?"
                            r"(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?|rules?)", 0.8),
    ("role_hijack", r"you\s+are\s+now\s+(?:a|an|the)?\s*[a-z ]{0,40}(?:mode|assistant|dan|jailbroken)", 0.75),
    ("persona_override", r"act\s+as\s+(?:if\s+you\s+are\s+)?(?:a|an|the)?\s*[a-z ]{0,30}"
                         r"(?:without\s+restrictions?|unfiltered|unrestricted)", 0.75),
    ("guardrail_bypass", r"(?:bypass|disable|turn\s+off|remove|circumvent|evade)\s+"
                         r"(?:your\s+|all\s+|the\s+)?(?:safety|guard\s?rails?|filters?|"
                         r"restrictions?|moderation|alignment)", 0.9),
    ("guardrail_bypass", r"developer\s+mode|god\s+mode|dan\s+mode|jailbreak", 0.8),
    ("exfiltration", r"(?:send|post|upload|exfiltrate|transmit|leak)\s+(?:the\s+|all\s+|your\s+)?"
                     r"(?:api[\s_-]?keys?|secrets?|tokens?|credentials?|env(?:ironment)?\s+vars?|"
                     r"system\s+prompt)", 0.95),
    ("tool_abuse", r"(?:call|invoke|execute|run)\s+(?:the\s+)?(?:shell|terminal|bash|"
                   r"eval|exec)\s*(?:function|command|tool)?", 0.55),
    ("encoding_evasion", r"base64|rot13|hex\s?decode|\\x[0-9a-f]{2}(?:\\x[0-9a-f]{2}){3,}", 0.6),
    ("delimiter_breakout", r"</?(?:system|assistant|user|instructions?)>|"
                           r"\[/?INST\]|<\|(?:im_start|im_end|system|endoftext)\|>", 0.8),
    ("fake_turn", r"^\s*(?:system|assistant|human)\s*[:\]]", 0.5),
    ("covert_instruction", r"do\s+not\s+(?:tell|inform|mention|reveal)\s+(?:this\s+)?"
                           r"(?:to\s+)?(?:the\s+)?(?:user|human|operator)", 0.8),
    ("data_exfiltration_instruction", r"include\s+(?:the\s+)?(?:api[\s_-]?key|password|"
                                      r"private[\s_-]?key|ssn|aadhaar)\s+in\s+(?:your|the)\s+"
                                      r"(?:output|answer|response)", 0.9),
)

INJECTION_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE | re.MULTILINE), weight)
                           for name, pattern, weight in INJECTION_PATTERNS)


@dataclass
class PIIRule:
    name: str
    label: str
    pattern: re.Pattern[str]
    severity: str = "medium"
    redact: bool = True
    validator: Any = None


def _luhn(digits: str) -> bool:
    numbers = [int(c) for c in digits if c.isdigit()]
    if len(numbers) < 13:
        return False
    checksum = 0
    parity = len(numbers) % 2
    for index, digit in enumerate(numbers):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


PII_RULES: tuple[PIIRule, ...] = (
    PIIRule("email", "Email address",
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "low"),
    PIIRule("phone_india", "Indian mobile number",
            re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{4}[-\s]?\d{5}(?!\d)"), "medium"),
    PIIRule("phone_international", "International phone number",
            re.compile(r"(?<![\d.])\+\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}(?![\d.])"),
            "low"),
    PIIRule("aadhaar", "Aadhaar number",
            re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"), "high"),
    PIIRule("pan_india", "PAN (tax identifier)",
            re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "high"),
    PIIRule("credit_card", "Payment card number",
            re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), "critical", True, _luhn),
    PIIRule("bank_account", "Bank account number",
            re.compile(r"(?<!\d)\d{9,18}(?!\d)"), "medium"),
    PIIRule("passport", "Passport number",
            re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"), "medium"),
    PIIRule("aws_key", "AWS access key",
            re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "critical"),
    PIIRule("private_key", "Private key block",
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----[\s\S]*?"
                       r"-----END (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "critical"),
    PIIRule("api_token", "API token / secret",
            re.compile(r"\b(?:sk|pk|ghp|gho|xox[baprs]|glpat)-[A-Za-z0-9_-]{16,}\b"), "critical"),
    PIIRule("bearer", "Bearer token",
            re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"), "critical"),
    PIIRule("password_assignment", "Password in text",
            re.compile(r"(?i)\b(?:password|passwd|pwd|secret)\s*[:=]\s*\S{4,}"), "critical"),
    PIIRule("ssn_us", "US social security number",
            re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "critical"),
    PIIRule("ip_address", "IP address",
            re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
                       r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])"), "low"),
    PIIRule("dob", "Date of birth",
            re.compile(r"(?i)\b(?:dob|date\s+of\s+birth|born(?:\s+on)?)\s*[:=]?\s*"
                       r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"), "high"),
    PIIRule("employee_id", "Employee identifier",
            re.compile(r"(?i)\b(?:emp(?:loyee)?[\s_-]?id|staff[\s_-]?id)\s*[:=]\s*[A-Z0-9-]{4,}\b"),
            "medium"),
)

REDACTION_TOKENS: dict[str, str] = {
    "email": "[EMAIL_REDACTED]",
    "phone_india": "[PHONE_REDACTED]",
    "phone_international": "[PHONE_REDACTED]",
    "aadhaar": "[AADHAAR_REDACTED]",
    "pan_india": "[PAN_REDACTED]",
    "credit_card": "[CARD_REDACTED]",
    "bank_account": "[ACCOUNT_REDACTED]",
    "passport": "[PASSPORT_REDACTED]",
    "aws_key": "[AWS_KEY_REDACTED]",
    "private_key": "[PRIVATE_KEY_REDACTED]",
    "api_token": "[TOKEN_REDACTED]",
    "bearer": "[TOKEN_REDACTED]",
    "password_assignment": "[SECRET_REDACTED]",
    "ssn_us": "[SSN_REDACTED]",
    "ip_address": "[IP_REDACTED]",
    "dob": "[DOB_REDACTED]",
    "employee_id": "[EMP_ID_REDACTED]",
}


@dataclass
class SecurityReport:
    injection_score: float = 0.0
    injection_patterns: list[str] = field(default_factory=list)
    injection_matches: list[dict[str, Any]] = field(default_factory=list)
    pii_findings: list[dict[str, Any]] = field(default_factory=list)
    pii_count: int = 0
    pii_types: list[str] = field(default_factory=list)
    risk_level: str = RiskLevel.NONE
    redactions_applied: int = 0
    recommendations: list[str] = field(default_factory=list)
    sanitised_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("sanitised_text", None)
        return data


RISK_BY_SEVERITY = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}


def _severity_to_risk(severities: set[str]) -> list[str]:
    return [str(RISK_BY_SEVERITY[s]) for s in severities if s in RISK_BY_SEVERITY]


def detect_prompt_injection(text: str) -> tuple[float, list[str], list[dict[str, Any]]]:
    """Return (score 0..1, matched pattern names, match details)."""
    if not text:
        return 0.0, [], []
    matches: list[dict[str, Any]] = []
    names: list[str] = []
    for name, pattern, weight in INJECTION_COMPILED:
        for found in pattern.finditer(text):
            names.append(name)
            matches.append(
                {
                    "pattern": name,
                    "weight": weight,
                    "evidence": found.group(0)[:160],
                    "position": found.start(),
                }
            )
    if not matches:
        return 0.0, [], []
    # Deduplicate identical evidence, then combine with saturating noise.
    unique = {(m["pattern"], m["evidence"].lower()) for m in matches}
    score = sum(w for name, _, w in INJECTION_COMPILED if any(u[0] == name for u in unique))
    score = min(1.0, round(score / 1.6, 4))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in matches:
        key = (match["pattern"], match["evidence"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    return score, sorted(set(names)), deduped[:25]


def detect_pii(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not text:
        return findings
    claimed: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in claimed)

    # Highest severity first so redaction order is stable.
    for rule in sorted(PII_RULES, key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}[r.severity]):
        for found in rule.pattern.finditer(text):
            value = found.group(0)
            if rule.validator and not rule.validator(value):
                continue
            if len(value.strip()) < 4:
                continue
            if overlaps(found.start(), found.end()):
                continue
            claimed.append((found.start(), found.end()))
            findings.append(
                {
                    "category": rule.name,
                    "label": rule.label,
                    "severity": rule.severity,
                    "position": found.start(),
                    "evidence": _mask(value, rule.name),
                    "redacted_value": REDACTION_TOKENS.get(rule.name, "[REDACTED]"),
                }
            )
    findings.sort(key=lambda f: f["position"])
    return findings


def _mask(value: str, category: str) -> str:
    compact = value.strip()
    if category in {"credit_card", "aadhaar", "bank_account", "ssn_us", "pan_india"}:
        return f"{compact[:2]}***{compact[-2:]}"
    if len(compact) <= 4:
        return "*" * len(compact)
    return f"{compact[:2]}{'*' * (len(compact) - 4)}{compact[-2:]}"


def redact(text: str, findings: list[dict[str, Any]], enabled: bool = True) -> tuple[str, int]:
    if not enabled or not findings:
        return text, 0
    result = text
    applied = 0
    for finding in sorted(findings, key=lambda f: f["position"], reverse=True):
        rule = next((r for r in PII_RULES if r.name == finding["category"]), None)
        if rule is None:
            continue
        token = finding["redacted_value"]
        replaced, count = rule.pattern.subn(token, result)
        if count:
            result = replaced
            applied += count
    return result, applied


def neutralise_instructions(text: str) -> str:
    """Rewrite injection-like lines so they cannot act as instructions."""
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        score, _, _ = detect_prompt_injection(line)
        if score >= 0.5 and line.strip():
            cleaned.append("[UNTRUSTED_INSTRUCTION_SUPPRESSED]")
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


def wrap_as_data(text: str, label: str = "SOURCE") -> str:
    """Fence untrusted content so the model treats it as data, not orders."""
    safe = re.sub(rf"<</?\s*{re.escape(label)}\s*>>", f"<{label}_ESCAPED>", text, flags=re.IGNORECASE)
    return f"<<{label}>>\n{safe}\n<</{label}>>"


def scan_text(text: str, redact_enabled: bool = True, sanitise: bool = False) -> SecurityReport:
    text = normalise_whitespace(text or "")
    injection_score, patterns, matches = detect_prompt_injection(text)
    pii = detect_pii(text)

    severities = {f["severity"] for f in pii}

    # Injection and sensitive-data risk are independent signals; the document
    # takes the higher of the two. Risk tracks the *severity* of what was found
    # rather than the mere presence of a match, so an indicator of compromise
    # (a bare IP in a threat report) does not read like a privacy incident.
    if injection_score >= 0.75:
        injection_risk = RiskLevel.CRITICAL
    elif injection_score >= 0.45:
        injection_risk = RiskLevel.HIGH
    elif injection_score > 0:
        injection_risk = RiskLevel.LOW
    else:
        injection_risk = RiskLevel.NONE

    pii_risk = max_risk(_severity_to_risk(severities))
    risk = max_risk([str(injection_risk), pii_risk])

    recommendations: list[str] = []
    if injection_score >= 0.45:
        recommendations.append(
            "Content contains instruction-like text. Transformation is restricted to source-grounded "
            "extraction and manual approval is required before release."
        )
    if any(f["category"] in {"api_token", "private_key", "aws_key", "bearer", "password_assignment"}
           for f in pii):
        recommendations.append("Rotate any credential present in the source before sharing this document.")
    if any(f["category"] in {"aadhaar", "pan_india", "ssn_us", "credit_card"} for f in pii):
        recommendations.append("Redacted national identifiers were removed. Confirm redaction before export.")
    if pii and not any(f["category"] in {"email", "ip_address"} for f in pii):
        recommendations.append("Personal identifiers detected - confirm the audience is authorised to receive them.")
    if not recommendations:
        recommendations.append("No prompt-injection or sensitive-data signals detected.")

    report = SecurityReport(
        injection_score=injection_score,
        injection_patterns=patterns,
        injection_matches=matches,
        pii_findings=pii,
        pii_count=len(pii),
        pii_types=sorted({f["category"] for f in pii}),
        risk_level=str(risk),
        recommendations=recommendations,
    )

    sanitised: str | None = None
    if sanitise:
        working = text
        if redact_enabled:
            working, applied = redact(working, pii, enabled=True)
            report.redactions_applied = applied
        working = neutralise_instructions(working)
        sanitised = wrap_as_data(working)
        report.sanitised_text = sanitised

    return report


def scan_output(text: str) -> dict[str, Any]:
    """Post-generation check: PII leakage and residual injection echoes."""
    pii = detect_pii(text)
    injection_score, patterns, _ = detect_prompt_injection(text)
    return {
        "pii_leaked": [f for f in pii if f["category"] not in {"ip_address"}],
        "pii_count": len(pii),
        "injection_echo_score": injection_score,
        "injection_patterns": patterns,
        "passed": not pii and injection_score < 0.3,
        "checked_at_stage": "output_validation",
    }
