"""State resolution operations (match + resolve)."""

from __future__ import annotations

import copy

from desloppify.engine.state_internal.filtering import _matches_pattern
from desloppify.engine.state_internal.schema import (
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)
from desloppify.engine.state_internal.scoring import _recompute_stats


def _coerce_assessment_score(value: object) -> float:
    """Normalize a subjective assessment score payload to a 0-100 float."""
    raw = value.get("score", 0) if isinstance(value, dict) else value
    try:
        score = float(raw)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(100.0, score))


def _reset_subjective_assessments_after_review_fix(
    state: dict,
    *,
    status: str,
    resolved_findings: list[dict],
    now: str,
) -> None:
    """Invalidate subjective assessments touched by fixed review findings."""
    if status != "fixed":
        return

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
        prior_score = _coerce_assessment_score(payload)
        if prior_score <= 0.0:
            continue

        if isinstance(payload, dict):
            payload["score"] = 0.0
            payload["assessed_at"] = now
            payload["needs_review_refresh"] = True
            payload["refresh_reason"] = "review_finding_resolved"
        else:
            assessments[dimension] = {
                "score": 0.0,
                "assessed_at": now,
                "needs_review_refresh": True,
                "refresh_reason": "review_finding_resolved",
            }


def match_findings(
    state: dict, pattern: str, status_filter: str = "open"
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
    state: dict,
    pattern: str,
    status: str,
    note: str | None = None,
    attestation: str | None = None,
) -> list[str]:
    """Resolve open findings matching pattern and return resolved IDs."""
    ensure_state_defaults(state)
    now = utc_now()
    resolved: list[str] = []
    resolved_findings: list[dict] = []

    for finding in match_findings(state, pattern, status_filter="open"):
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
        finding.update(
            status=status,
            note=note,
            resolved_at=now,
            suppressed=False,
            suppressed_at=None,
            suppression_pattern=None,
            resolution_attestation={
                "kind": "manual",
                "text": attestation,
                "attested_at": now,
                "scan_verified": False,
            },
            **extra_updates,
        )
        resolved.append(finding["id"])
        resolved_findings.append(finding)

    _reset_subjective_assessments_after_review_fix(
        state,
        status=status,
        resolved_findings=resolved_findings,
        now=now,
    )

    _recompute_stats(state, scan_path=state.get("scan_path"))
    validate_state_invariants(state)
    return resolved
