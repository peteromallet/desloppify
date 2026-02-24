"""Shared subjective-review contract for prompts, normalization, and import validation."""

from __future__ import annotations

LOW_SCORE_FINDING_THRESHOLD = 95.0
ASSESSMENT_FEEDBACK_THRESHOLD = 100.0
HIGH_SCORE_ISSUES_NOTE_THRESHOLD = 85.0
DIMENSION_NOTE_ISSUES_KEY = "issues_preventing_higher_score"
LEGACY_DIMENSION_NOTE_ISSUES_KEY = "unreported_risk"
REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY = "high_score_missing_issue_note"
LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY = "high_score_without_risk"
DEFAULT_MAX_BATCH_FINDINGS = 10
_PROMPT_CONTRACT_HEADER = "GLOBAL REVIEW CONTRACT (applies to every dimension):"

# Backward compatibility alias for older imports.
HIGH_SCORE_UNREPORTED_RISK_THRESHOLD = HIGH_SCORE_ISSUES_NOTE_THRESHOLD


def max_batch_findings_for_dimension_count(dimension_count: int) -> int:
    """Return the normalized max findings budget for one batch payload."""
    safe_count = max(0, int(dimension_count))
    return max(DEFAULT_MAX_BATCH_FINDINGS, safe_count)


def score_requires_dimension_finding(score: float) -> bool:
    """Return True when score requires at least one explicit finding."""
    return float(score) < LOW_SCORE_FINDING_THRESHOLD


def score_requires_explicit_feedback(score: float) -> bool:
    """Return True when score requires a finding or dimension-note evidence."""
    return float(score) < ASSESSMENT_FEEDBACK_THRESHOLD


def global_prompt_contract() -> str:
    """Render shared review contract text injected into all review prompts."""
    return (
        f"{_PROMPT_CONTRACT_HEADER}\n"
        "- Scope breadth: report any material issues supported by evidence "
        "(structural, architectural, boundary, readability, lifecycle), "
        "not only low-level nits.\n"
        "- Dimension boundaries are guidance, not a gag-order: if an issue "
        "spans dimensions, report it under the most impacted dimension.\n"
        "- Do not default to 100. Reserve 100 for genuinely exemplary code "
        "with clear positive evidence; if there is uncertainty or residual "
        "issues, score below 100.\n"
        "- Do not suppress valid findings to keep scores high.\n"
        f"- Scores below {LOW_SCORE_FINDING_THRESHOLD:.1f} MUST include at least one "
        "finding for that same dimension.\n"
        f"- Scores below {ASSESSMENT_FEEDBACK_THRESHOLD:.1f} MUST include explicit "
        "feedback for that same dimension (finding with suggestion or "
        "dimension_notes evidence).\n"
        f"- Scores above {HIGH_SCORE_ISSUES_NOTE_THRESHOLD:.1f} MUST include a "
        "non-empty `issues_preventing_higher_score` note for that dimension.\n"
        "- Findings must always describe defects that need change, never positive observations.\n"
        "- Think structurally: when individual findings form a pattern, consider what is\n"
        "  causing them. If several issues stem from a shared root cause (missing abstraction,\n"
        "  repeated pattern, inconsistent convention), say so in the findings — explain the\n"
        "  deeper issue and use root_cause_cluster to connect related symptoms."
    )


def ensure_prompt_contract(system_prompt: str) -> str:
    """Append shared contract text once to a system prompt."""
    text = (system_prompt or "").strip()
    if _PROMPT_CONTRACT_HEADER in text:
        return text
    suffix = global_prompt_contract()
    if not text:
        return suffix
    return f"{text}\n\n{suffix}"


__all__ = [
    "ASSESSMENT_FEEDBACK_THRESHOLD",
    "DIMENSION_NOTE_ISSUES_KEY",
    "DEFAULT_MAX_BATCH_FINDINGS",
    "HIGH_SCORE_ISSUES_NOTE_THRESHOLD",
    "HIGH_SCORE_UNREPORTED_RISK_THRESHOLD",
    "LEGACY_DIMENSION_NOTE_ISSUES_KEY",
    "LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY",
    "REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY",
    "LOW_SCORE_FINDING_THRESHOLD",
    "ensure_prompt_contract",
    "global_prompt_contract",
    "max_batch_findings_for_dimension_count",
    "score_requires_dimension_finding",
    "score_requires_explicit_feedback",
]
