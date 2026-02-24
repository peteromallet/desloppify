"""State resolution operations (match + resolve)."""

from __future__ import annotations

import copy

__all__ = [
    "coerce_assessment_score",
    "match_findings",
    "resolve_findings",
]

from desloppify.core._internal.text_utils import is_numeric
from desloppify.engine._state.filtering import _matches_pattern
from desloppify.engine._state.schema import (
    StateModel,
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)
from desloppify.engine._state.scoring import _recompute_stats


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
    resolved_findings: list[dict],
    now: str,
) -> None:
    """Mark subjective assessments as stale when review findings are resolved.

    The assessment score is preserved (not zeroed) — only a fresh review import
    should change dimension scores.  The stale marker tells the UI to prompt
    for a re-review.
    """
    assessments = state.get("subjective_assessments")
    if not isinstance(assessments, dict) or not assessments:
        return

    touched_dimensions: set[str] = set()
    for finding in resolved_findings:
        if finding.get("detector") != "review":
            continue
        dimension = str(finding.get("detail", {}).get("dimension", "")).strip()
        if dimension:
            touched_dimensions.add(dimension)

    for dimension in sorted(touched_dimensions):
        if dimension not in assessments:
            continue

        payload = assessments.get(dimension)
        if isinstance(payload, dict):
            payload["needs_review_refresh"] = True
            payload["refresh_reason"] = f"review_finding_{status}"
            payload["stale_since"] = now
        else:
            assessments[dimension] = {
                "score": coerce_assessment_score(payload) or 0.0,
                "needs_review_refresh": True,
                "refresh_reason": f"review_finding_{status}",
                "stale_since": now,
            }


def match_findings(
    state: StateModel, pattern: str, status_filter: str = "open"
) -> list[dict]:
    """Return findings matching *pattern* with the given status."""
    ensure_state_defaults(state)
    return [
        finding
        for finding_id, finding in state["findings"].items()
        if not finding.get("suppressed")
        if (status_filter == "all" or finding["status"] == status_filter)
        and _matches_pattern(finding_id, finding, pattern)
    ]


def resolve_findings(
    state: StateModel,
    pattern: str,
    status: str,
    note: str | None = None,
    attestation: str | None = None,
) -> list[str]:
    """Set finding status for matches and return affected finding IDs."""
    ensure_state_defaults(state)
    now = utc_now()
    resolved: list[str] = []
    resolved_findings: list[dict] = []
    status_filter = "all" if status == "open" else "open"
    for finding in match_findings(state, pattern, status_filter=status_filter):
        previous_status = str(finding.get("status", "open")).strip() or "open"
        if status == "open" and previous_status == "open":
            continue

        extra_updates: dict[str, object] = {}
        if status == "wontfix":
            snapshot_scan_count = int(state.get("scan_count", 0) or 0)
            extra_updates["wontfix_scan_count"] = snapshot_scan_count
            extra_updates["wontfix_snapshot"] = {
                "captured_at": now,
                "scan_count": snapshot_scan_count,
                "tier": finding.get("tier"),
                "confidence": finding.get("confidence"),
                "detail": copy.deepcopy(finding.get("detail", {})),
            }
        if status == "open":
            finding["reopen_count"] = int(finding.get("reopen_count", 0) or 0) + 1
            finding.pop("wontfix_scan_count", None)
            finding.pop("wontfix_snapshot", None)
            previous_note = finding.get("note")
            next_note = note if note is not None else previous_note
            extra_updates["resolved_at"] = None
            extra_updates["note"] = next_note
            extra_updates["resolution_attestation"] = {
                "kind": "manual_reopen",
                "text": attestation or note,
                "attested_at": now,
                "scan_verified": False,
                "previous_status": previous_status,
            }

        updates: dict[str, object] = {
            "status": status,
            "note": note,
            "resolved_at": now,
            "suppressed": False,
            "suppressed_at": None,
            "suppression_pattern": None,
            "resolution_attestation": {
                "kind": "manual",
                "text": attestation,
                "attested_at": now,
                "scan_verified": False,
            },
        }
        updates.update(extra_updates)
        finding.update(updates)
        resolved.append(finding["id"])
        resolved_findings.append(finding)

    _mark_stale_assessments_on_review_resolve(
        state,
        status=status,
        resolved_findings=resolved_findings,
        now=now,
    )

    _recompute_stats(state, scan_path=state.get("scan_path"))
    validate_state_invariants(state)
    return resolved
