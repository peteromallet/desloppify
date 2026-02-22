"""State schema/types, constants, and validation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, NotRequired, Required, TypedDict, cast

from desloppify.core._internal.text_utils import PROJECT_ROOT

__all__ = [
    "ConcernDismissal",
    "FindingStatus",
    "Finding",
    "TierStats",
    "StateStats",
    "DimensionScore",
    "ScanHistoryEntry",
    "SubjectiveAssessment",
    "SubjectiveIntegrity",
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
    "get_overall_score",
    "get_objective_score",
    "get_strict_score",
    "get_verified_strict_score",
]

FindingStatus = Literal["open", "fixed", "auto_resolved", "wontfix", "false_positive"]
_ALLOWED_FINDING_STATUSES: set[str] = {
    "open",
    "fixed",
    "auto_resolved",
    "wontfix",
    "false_positive",
}


class Finding(TypedDict):
    """The central data structure: a normalized finding from any detector."""

    id: str
    detector: str
    file: str
    tier: int
    confidence: str
    summary: str
    detail: dict
    status: FindingStatus
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
    checks: int
    issues: int
    tier: int
    detectors: dict[str, Any]


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
    raw_findings: int
    suppressed_pct: float
    ignore_patterns: int
    subjective_integrity: dict[str, Any] | None
    dimension_scores: dict[str, dict[str, float]] | None


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
    integrity_penalty: str | None
    needs_review_refresh: bool
    refresh_reason: str | None
    stale_since: str | None


class ConcernDismissal(TypedDict, total=False):
    """Record of a dismissed concern from review output."""

    dismissed_at: str
    reason: str | None
    dimension: str


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
    findings: Required[dict[str, Finding]]
    scan_history: list[ScanHistoryEntry]
    subjective_integrity: Required[SubjectiveIntegrity]
    subjective_assessments: Required[dict[str, SubjectiveAssessment]]
    concern_dismissals: dict[str, ConcernDismissal]


class ScanDiff(TypedDict):
    new: int
    auto_resolved: int
    reopened: int
    total_current: int
    suspect_detectors: list[str]
    chronic_reopeners: list[dict]
    skipped_other_lang: int
    skipped_out_of_scope: int
    ignored: int
    ignore_patterns: int
    raw_findings: int
    suppressed_pct: float
    skipped: NotRequired[int]
    skipped_details: NotRequired[list[dict]]


STATE_DIR = PROJECT_ROOT / ".desloppify"
STATE_FILE = STATE_DIR / "state.json"
CURRENT_VERSION = 1


def utc_now() -> str:
    """Return current UTC timestamp with second-level precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        "findings": {},
        "subjective_integrity": {},
        "subjective_assessments": {},
    }


def _as_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else 0


def ensure_state_defaults(state: StateModel | dict) -> StateModel:
    """Normalize loose/legacy state payloads to a valid base shape."""
    for key, value in empty_state().items():
        state.setdefault(key, value)

    if not isinstance(state.get("findings"), dict):
        state["findings"] = {}
    if not isinstance(state.get("stats"), dict):
        state["stats"] = {}
    if not isinstance(state.get("scan_history"), list):
        state["scan_history"] = []
    if not isinstance(state.get("subjective_integrity"), dict):
        state["subjective_integrity"] = {}

    findings = state["findings"]
    to_remove: list[str] = []
    for finding_id, finding in findings.items():
        if not isinstance(finding, dict):
            to_remove.append(finding_id)
            continue

        finding.setdefault("id", finding_id)
        finding.setdefault("detector", "unknown")
        finding.setdefault("file", "")
        finding.setdefault("tier", 3)
        finding.setdefault("confidence", "low")
        finding.setdefault("summary", "")
        finding.setdefault("detail", {})
        finding.setdefault("status", "open")
        # Migrate legacy "resolved" status (renamed to "fixed" during Status enum migration)
        if finding["status"] == "resolved":
            finding["status"] = "fixed"
        if finding["status"] not in _ALLOWED_FINDING_STATUSES:
            finding["status"] = "open"
        finding.setdefault("note", None)
        finding.setdefault("first_seen", state.get("created") or utc_now())
        finding.setdefault("last_seen", finding["first_seen"])
        finding.setdefault("resolved_at", None)
        finding["reopen_count"] = _as_non_negative_int(
            finding.get("reopen_count", 0), default=0
        )
        finding.setdefault("suppressed", False)
        finding.setdefault("suppressed_at", None)
        finding.setdefault("suppression_pattern", None)

    for finding_id in to_remove:
        findings.pop(finding_id, None)

    for entry in state["scan_history"]:
        if not isinstance(entry, dict):
            continue
        integrity = entry.get("subjective_integrity")
        if integrity is not None and not isinstance(integrity, dict):
            entry["subjective_integrity"] = None

    state["scan_count"] = _as_non_negative_int(state.get("scan_count", 0), default=0)
    return cast(StateModel, state)


def validate_state_invariants(state: StateModel) -> None:
    """Raise ValueError when core state invariants are violated."""
    if not isinstance(state.get("findings"), dict):
        raise ValueError("state.findings must be a dict")
    if not isinstance(state.get("stats"), dict):
        raise ValueError("state.stats must be a dict")

    findings = state["findings"]
    for finding_id, finding in findings.items():
        if not isinstance(finding, dict):
            raise ValueError(f"finding {finding_id!r} must be a dict")
        if finding.get("id") != finding_id:
            raise ValueError(f"finding id mismatch for {finding_id!r}")
        if finding.get("status") not in _ALLOWED_FINDING_STATUSES:
            raise ValueError(
                f"finding {finding_id!r} has invalid status {finding.get('status')!r}"
            )

        tier = finding.get("tier")
        if not isinstance(tier, int) or tier < 1 or tier > 4:
            raise ValueError(f"finding {finding_id!r} has invalid tier {tier!r}")

        reopen_count = finding.get("reopen_count")
        if not isinstance(reopen_count, int) or reopen_count < 0:
            raise ValueError(
                f"finding {finding_id!r} has invalid reopen_count {reopen_count!r}"
            )


def json_default(obj: Any) -> Any:
    """JSON serializer that handles known types and rejects unknowns."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj).replace("\\", "/")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable: {obj!r}"
    )


def get_overall_score(state: StateModel) -> float | None:
    """Canonical overall score (lenient, includes subjective dimensions)."""
    return state.get("overall_score")


def get_objective_score(state: StateModel) -> float | None:
    """Canonical objective score (lenient, mechanical dimensions only)."""
    return state.get("objective_score")


def get_strict_score(state: StateModel) -> float | None:
    """Canonical strict score (strict, includes subjective dimensions)."""
    return state.get("strict_score")


def get_verified_strict_score(state: StateModel) -> float | None:
    """Strict score that only credits scan-verified fixes.

    Returns None if no scan-verified score exists yet (fresh state or
    no scan has run). Does not fall back to the unverified strict_score.
    """
    return state.get("verified_strict_score")
