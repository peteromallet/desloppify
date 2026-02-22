"""Lightweight integrity helpers for subjective/review scoring.

This module intentionally lives outside ``desloppify.intelligence.review`` so command/state
paths can import it without loading the heavier review package.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from desloppify.engine._scoring.policy.core import (
    SUBJECTIVE_TARGET_MATCH_TOLERANCE,
    matches_target_score,
)

__all__ = [
    "SUBJECTIVE_TARGET_MATCH_TOLERANCE",
    "is_holistic_subjective_finding",
    "is_subjective_review_open",
    "matches_target_score",
    "subjective_review_open_breakdown",
    "unassessed_subjective_dimensions",
]


# ---------------------------------------------------------------------------
# Internal iteration helper
# ---------------------------------------------------------------------------


def _iter_findings(
    findings: Mapping[str, dict] | Iterable[dict],
) -> Iterable[tuple[str, dict]]:
    """Yield (finding_id, finding) pairs from mapping or iterable inputs."""
    if isinstance(findings, Mapping):
        for finding_id, finding in findings.items():
            if isinstance(finding, dict):
                yield str(finding_id), finding
        return

    for index, finding in enumerate(findings):
        if isinstance(finding, dict):
            yield str(index), finding


# ---------------------------------------------------------------------------
# Public helpers (formerly in integrity/review.py)
# ---------------------------------------------------------------------------


def is_subjective_review_open(finding: dict) -> bool:
    """Return True when a finding is an open subjective-review signal."""
    return (
        finding.get("status") == "open"
        and finding.get("detector") == "subjective_review"
    )


def is_holistic_subjective_finding(finding: dict, *, finding_id: str = "") -> bool:
    """Best-effort check for holistic subjective-review coverage findings."""
    candidate_id = str(finding.get("id") or finding_id or "")
    if "::holistic_unreviewed" in candidate_id or "::holistic_stale" in candidate_id:
        return True

    summary = str(finding.get("summary", "") or "").lower()
    if "holistic" in summary and "review" in summary:
        return True

    detail = finding.get("detail", {})
    return bool(detail.get("holistic"))


def subjective_review_open_breakdown(
    findings: Mapping[str, dict] | Iterable[dict],
) -> tuple[int, dict[str, int], dict[str, int]]:
    """Return open subjective count plus reason and holistic-reason breakdowns."""
    reason_counts: dict[str, int] = {}
    holistic_reason_counts: dict[str, int] = {}
    total = 0

    for finding_id, finding in _iter_findings(findings):
        if not is_subjective_review_open(finding):
            continue

        total += 1
        reason = str(finding.get("detail", {}).get("reason", "other") or "other")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

        if is_holistic_subjective_finding(finding, finding_id=finding_id):
            holistic_reason_counts[reason] = holistic_reason_counts.get(reason, 0) + 1

    return total, reason_counts, holistic_reason_counts


def unassessed_subjective_dimensions(dim_scores: dict | None) -> list[str]:
    """Return subjective dimension display names that are still 0% placeholders."""
    if not dim_scores:
        return []

    unassessed: list[str] = []
    for name, info in dim_scores.items():
        if "subjective_assessment" not in info.get("detectors", {}):
            continue
        strict_val = float(info.get("strict", info.get("score", 100.0)))
        issues = int(info.get("issues", 0))
        if strict_val <= 0.0 and issues == 0:
            unassessed.append(name)

    unassessed.sort()
    return unassessed
