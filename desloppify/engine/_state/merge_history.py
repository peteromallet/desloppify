"""Scan metadata/history helpers for merge operations."""

from __future__ import annotations

from desloppify.base.tooling import compute_tool_hash
from desloppify.engine._state.schema import ScanDiff, StateModel


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


def _compute_suppression(raw_issues: int, ignored_count: int) -> float:
    return round(ignored_count / raw_issues * 100, 1) if raw_issues else 0.0


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


def _score_confidence_snapshot(confidence: dict | None) -> dict[str, object] | None:
    if not isinstance(confidence, dict):
        return None
    status = confidence.get("status")
    if status is None:
        return None
    detectors = confidence.get("detectors", [])
    detector_count = len(detectors) if isinstance(detectors, list) else 0
    dimensions = confidence.get("dimensions", [])
    dimension_count = len(dimensions) if isinstance(dimensions, list) else 0
    return {
        "status": status,
        "confidence": confidence.get("confidence"),
        "detector_count": detector_count,
        "dimension_count": dimension_count,
    }


def _scan_score_snapshot(state: StateModel) -> dict[str, object]:
    """Copy canonical score fields into one scan-history snapshot."""
    return {
        "strict_score": state.get("strict_score"),
        "verified_strict_score": state.get("verified_strict_score"),
        "objective_score": state.get("objective_score"),
        "overall_score": state.get("overall_score"),
        "open": state["stats"]["open"],
        "subjective_integrity": _subjective_integrity_snapshot(
            state.get("subjective_integrity")
        ),
        "score_confidence": _score_confidence_snapshot(state.get("score_confidence")),
        "dimension_scores": {
            name: {"score": ds["score"], "strict": ds.get("strict", ds["score"])}
            for name, ds in state.get("dimension_scores", {}).items()
        }
        if state.get("dimension_scores")
        else None,
    }


def refresh_scan_history_scores(state: StateModel) -> None:
    """Update only this scan's history snapshot after disposition reconciliation."""
    current_scan = state.get("last_scan")
    history = state.get("scan_history")
    if not current_scan or not isinstance(history, list) or not history:
        return
    latest = history[-1]
    if isinstance(latest, dict) and latest.get("timestamp") == current_scan:
        latest.update(_scan_score_snapshot(state))


def _append_scan_history(
    state: StateModel,
    *,
    now: str,
    lang: str | None,
    new_count: int,
    auto_resolved: int,
    ignored_count: int,
    raw_issues: int,
    suppressed_pct: float,
    ignore_pattern_count: int,
) -> None:
    history = state.setdefault("scan_history", [])
    history.append(
        {
            "timestamp": now,
            "lang": lang,
            **_scan_score_snapshot(state),
            "diff_new": new_count,
            "diff_resolved": auto_resolved,
            "ignored": ignored_count,
            "raw_issues": raw_issues,
            "suppressed_pct": suppressed_pct,
            "ignore_patterns": ignore_pattern_count,
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
    resolved_out_of_scope: int,
    ignored_count: int,
    ignore_pattern_count: int,
    raw_issues: int,
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
        "resolved_out_of_scope": resolved_out_of_scope,
        "ignored": ignored_count,
        "ignore_patterns": ignore_pattern_count,
        "raw_issues": raw_issues,
        "suppressed_pct": suppressed_pct,
    }


__all__ = [
    "_append_scan_history",
    "_build_merge_diff",
    "_compute_suppression",
    "_merge_scan_inputs",
    "_record_scan_metadata",
    "refresh_scan_history_scores",
    "_subjective_integrity_snapshot",
]
