"""State schema/types, constants, and validation helpers."""

from __future__ import annotations

from desloppify.base.compatibility import UTC
from datetime import datetime
from desloppify.base.compatibility import NotRequired, Required
from typing import Any, TypedDict, cast

from desloppify.base.enums import Status, canonical_issue_status, issue_status_tokens
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine._state.schema_scores import (
    json_default,
)
from desloppify.languages._framework.base.types import ScanCoverageRecord

__all__ = [
    "ConcernDismissal",
    "AssessmentImportAuditEntry",
    "AttestationLogEntry",
    "Issue",
    "TierStats",
    "StateStats",
    "DimensionScore",
    "ScoreConfidenceDetector",
    "ScoreConfidenceModel",
    "ScanHistoryEntry",
    "SubjectiveAssessment",
    "SubjectiveIntegrity",
    "LangCapability",
    "ReviewCacheModel",
    "IgnoreIntegrityModel",
    "StateModel",
    "ScanDiff",
    "STATE_DIR",
    "STATE_FILE",
    "CURRENT_VERSION",
    "utc_now",
    "empty_state",
    "ensure_state_defaults",
    "validate_state_invariants",
    "json_default",
    "migrate_state_keys",
]

_ALLOWED_ISSUE_STATUSES: set[str] = {
    *issue_status_tokens(),
}


class Issue(TypedDict):
    """The central data structure: a normalized issue from any detector."""

    id: str
    detector: str
    file: str
    tier: int
    confidence: str
    summary: str
    # Known detail shapes per detector (non-exhaustive, for reference):
    #
    # structural:      {loc, complexity_score?, complexity_signals?: list[str],
    #                   name? (god class), ...god_class_metrics}
    # smells:          {smell_id, severity, count, lines: list[int]}
    # dupes:           {fn_a: dict, fn_b: dict, similarity, kind, cluster_size,
    #                   cluster: list}
    # coupling:        {target, tool?, direction, sole_tool?, importer_count?,
    #                   loc?, source_tool?, target_tool?}
    # single_use:      {loc, sole_importer}
    # orphaned:        {loc}
    # facade:          {loc, importers, imports_from: list[str], kind}
    # review:          {holistic?: bool, dimension?, related_files?: list[str],
    #                   suggestion?, evidence?: list[str], investigation?,
    #                   merged_at?}
    # review_coverage: {reason, loc?, age_days?, old_files?, new_files?}
    # security:        {kind, severity, line, content, remediation}
    # test_coverage:   {kind, loc?, importer_count?, loc_weight?,
    #                   test_file?, test_functions?, assertions?, mocks?,
    #                   snapshots?}
    # props:           {passthrough entry fields minus "file"}
    # subjective_assessment (synthetic): {dimension_name, dimension, failing,
    #                   strict_score, open_review_issues?}
    # workflow (synthetic): {stage?, strict?, plan_start_strict?, delta?,
    #                   total_review_issues?, explanation?}
    detail: dict[str, Any]
    status: Status
    note: str | None
    first_seen: str
    last_seen: str
    resolved_at: str | None
    reopen_count: int
    suppressed: NotRequired[bool]
    suppressed_at: NotRequired[str | None]
    suppression_pattern: NotRequired[str | None]
    resolution_attestation: NotRequired[dict[str, str | bool | None]]
    lang: NotRequired[str]
    zone: NotRequired[str]


class TierStats(TypedDict, total=False):
    open: int
    fixed: int
    auto_resolved: int
    wontfix: int
    false_positive: int


class StateStats(TypedDict, total=False):
    total: int
    open: int
    fixed: int
    auto_resolved: int
    wontfix: int
    false_positive: int
    by_tier: dict[str, TierStats]


class DimensionScore(TypedDict, total=False):
    score: float
    strict: float
    verified_strict_score: float
    checks: int
    failing: int
    tier: int
    carried_forward: bool
    detectors: dict[str, Any]
    coverage_status: str
    coverage_confidence: float
    coverage_impacts: list[dict[str, Any]]


class ScoreConfidenceDetector(TypedDict, total=False):
    """Detector-level confidence details persisted after each scan."""

    detector: str
    status: str
    confidence: float
    summary: str
    impact: str
    remediation: str
    tool: str
    reason: str


class ScoreConfidenceModel(TypedDict, total=False):
    """State-level score confidence summary."""

    status: str
    confidence: float
    detectors: list[ScoreConfidenceDetector]
    dimensions: list[str]


class ScanHistoryEntry(TypedDict, total=False):
    timestamp: str
    lang: str | None
    strict_score: float | None
    verified_strict_score: float | None
    objective_score: float | None
    overall_score: float | None
    open: int
    diff_new: int
    diff_resolved: int
    ignored: int
    raw_issues: int
    suppressed_pct: float
    ignore_patterns: int
    subjective_integrity: dict[str, Any] | None
    dimension_scores: dict[str, dict[str, float]] | None
    score_confidence: ScoreConfidenceModel | None


class SubjectiveIntegrity(TypedDict, total=False):
    """Anti-gaming metadata for subjective assessment scores."""

    status: str  # "disabled" | "pass" | "warn" | "penalized"
    target_score: float | None
    matched_count: int
    matched_dimensions: list[str]
    reset_dimensions: list[str]


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
    mode: str
    trusted: bool
    reason: str
    override_used: bool
    attested_external: bool
    provisional: bool
    provisional_count: int
    attest: str
    import_file: str


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


class StateModel(TypedDict, total=False):
    version: Required[int]
    created: Required[str]
    last_scan: Required[str | None]
    scan_count: Required[int]
    overall_score: Required[float]
    objective_score: Required[float]
    strict_score: Required[float]
    verified_strict_score: Required[float]
    stats: Required[StateStats]
    issues: Required[dict[str, Issue]]
    dimension_scores: dict[str, DimensionScore]
    scan_path: str | None
    tool_hash: str
    scan_completeness: dict[str, str]
    potentials: dict[str, dict[str, int]]
    codebase_metrics: dict[str, dict[str, Any]]
    scan_coverage: dict[str, ScanCoverageRecord]
    score_confidence: ScoreConfidenceModel
    scan_history: list[ScanHistoryEntry]
    lang_capabilities: dict[str, LangCapability]
    zone_distribution: dict[str, int]
    review_cache: ReviewCacheModel
    reminder_history: dict[str, int]
    ignore_integrity: IgnoreIntegrityModel
    config: dict[str, Any]
    lang: str
    subjective_integrity: Required[SubjectiveIntegrity]
    subjective_assessments: Required[dict[str, SubjectiveAssessment]]
    custom_review_dimensions: list[str]
    assessment_import_audit: list[AssessmentImportAuditEntry]
    attestation_log: list[AttestationLogEntry]
    concern_dismissals: dict[str, ConcernDismissal]
    _plan_start_scores_for_reveal: dict[str, Any]


class ScanDiff(TypedDict):
    new: int
    auto_resolved: int
    reopened: int
    total_current: int
    suspect_detectors: list[str]
    chronic_reopeners: list[dict]
    skipped_other_lang: int
    resolved_out_of_scope: int
    ignored: int
    ignore_patterns: int
    raw_issues: int
    suppressed_pct: float
    skipped: NotRequired[int]
    skipped_details: NotRequired[list[dict]]


STATE_DIR = get_project_root() / ".desloppify"
STATE_FILE = STATE_DIR / "state.json"
CURRENT_VERSION = 1


def utc_now() -> str:
    """Return current UTC timestamp with second-level precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def empty_state() -> StateModel:
    """Return a new empty state payload."""
    return {
        "version": CURRENT_VERSION,
        "created": utc_now(),
        "last_scan": None,
        "scan_count": 0,
        "overall_score": 0,
        "objective_score": 0,
        "strict_score": 0,
        "verified_strict_score": 0,
        "stats": {},
        "issues": {},
        "scan_coverage": {},
        "score_confidence": {},
        "subjective_integrity": {},
        "subjective_assessments": {},
    }


def _as_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else 0


def _rename_key(d: dict, old: str, new: str) -> bool:
    if old not in d:
        return False
    d.setdefault(new, d.pop(old))
    return True


def migrate_state_keys(state: StateModel | dict[str, Any]) -> None:
    """Migrate legacy key names in-place.

    - ``"findings"`` → ``"issues"``
    - ``dimension_scores[dim]["issues"]`` → ``"failing"``
    """
    state_dict = cast(dict[str, Any], state)
    _rename_key(state_dict, "findings", "issues")

    for ds in state_dict.get("dimension_scores", {}).values():
        if isinstance(ds, dict):
            _rename_key(ds, "issues", "failing")

    for entry in state_dict.get("scan_history", []):
        if not isinstance(entry, dict):
            continue
        _rename_key(entry, "raw_findings", "raw_issues")
        for ds in (entry.get("dimension_scores") or {}).values():
            if isinstance(ds, dict):
                _rename_key(ds, "issues", "failing")


def ensure_state_defaults(state: StateModel | dict) -> None:
    """Normalize loose/legacy state payloads to a valid base shape in-place."""
    migrate_state_keys(state)

    mutable_state = cast(dict[str, Any], state)
    for key, value in empty_state().items():
        mutable_state.setdefault(key, value)

    if not isinstance(state.get("issues"), dict):
        state["issues"] = {}
    if not isinstance(state.get("stats"), dict):
        state["stats"] = {}
    if not isinstance(state.get("scan_history"), list):
        state["scan_history"] = []
    if not isinstance(state.get("scan_coverage"), dict):
        state["scan_coverage"] = {}
    if not isinstance(state.get("score_confidence"), dict):
        state["score_confidence"] = {}
    if not isinstance(state.get("subjective_integrity"), dict):
        state["subjective_integrity"] = {}

    all_issues = state["issues"]
    to_remove: list[str] = []
    for issue_id, issue in all_issues.items():
        if not isinstance(issue, dict):
            to_remove.append(issue_id)
            continue

        issue.setdefault("id", issue_id)
        issue.setdefault("detector", "unknown")
        issue.setdefault("file", "")
        issue.setdefault("tier", 3)
        issue.setdefault("confidence", "low")
        issue.setdefault("summary", "")
        issue.setdefault("detail", {})
        issue.setdefault("status", "open")
        issue["status"] = canonical_issue_status(
            issue.get("status"),
            default="open",
        )
        issue.setdefault("note", None)
        issue.setdefault("first_seen", state.get("created") or utc_now())
        issue.setdefault("last_seen", issue["first_seen"])
        issue.setdefault("resolved_at", None)
        issue["reopen_count"] = _as_non_negative_int(
            issue.get("reopen_count", 0), default=0
        )
        issue.setdefault("suppressed", False)
        issue.setdefault("suppressed_at", None)
        issue.setdefault("suppression_pattern", None)

    for issue_id in to_remove:
        all_issues.pop(issue_id, None)

    for entry in state["scan_history"]:
        if not isinstance(entry, dict):
            continue
        integrity = entry.get("subjective_integrity")
        if integrity is not None and not isinstance(integrity, dict):
            entry["subjective_integrity"] = None

    state["scan_count"] = _as_non_negative_int(state.get("scan_count", 0), default=0)
    return None


def validate_state_invariants(state: StateModel) -> None:
    """Raise ValueError when core state invariants are violated."""
    if not isinstance(state.get("issues"), dict):
        raise ValueError("state.issues must be a dict")
    if not isinstance(state.get("stats"), dict):
        raise ValueError("state.stats must be a dict")

    all_issues = state["issues"]
    for issue_id, issue in all_issues.items():
        if not isinstance(issue, dict):
            raise ValueError(f"issue {issue_id!r} must be a dict")
        if issue.get("id") != issue_id:
            raise ValueError(f"issue id mismatch for {issue_id!r}")
        if issue.get("status") not in _ALLOWED_ISSUE_STATUSES:
            raise ValueError(
                f"issue {issue_id!r} has invalid status {issue.get('status')!r}"
            )

        tier = issue.get("tier")
        if not isinstance(tier, int) or tier < 1 or tier > 4:
            raise ValueError(f"issue {issue_id!r} has invalid tier {tier!r}")

        reopen_count = issue.get("reopen_count")
        if not isinstance(reopen_count, int) or reopen_count < 0:
            raise ValueError(
                f"issue {issue_id!r} has invalid reopen_count {reopen_count!r}"
            )
