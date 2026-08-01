"""Shared enrich/sense-check quality evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..review_coverage import cluster_issue_ids
from .enrich_checks import (
    _steps_missing_issue_refs,
    _steps_referencing_skipped_issues,
    _steps_with_bad_paths,
    _steps_with_vague_detail,
    _steps_without_effort,
    _underspecified_steps,
)

Severity = Literal["failure", "warning"]


@dataclass(frozen=True)
class EnrichQualityIssue:
    """Structured enrich-quality issue with severity and source rows."""

    code: str
    total: int
    rows: list[tuple]
    message: str
    severity: Severity


@dataclass(frozen=True)
class EnrichQualityReport:
    """Structured enrich-quality result for stage flows, confirmations, and runners."""

    failures: list[EnrichQualityIssue]
    warnings: list[EnrichQualityIssue]

    def failure(self, code: str) -> EnrichQualityIssue | None:
        for issue in self.failures:
            if issue.code == code:
                return issue
        return None

    def warning(self, code: str) -> EnrichQualityIssue | None:
        for issue in self.warnings:
            if issue.code == code:
                return issue
        return None


def _append_issue(
    issues: list[EnrichQualityIssue],
    *,
    code: str,
    total: int,
    rows: list[tuple],
    message: str,
    severity: Severity,
) -> None:
    if total <= 0:
        return
    issues.append(
        EnrichQualityIssue(
            code=code,
            total=total,
            rows=rows,
            message=message,
            severity=severity,
        )
    )


def _active_cluster_names(plan: dict, triage_issue_ids: set[str]) -> set[str]:
    """Return cluster names that overlap with the current triage cycle's issue IDs."""
    return {
        name
        for name, cluster in plan.get("clusters", {}).items()
        if not cluster_issue_ids(cluster)
        or set(cluster_issue_ids(cluster)) & triage_issue_ids
    }


def _scoped_plan(plan: dict, triage_issue_ids: set[str] | None) -> dict:
    """Narrow plan to only clusters relevant to the current triage cycle.

    ``None`` means no triage scoping is needed. An empty set is an explicitly
    frozen empty scope and therefore excludes historical clusters.
    """
    if triage_issue_ids is None:
        return plan
    if not triage_issue_ids:
        return {**plan, "clusters": {}}
    active = _active_cluster_names(plan, triage_issue_ids)
    return {
        **plan,
        "clusters": {
            name: cluster
            for name, cluster in plan.get("clusters", {}).items()
            if name in active
        },
    }


def evaluate_enrich_quality(
    plan: dict,
    repo_root: Path,
    *,
    phase_label: str,
    bad_paths_severity: Severity,
    missing_effort_severity: Severity,
    include_missing_issue_refs: bool,
    include_vague_detail: bool,
    stale_issue_refs_severity: Severity | None,
    triage_issue_ids: set[str] | None = None,
) -> EnrichQualityReport:
    """Evaluate executor-readiness checks for enrich-level stage data."""
    plan = _scoped_plan(plan, triage_issue_ids)

    failures: list[EnrichQualityIssue] = []
    warnings: list[EnrichQualityIssue] = []
    sink = {"failure": failures, "warning": warnings}
    sense_suffix = f" after {phase_label}" if phase_label == "sense-check" else ""

    underspec = _underspecified_steps(plan)
    _append_issue(
        sink["failure"],
        code="underspecified",
        total=sum(n for _, n, _ in underspec),
        rows=underspec,
        message=f"{sum(n for _, n, _ in underspec)} step(s) still lack detail or issue_refs{sense_suffix}.",
        severity="failure",
    )

    bad_paths = _steps_with_bad_paths(plan, repo_root)
    total_bad_paths = sum(len(paths) for _, _, paths in bad_paths)
    bad_paths_message = (
        f"{total_bad_paths} file path(s) don't exist on disk{sense_suffix}."
        if phase_label == "sense-check"
        else f"{total_bad_paths} file path(s) in step details don't exist on disk."
    )
    _append_issue(
        sink[bad_paths_severity],
        code="bad_paths",
        total=total_bad_paths,
        rows=bad_paths,
        message=bad_paths_message,
        severity=bad_paths_severity,
    )

    missing_effort = _steps_without_effort(plan)
    total_missing_effort = sum(n for _, n, _ in missing_effort)
    missing_effort_message = (
        f"{total_missing_effort} step(s) have no effort tag{sense_suffix}."
        if phase_label == "sense-check"
        else f"{total_missing_effort} step(s) have no effort tag (trivial/small/medium/large)."
    )
    _append_issue(
        sink[missing_effort_severity],
        code="missing_effort",
        total=total_missing_effort,
        rows=missing_effort,
        message=missing_effort_message,
        severity=missing_effort_severity,
    )

    if include_missing_issue_refs:
        missing_refs = _steps_missing_issue_refs(plan)
        total_missing_refs = sum(n for _, n, _ in missing_refs)
        missing_refs_message = (
            f"{total_missing_refs} step(s) have no issue_refs{sense_suffix}."
            if phase_label == "sense-check"
            else f"{total_missing_refs} step(s) have no issue_refs for traceability."
        )
        _append_issue(
            sink["failure"],
            code="missing_issue_refs",
            total=total_missing_refs,
            rows=missing_refs,
            message=missing_refs_message,
            severity="failure",
        )

    if include_vague_detail:
        vague_detail = _steps_with_vague_detail(plan, repo_root)
        vague_message = (
            f"{len(vague_detail)} step(s) have vague detail{sense_suffix}."
            if phase_label == "sense-check"
            else (
                f"{len(vague_detail)} step(s) have vague detail (< 80 chars, no file paths). "
                "Executor-ready means: file path + specific instruction."
            )
        )
        _append_issue(
            sink["failure"],
            code="vague_detail",
            total=len(vague_detail),
            rows=vague_detail,
            message=vague_message,
            severity="failure",
        )

    if stale_issue_refs_severity is not None:
        stale_refs = _steps_referencing_skipped_issues(plan)
        total_stale_refs = sum(len(refs) for _, _, refs in stale_refs)
        _append_issue(
            sink[stale_issue_refs_severity],
            code="stale_issue_refs",
            total=total_stale_refs,
            rows=stale_refs,
            message=(
                f"{total_stale_refs} step issue_ref(s) point to skipped/wontfixed issues"
                f"{sense_suffix}. Remove stale refs."
            ),
            severity=stale_issue_refs_severity,
        )

    return EnrichQualityReport(failures=failures, warnings=warnings)


__all__ = ["EnrichQualityIssue", "EnrichQualityReport", "evaluate_enrich_quality"]
