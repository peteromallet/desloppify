"""Review- and assessment-related TypedDict models for persisted state payloads."""

from __future__ import annotations

from typing import Any, TypedDict


class SubjectiveIntegrity(TypedDict, total=False):
    """Anti-gaming metadata for subjective assessment scores."""

    status: str  # "disabled" | "pass" | "warn" | "penalized"
    target_score: float | None
    matched_count: int
    matched_dimensions: list[str]
    reset_dimensions: list[str]


class SubjectiveAssessmentJudgment(TypedDict, total=False):
    """Reviewer's holistic judgment narrative for a subjective dimension."""

    strengths: list[str]
    dimension_character: str
    score_rationale: str


class SubjectiveAssessment(TypedDict, total=False):
    """A single subjective dimension assessment payload."""

    score: float
    source: str
    assessed_at: str
    reset_by: str
    placeholder: bool
    components: list[str]
    component_scores: dict[str, float]
    integrity_penalty: str | None
    provisional_override: bool
    provisional_until_scan: int
    needs_review_refresh: bool
    refresh_reason: str | None
    stale_since: str | None
    judgment: SubjectiveAssessmentJudgment


class ConcernDismissal(TypedDict, total=False):
    """Record of a dismissed concern from review output."""

    dismissed_at: str
    reason: str | None
    dimension: str
    reasoning: str
    concern_type: str
    concern_file: str
    source_issue_ids: list[str]


class AssessmentImportAuditEntry(TypedDict, total=False):
    """Typed record for review assessment import events."""

    timestamp: str
    scan_timestamp: str
    assessment_timestamps: dict[str, str]
    mode: str
    trusted: bool
    reason: str
    override_used: bool
    attested_external: bool
    provisional: bool
    provisional_count: int
    attest: str
    import_file: str
    packet_sha256: str


class AttestationLogEntry(TypedDict, total=False):
    """Typed entry for resolve/suppress attestation history."""

    timestamp: str | None
    command: str
    pattern: str
    attestation: str | None
    affected: int


class LangCapability(TypedDict, total=False):
    """Capabilities reported for a language runtime."""

    fixers: list[str]
    typecheck_cmd: str


class ReviewCacheModel(TypedDict, total=False):
    """Cached review metadata keyed by relative file path."""

    files: dict[str, dict[str, Any]]
    holistic: dict[str, Any]


class IgnoreIntegrityModel(TypedDict, total=False):
    """Ignore/suppression integrity summary used by reporting surfaces."""

    ignored: int
    suppressed_pct: float
    ignore_patterns: int
    raw_issues: int


class ContextInsight(TypedDict, total=False):
    """A single piece of accumulated knowledge about a dimension."""

    header: str
    description: str
    settled: bool
    positive: bool
    added_at: str
    source: str


class DimensionContext(TypedDict, total=False):
    """Accumulated understanding for a subjective dimension across review rounds."""

    insights: list[ContextInsight]
    created_at: str
    updated_at: str
    stable_rounds: int


__all__ = [
    "AssessmentImportAuditEntry",
    "AttestationLogEntry",
    "ConcernDismissal",
    "ContextInsight",
    "DimensionContext",
    "IgnoreIntegrityModel",
    "LangCapability",
    "ReviewCacheModel",
    "SubjectiveAssessment",
    "SubjectiveAssessmentJudgment",
    "SubjectiveIntegrity",
]
