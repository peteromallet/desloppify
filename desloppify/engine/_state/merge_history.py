"""Scan metadata/history helpers for merge operations."""

from __future__ import annotations

from desloppify.engine._state.schema import ScanDiff, StateModel
from desloppify.utils import compute_tool_hash


def _record_scan_metadata(
    state: StateModel,
    now: str,
    *,
    lang: str | None,
    include_slow: bool,
    scan_path: str | None,
) -> None:
    state["last_scan"] = now
    state["scan_count"] = state.get("scan_count", 0) + 1
    state["tool_hash"] = compute_tool_hash()
    state["scan_path"] = scan_path
    if lang:
        state.setdefault("scan_completeness", {})[lang] = (
            "full" if include_slow else "fast"
        )


def _merge_scan_inputs(
    state: StateModel,
    *,
    lang: str | None,
    potentials: dict[str, int] | None,
    merge_potentials: bool,
    codebase_metrics: dict | None,
) -> None:
    if potentials is not None and lang:
        all_potentials = state.setdefault("potentials", {})
        if merge_potentials and isinstance(all_potentials.get(lang), dict):
            merged = dict(all_potentials[lang])
            merged.update(potentials)
            all_potentials[lang] = merged
        else:
            all_potentials[lang] = dict(potentials)

    if codebase_metrics is not None and lang:
        state.setdefault("codebase_metrics", {})[lang] = dict(codebase_metrics)


def _compute_suppression(raw_findings: int, ignored_count: int) -> float:
    return round(ignored_count / raw_findings * 100, 1) if raw_findings else 0.0


def _subjective_integrity_snapshot(integrity: dict | None) -> dict[str, object] | None:
    if not isinstance(integrity, dict):
        return None
    return {
        "status": integrity.get("status"),
        "matched_count": int(integrity.get("matched_count", 0) or 0),
        "reset_count": len(
            [
                key
                for key in integrity.get("reset_dimensions", [])
                if isinstance(key, str) and key
            ]
        ),
        "target_score": integrity.get("target_score"),
    }


def _append_scan_history(
    state: StateModel,
    *,
    now: str,
    lang: str | None,
    new_count: int,
    auto_resolved: int,
    ignored_count: int,
    raw_findings: int,
    suppressed_pct: float,
    ignore_pattern_count: int,
) -> None:
    history = state.setdefault("scan_history", [])
    history.append(
        {
            "timestamp": now,
            "lang": lang,
            "strict_score": state.get("strict_score"),
            "verified_strict_score": state.get("verified_strict_score"),
            "objective_score": state.get("objective_score"),
            "overall_score": state.get("overall_score"),
            "open": state["stats"]["open"],
            "diff_new": new_count,
            "diff_resolved": auto_resolved,
            "ignored": ignored_count,
            "raw_findings": raw_findings,
            "suppressed_pct": suppressed_pct,
            "ignore_patterns": ignore_pattern_count,
            "subjective_integrity": _subjective_integrity_snapshot(
                state.get("subjective_integrity")
            ),
            "dimension_scores": {
                name: {"score": ds["score"], "strict": ds.get("strict", ds["score"])}
                for name, ds in state.get("dimension_scores", {}).items()
            }
            if state.get("dimension_scores")
            else None,
        }
    )

    if len(history) > 20:
        state["scan_history"] = history[-20:]


def _build_merge_diff(
    *,
    new_count: int,
    auto_resolved: int,
    reopened_count: int,
    current_ids: set[str],
    suspect_detectors: set[str],
    chronic_reopeners: list[dict],
    skipped_other_lang: int,
    skipped_out_of_scope: int,
    ignored_count: int,
    ignore_pattern_count: int,
    raw_findings: int,
    suppressed_pct: float,
) -> ScanDiff:
    return {
        "new": new_count,
        "auto_resolved": auto_resolved,
        "reopened": reopened_count,
        "total_current": len(current_ids),
        "suspect_detectors": sorted(suspect_detectors) if suspect_detectors else [],
        "chronic_reopeners": chronic_reopeners,
        "skipped_other_lang": skipped_other_lang,
        "skipped_out_of_scope": skipped_out_of_scope,
        "ignored": ignored_count,
        "ignore_patterns": ignore_pattern_count,
        "raw_findings": raw_findings,
        "suppressed_pct": suppressed_pct,
    }


__all__ = [
    "_append_scan_history",
    "_build_merge_diff",
    "_compute_suppression",
    "_merge_scan_inputs",
    "_record_scan_metadata",
    "_subjective_integrity_snapshot",
]
