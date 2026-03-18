"""Scan merge/update operations for persisted issues state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "MergeScanOptions",
    "merge_scan",
]

from desloppify.base.registry import DETECTORS
from desloppify.engine._state.issue_semantics import ensure_work_item_semantics
from desloppify.engine._state.merge_history import (
    _append_scan_history,
    _build_merge_diff,
    _compute_suppression,
    _merge_scan_inputs,
    _record_scan_metadata,
)
from desloppify.engine._state.merge_issues import (
    verify_disappeared,
    find_suspect_detectors,
    upsert_issues,
)
from desloppify.engine._state.schema import (
    ScanDiff,
    StateModel,
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)


from desloppify.engine._state import _recompute_stats

from desloppify.base.registry import get_detector_meta


def _latest_trusted_assessment_import_timestamp(state: StateModel) -> str:
    """Return the newest trusted assessment-import timestamp, if present."""
    for raw_entry in reversed(state.get("assessment_import_audit", []) or []):
        if not isinstance(raw_entry, dict):
            continue
        if raw_entry.get("mode") not in {"trusted_internal", "attested_external"}:
            continue
        timestamp = str(raw_entry.get("timestamp", "")).strip()
        if timestamp:
            return timestamp
    return ""


def _preserve_fresh_assessment_on_reconcile(
    payload: dict[str, Any],
    *,
    previous_last_scan: str,
    latest_trusted_import_ts: str,
) -> bool:
    """Suppress immediate re-staling after a fresh trusted review import.

    A scan that runs directly after a trusted review import is reconciling the
    issue inventory up to the code state that was just reviewed. If the
    assessment was imported after the previous scan, we should not immediately
    invalidate it based on that older scan delta.
    """
    if previous_last_scan == "" or latest_trusted_import_ts == "":
        return False
    if latest_trusted_import_ts <= previous_last_scan:
        return False
    assessed_at = str(payload.get("assessed_at", "")).strip()
    if assessed_at == "":
        return False
    return assessed_at >= latest_trusted_import_ts


def _mark_stale_on_mechanical_change(
    state: StateModel,
    *,
    changed_detectors: set[str],
    now: str,
    previous_last_scan: str,
) -> None:
    """Mark subjective assessments stale when mechanical issues change.

    Only marks dimensions that already have an assessment — doesn't create
    new entries for dimensions that have never been reviewed.
    """
    assessments = state.get("subjective_assessments")
    if not isinstance(assessments, dict) or not assessments:
        return

    affected_dims: set[str] = set()
    for detector in changed_detectors:
        meta = DETECTORS.get(detector)
        if meta is None or not meta.marks_dims_stale:
            continue
        det_meta = get_detector_meta(detector)
        dims = det_meta.subjective_dimensions if det_meta else ()
        if dims:
            affected_dims.update(dims)
            continue
        # Safety fallback for newly added "marks_dims_stale" detectors that
        # have not declared fine-grained dimension mappings yet.
        affected_dims.update(
            dim
            for dim in assessments
            if isinstance(dim, str) and dim.strip()
        )

    if not affected_dims:
        return

    latest_trusted_import_ts = _latest_trusted_assessment_import_timestamp(state)
    for dimension in sorted(affected_dims):
        if dimension not in assessments:
            continue
        payload = assessments[dimension]
        if not isinstance(payload, dict):
            continue
        # Don't overwrite if already stale
        if payload.get("needs_review_refresh"):
            continue
        if _preserve_fresh_assessment_on_reconcile(
            payload,
            previous_last_scan=previous_last_scan,
            latest_trusted_import_ts=latest_trusted_import_ts,
        ):
            continue
        payload["needs_review_refresh"] = True
        payload["refresh_reason"] = "mechanical_issues_changed"
        payload["stale_since"] = now


@dataclass
class MergeScanOptions:
    """Configuration bundle for merging a scan into persisted state."""

    lang: str | None = None
    scan_path: str | None = None
    force_resolve: bool = False
    exclude: tuple[str, ...] = ()
    potentials: dict[str, int] | None = None
    merge_potentials: bool = False
    codebase_metrics: dict[str, Any] | None = None
    include_slow: bool = True
    ignore: list[str] | None = None
    subjective_integrity_target: float | None = None
    project_root: str | None = None
    zone_map: Any | None = None


def merge_scan(
    state: StateModel,
    current_issues: list[dict],
    options: MergeScanOptions | None = None,
) -> ScanDiff:
    """Merge a fresh scan into existing state and return a diff summary."""
    ensure_state_defaults(state)
    for issue in current_issues:
        if isinstance(issue, dict):
            ensure_work_item_semantics(issue)
    resolved_options = options or MergeScanOptions()

    previous_last_scan = str(state.get("last_scan", "") or "")
    now = utc_now()
    _record_scan_metadata(
        state,
        now,
        lang=resolved_options.lang,
        include_slow=resolved_options.include_slow,
        scan_path=resolved_options.scan_path,
    )
    _merge_scan_inputs(
        state,
        lang=resolved_options.lang,
        potentials=resolved_options.potentials,
        merge_potentials=resolved_options.merge_potentials,
        codebase_metrics=resolved_options.codebase_metrics,
    )

    existing = state["work_items"]
    ignore_patterns = (
        resolved_options.ignore
        if resolved_options.ignore is not None
        else state.get("config", {}).get("ignore", [])
    )
    current_ids, new_count, reopened_count, current_by_detector, ignored_count, upsert_changed = (
        upsert_issues(
            existing,
            current_issues,
            ignore_patterns,
            now,
            lang=resolved_options.lang,
        )
    )

    raw_issues = len(current_issues)
    suppressed_pct = _compute_suppression(raw_issues, ignored_count)

    ran_detectors = (
        set(resolved_options.potentials.keys())
        if resolved_options.potentials is not None
        else None
    )
    suspect_detectors = find_suspect_detectors(
        existing,
        current_by_detector,
        resolved_options.force_resolve,
        ran_detectors,
    )
    auto_resolved, skipped_other_lang, resolved_out_of_scope, resolve_changed = verify_disappeared(
        existing,
        current_ids,
        suspect_detectors,
        now,
        lang=resolved_options.lang,
        scan_path=resolved_options.scan_path,
        exclude=resolved_options.exclude,
        project_root=resolved_options.project_root,
        zone_map=resolved_options.zone_map,
    )

    # Mark subjective assessments stale when mechanical issues changed.
    changed_detectors = upsert_changed | resolve_changed
    if changed_detectors:
        _mark_stale_on_mechanical_change(
            state,
            changed_detectors=changed_detectors,
            now=now,
            previous_last_scan=previous_last_scan,
        )

    _recompute_stats(
        state,
        scan_path=resolved_options.scan_path,
        subjective_integrity_target=resolved_options.subjective_integrity_target,
    )
    _append_scan_history(
        state,
        now=now,
        lang=resolved_options.lang,
        new_count=new_count,
        auto_resolved=auto_resolved,
        ignored_count=ignored_count,
        raw_issues=raw_issues,
        suppressed_pct=suppressed_pct,
        ignore_pattern_count=len(ignore_patterns),
    )

    chronic_reopeners = [
        issue
        for issue in existing.values()
        if issue.get("reopen_count", 0) >= 2 and issue["status"] == "open"
    ]

    validate_state_invariants(state)
    return _build_merge_diff(
        new_count=new_count,
        auto_resolved=auto_resolved,
        reopened_count=reopened_count,
        current_ids=current_ids,
        suspect_detectors=suspect_detectors,
        chronic_reopeners=chronic_reopeners,
        skipped_other_lang=skipped_other_lang,
        resolved_out_of_scope=resolved_out_of_scope,
        ignored_count=ignored_count,
        ignore_pattern_count=len(ignore_patterns),
        raw_issues=raw_issues,
        suppressed_pct=suppressed_pct,
    )
