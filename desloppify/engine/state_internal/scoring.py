"""State scoring, statistics, and suppression accounting."""

from __future__ import annotations

import importlib
from copy import deepcopy

from desloppify.engine.state_internal.filtering import path_scoped_findings
from desloppify.engine.state_internal.schema import ensure_state_defaults
from desloppify.intelligence.integrity.subjective import matches_target_score

_EMPTY_COUNTERS = ("open", "fixed", "auto_resolved", "wontfix", "false_positive")
_SUBJECTIVE_TARGET_RESET_THRESHOLD = 2


def _count_findings(findings: dict) -> tuple[dict[str, int], dict[int, dict[str, int]]]:
    """Tally per-status counters and per-tier breakdowns."""
    counters = dict.fromkeys(_EMPTY_COUNTERS, 0)
    tier_stats: dict[int, dict[str, int]] = {}

    for finding in findings.values():
        status = finding["status"]
        tier = finding.get("tier", 3)
        counters[status] = counters.get(status, 0) + 1
        tier_counter = tier_stats.setdefault(tier, dict.fromkeys(_EMPTY_COUNTERS, 0))
        tier_counter[status] = tier_counter.get(status, 0) + 1

    return counters, tier_stats


def _coerce_subjective_score(value: dict | float | int | str | None) -> float:
    """Normalize a subjective assessment score payload to a 0-100 float."""
    raw = value.get("score", 0) if isinstance(value, dict) else value
    try:
        score = float(raw)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(100.0, score))


def _subjective_target_matches(
    subjective_assessments: dict, *, target: float
) -> list[str]:
    """Return dimension keys whose subjective score matches the target band."""
    matches = [
        dimension
        for dimension, payload in subjective_assessments.items()
        if matches_target_score(_coerce_subjective_score(payload), target)
    ]
    return sorted(matches)


def _subjective_integrity_baseline(target: float | None) -> dict[str, object]:
    """Create baseline subjective-integrity metadata for scan/reporting output."""
    return {
        "status": "disabled" if target is None else "pass",
        "target_score": None if target is None else round(float(target), 2),
        "matched_count": 0,
        "matched_dimensions": [],
        "reset_dimensions": [],
    }


def _apply_subjective_integrity_policy(
    subjective_assessments: dict,
    *,
    target: float,
) -> tuple[dict, dict[str, object]]:
    """Apply anti-gaming penalties for subjective scores clustered on the target."""
    normalized_target = max(0.0, min(100.0, float(target)))
    matched_dimensions = _subjective_target_matches(
        subjective_assessments,
        target=normalized_target,
    )
    meta = _subjective_integrity_baseline(normalized_target)
    meta["matched_count"] = len(matched_dimensions)
    meta["matched_dimensions"] = matched_dimensions

    if len(matched_dimensions) < _SUBJECTIVE_TARGET_RESET_THRESHOLD:
        meta["status"] = "warn" if matched_dimensions else "pass"
        return subjective_assessments, meta

    adjusted = deepcopy(subjective_assessments)
    for dimension in matched_dimensions:
        payload = adjusted.get(dimension)
        if isinstance(payload, dict):
            payload["score"] = 0.0
            payload["integrity_penalty"] = "target_match_reset"
        else:
            adjusted[dimension] = {
                "score": 0.0,
                "integrity_penalty": "target_match_reset",
            }

    meta["status"] = "penalized"
    meta["reset_dimensions"] = matched_dimensions
    return adjusted, meta


def _update_objective_health(
    state: dict,
    findings: dict,
    *,
    subjective_integrity_target: float | None = None,
) -> None:
    """Compute canonical score trio from dimension scoring."""
    pots = state.get("potentials", {})
    if not pots:
        return

    scoring_mod = importlib.import_module("desloppify.scoring")

    merged = scoring_mod.merge_potentials(pots)
    if not merged:
        return

    subjective_assessments = state.get("subjective_assessments") or None
    integrity_target = (
        max(0.0, min(100.0, float(subjective_integrity_target)))
        if isinstance(subjective_integrity_target, int | float)
        else None
    )
    integrity_meta = _subjective_integrity_baseline(integrity_target)
    if subjective_assessments and integrity_target is not None:
        subjective_assessments, integrity_meta = _apply_subjective_integrity_policy(
            subjective_assessments,
            target=integrity_target,
        )
    state["subjective_integrity"] = integrity_meta

    has_active_checks = any((count or 0) > 0 for count in merged.values())
    if not has_active_checks and not subjective_assessments:
        state["dimension_scores"] = {}
        state["overall_score"] = 100.0
        state["objective_score"] = 100.0
        state["strict_score"] = 100.0
        state["verified_strict_score"] = 100.0
        return

    bundle = scoring_mod.compute_score_bundle(
        findings,
        merged,
        subjective_assessments=subjective_assessments,
    )
    lenient_scores = bundle.dimension_scores
    strict_scores = bundle.strict_dimension_scores

    state["dimension_scores"] = {
        name: dict(
            score=lenient_scores[name]["score"],
            strict_score=strict_scores[name]["score"],
            checks=lenient_scores[name]["checks"],
            issues=lenient_scores[name]["issues"],
            tier=lenient_scores[name]["tier"],
            detectors=lenient_scores[name].get("detectors", {}),
        )
        for name in lenient_scores
    }
    for data in state["dimension_scores"].values():
        data["strict"] = data["strict_score"]

    state["overall_score"] = bundle.overall_score
    state["objective_score"] = bundle.objective_score
    state["strict_score"] = bundle.strict_score
    state["verified_strict_score"] = bundle.verified_strict_score


def _recompute_stats(
    state: dict,
    scan_path: str | None = None,
    *,
    subjective_integrity_target: float | None = None,
) -> None:
    """Recompute stats and canonical health scores from findings."""
    ensure_state_defaults(state)
    findings = path_scoped_findings(state["findings"], scan_path)
    counters, tier_stats = _count_findings(findings)
    state["stats"] = {
        "total": sum(counters.values()),
        **counters,
        "by_tier": {
            str(tier): tier_counts for tier, tier_counts in sorted(tier_stats.items())
        },
    }
    _update_objective_health(
        state,
        findings,
        subjective_integrity_target=subjective_integrity_target,
    )


def _empty_suppression_metrics() -> dict[str, int | float]:
    return {
        "last_ignored": 0,
        "last_raw_findings": 0,
        "last_suppressed_pct": 0.0,
        "last_ignore_patterns": 0,
        "recent_scans": 0,
        "recent_ignored": 0,
        "recent_raw_findings": 0,
        "recent_suppressed_pct": 0.0,
    }


def suppression_metrics(state: dict, *, window: int = 5) -> dict[str, int | float]:
    """Summarize ignore suppression from recent scan history."""
    history = state.get("scan_history", [])
    if not history:
        return _empty_suppression_metrics()

    scans_with_suppression = [
        entry
        for entry in history
        if isinstance(entry, dict)
        and (
            "ignored" in entry
            or "raw_findings" in entry
            or "suppressed_pct" in entry
            or "ignore_patterns" in entry
        )
    ]
    if not scans_with_suppression:
        return _empty_suppression_metrics()

    recent = scans_with_suppression[-max(1, window) :]
    last = recent[-1]

    recent_ignored = sum(int(entry.get("ignored", 0) or 0) for entry in recent)
    recent_raw = sum(int(entry.get("raw_findings", 0) or 0) for entry in recent)
    recent_pct = round(recent_ignored / recent_raw * 100, 1) if recent_raw else 0.0

    last_ignored = int(last.get("ignored", 0) or 0)
    last_raw = int(last.get("raw_findings", 0) or 0)
    if "suppressed_pct" in last:
        last_pct = round(float(last.get("suppressed_pct") or 0.0), 1)
    else:
        last_pct = round(last_ignored / last_raw * 100, 1) if last_raw else 0.0

    return {
        "last_ignored": last_ignored,
        "last_raw_findings": last_raw,
        "last_suppressed_pct": last_pct,
        "last_ignore_patterns": int(last.get("ignore_patterns", 0) or 0),
        "recent_scans": len(recent),
        "recent_ignored": recent_ignored,
        "recent_raw_findings": recent_raw,
        "recent_suppressed_pct": recent_pct,
    }
