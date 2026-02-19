"""Scan merge/update operations for persisted findings state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desloppify.engine.state_internal.merge_findings import (
    _auto_resolve_disappeared,
    find_suspect_detectors,
    upsert_findings,
)
from desloppify.engine.state_internal.merge_history import (
    _append_scan_history,
    _build_merge_diff,
    _compute_suppression,
    _merge_scan_inputs,
    _record_scan_metadata,
)
from desloppify.engine.state_internal.schema import (
    ScanDiff,
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)
from desloppify.engine.state_internal.scoring import _recompute_stats


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


def merge_scan(
    state: dict,
    current_findings: list[dict],
    options: MergeScanOptions | None = None,
) -> ScanDiff:
    """Merge a fresh scan into existing state and return a diff summary."""
    ensure_state_defaults(state)
    resolved_options = options or MergeScanOptions()

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

    existing = state["findings"]
    ignore_patterns = (
        resolved_options.ignore
        if resolved_options.ignore is not None
        else state.get("config", {}).get("ignore", [])
    )
    current_ids, new_count, reopened_count, current_by_detector, ignored_count = (
        upsert_findings(
            existing,
            current_findings,
            ignore_patterns,
            now,
            lang=resolved_options.lang,
        )
    )

    raw_findings = len(current_findings)
    suppressed_pct = _compute_suppression(raw_findings, ignored_count)

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
    auto_resolved, skipped_other_lang, skipped_out_of_scope = _auto_resolve_disappeared(
        existing,
        current_ids,
        suspect_detectors,
        now,
        lang=resolved_options.lang,
        scan_path=resolved_options.scan_path,
        exclude=resolved_options.exclude,
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
        raw_findings=raw_findings,
        suppressed_pct=suppressed_pct,
        ignore_pattern_count=len(ignore_patterns),
    )

    chronic_reopeners = [
        finding
        for finding in existing.values()
        if finding.get("reopen_count", 0) >= 2 and finding["status"] == "open"
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
        skipped_out_of_scope=skipped_out_of_scope,
        ignored_count=ignored_count,
        ignore_pattern_count=len(ignore_patterns),
        raw_findings=raw_findings,
        suppressed_pct=suppressed_pct,
    )
