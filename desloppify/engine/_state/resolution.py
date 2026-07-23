"""State resolution operations (match + resolve)."""

from __future__ import annotations

import copy

__all__ = [
    "coerce_assessment_score",
    "match_issues",
    "resolve_issues",
]

from desloppify.base.text_utils import is_numeric
from desloppify.engine._state.filtering import _matches_pattern
from desloppify.engine._state.issue_semantics import is_review_finding
from desloppify.engine._state.schema import (
    StateModel,
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)


from desloppify.engine._state import _recompute_stats


def _preserve_integrity_target(state: StateModel) -> float | None:
    """Extract the current subjective integrity target so recompute doesn't erase it."""
    integrity = state.get("subjective_integrity")
    if not isinstance(integrity, dict):
        return None
    raw = integrity.get("target_score")
    if raw is None:
        return None
    try:
        return max(0.0, min(100.0, float(raw)))
    except (TypeError, ValueError):
        return None


def coerce_assessment_score(value: object) -> float | None:
    """Normalize a subjective assessment score payload to a 0-100 float.

    Returns ``None`` when the value cannot be interpreted as a numeric score
    (e.g. bools, non-numeric strings, missing keys).
    """
    if is_numeric(value):
        return round(max(0.0, min(100.0, float(value))), 1)
    if isinstance(value, dict):
        raw = value.get("score")
        if not is_numeric(raw):
            return None
        return round(max(0.0, min(100.0, float(raw))), 1)
    return None


def _mark_stale_assessments_on_review_resolve(
    state: StateModel,
    *,
    status: str,
    resolved_issues: list[dict],
    now: str,
) -> None:
    """Mark subjective assessments as stale when review issues are resolved.

    The assessment score is preserved (not zeroed) — only a fresh review import
    should change dimension scores.  The stale marker tells the UI to prompt
    for a re-review.
    """
    assessments = state.get("subjective_assessments")
    if not isinstance(assessments, dict) or not assessments:
        return

    touched_dimensions: set[str] = set()
    for issue in resolved_issues:
        if not is_review_finding(issue):
            continue
        dimension = str(issue.get("detail", {}).get("dimension", "")).strip()
        if dimension:
            touched_dimensions.add(dimension)

    for dimension in sorted(touched_dimensions):
        if dimension not in assessments:
            continue

        payload = assessments.get(dimension)
        if isinstance(payload, dict):
            payload["needs_review_refresh"] = True
            payload["refresh_reason"] = f"review_issue_{status}"
            payload["stale_since"] = now
        else:
            assessments[dimension] = {
                "score": coerce_assessment_score(payload) or 0.0,
                "needs_review_refresh": True,
                "refresh_reason": f"review_issue_{status}",
                "stale_since": now,
            }


def match_issues(
    state: StateModel, pattern: str, status_filter: str = "open"
) -> list[dict]:
    """Return issues matching *pattern* with the given status."""
    ensure_state_defaults(state)
    return [
        issue
        for issue_id, issue in state["work_items"].items()
        if not issue.get("suppressed")
        if (status_filter == "all" or issue["status"] == status_filter)
        and _matches_pattern(issue_id, issue, pattern)
    ]


def resolve_issues(
    state: StateModel,
    pattern: str,
    status: str,
    note: str | None = None,
    attestation: str | None = None,
    *,
    reattribute_auto_resolved: bool = False,
) -> list[str]:
    """Set issue status for matches and return affected issue IDs."""
    ensure_state_defaults(state)
    now = utc_now()
    resolved: list[str] = []
    resolved_issues: list[dict] = []

    def _refresh_original_wontfix(issue: dict) -> None:
        if status != "fixed" or issue.get("detector") != "stale_wontfix":
            return
        detail = issue.get("detail", {})
        if not isinstance(detail, dict):
            return
        original_issue_id = detail.get("original_issue_id")
        if not isinstance(original_issue_id, str) or not original_issue_id:
            return
        original = state["work_items"].get(original_issue_id)
        if not isinstance(original, dict) or original.get("status") != "wontfix":
            return
        snapshot_scan_count = int(state.get("scan_count", 0) or 0)
        original["wontfix_scan_count"] = snapshot_scan_count
        original["wontfix_snapshot"] = {
            "captured_at": now,
            "scan_count": snapshot_scan_count,
            "tier": original.get("tier"),
            "confidence": original.get("confidence"),
            "detail": copy.deepcopy(original.get("detail", {})),
        }

    status_filter = (
        "all"
        if status == "open"
        or (
            status == "fixed"
            and reattribute_auto_resolved
            and bool(attestation)
        )
        else "open"
    )
    for issue in match_issues(state, pattern, status_filter=status_filter):
        previous_status = str(issue.get("status", "open")).strip() or "open"
        if status == "fixed" and previous_status not in {"open", "auto_resolved"}:
            continue
        if status == "open" and previous_status == "open":
            continue

        extra_updates: dict[str, object] = {}
        if status == "wontfix":
            snapshot_scan_count = int(state.get("scan_count", 0) or 0)
            extra_updates["wontfix_scan_count"] = snapshot_scan_count
            extra_updates["wontfix_snapshot"] = {
                "captured_at": now,
                "scan_count": snapshot_scan_count,
                "tier": issue.get("tier"),
                "confidence": issue.get("confidence"),
                "detail": copy.deepcopy(issue.get("detail", {})),
            }
        if status == "open":
            issue["reopen_count"] = int(issue.get("reopen_count", 0) or 0) + 1
            issue.pop("wontfix_scan_count", None)
            issue.pop("wontfix_snapshot", None)
            previous_note = issue.get("note")
            next_note = note if note is not None else previous_note
            extra_updates["resolved_at"] = None
            extra_updates["note"] = next_note
            reopen_attestation = {
                "kind": "manual_reopen",
                "text": attestation or note,
                "attested_at": now,
                "scan_verified": False,
            }
            reopen_attestation["previous_status"] = previous_status
            extra_updates["resolution_attestation"] = reopen_attestation

        resolution_attestation = {
            "kind": "manual",
            "text": attestation,
            "attested_at": now,
            "scan_verified": False,
        }
        if previous_status == "auto_resolved":
            resolution_attestation["previous_status"] = previous_status
        updates: dict[str, object] = {
            "status": status,
            "note": note,
            "resolved_at": now,
            "suppressed": False,
            "suppressed_at": None,
            "suppression_pattern": None,
            "resolution_attestation": resolution_attestation,
        }
        updates.update(extra_updates)
        issue.update(updates)
        _refresh_original_wontfix(issue)
        resolved.append(issue["id"])
        resolved_issues.append(issue)

    _mark_stale_assessments_on_review_resolve(
        state,
        status=status,
        resolved_issues=resolved_issues,
        now=now,
    )

    _recompute_stats(
        state,
        scan_path=state.get("scan_path"),
        subjective_integrity_target=_preserve_integrity_target(state),
    )
    validate_state_invariants(state)
    return resolved
