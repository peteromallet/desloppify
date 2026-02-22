"""Dimension analysis and debt computation."""

from __future__ import annotations

from desloppify.intelligence.narrative._constants import STRUCTURAL_MERGE
from desloppify.scoring import (
    DIMENSIONS,
    TIER_WEIGHTS,
    compute_score_impact,
    merge_potentials,
)
from desloppify.state import path_scoped_findings


def _analyze_dimensions(dim_scores: dict, history: list[dict], state: dict) -> dict:
    """Compute per-dimension structured analysis."""
    if not dim_scores:
        return {}

    potentials = merge_potentials(state.get("potentials", {}))
    return {
        "lowest_dimensions": _lowest_dimensions(dim_scores, potentials),
        "biggest_gap_dimensions": _biggest_gap_dimensions(dim_scores, state)[:3],
        "stagnant_dimensions": _stagnant_dimensions(dim_scores, history),
    }


def _lowest_dimensions(dim_scores: dict, potentials: dict) -> list[dict]:
    """Build summary entries for the lowest strict-scoring dimensions."""
    sorted_dims = sorted(
        (
            (name, ds)
            for name, ds in dim_scores.items()
            if ds.get("strict", ds["score"]) < 100
        ),
        key=lambda item: item[1].get("strict", item[1]["score"]),
    )

    lowest = []
    for name, ds in sorted_dims[:3]:
        strict = ds.get("strict", ds["score"])
        issues = ds["issues"]
        impact = _dominant_detector_impact(
            dim_scores=dim_scores,
            detectors=ds.get("detectors", {}),
            potentials=potentials,
        )
        is_subjective = "subjective_assessment" in ds.get("detectors", {})
        entry = {
            "name": name,
            "strict": round(strict, 1),
            "issues": issues,
            "impact": round(impact, 1),
        }
        if is_subjective:
            entry["subjective"] = True
            entry["impact_description"] = "re-review to improve"
        lowest.append(entry)
    return lowest


def _biggest_gap_dimensions(dim_scores: dict, state: dict) -> list[dict]:
    """Build summary entries for dimensions with the biggest strict gap."""
    biggest_gap = []
    scoped = path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")
    )
    for name, ds in dim_scores.items():
        lenient = ds["score"]
        strict = ds.get("strict", lenient)
        gap = lenient - strict
        if gap > 1.0:
            wontfix_count = sum(
                1
                for f in scoped.values()
                if f["status"] == "wontfix"
                and _finding_in_dimension(f, name, dim_scores)
            )
            biggest_gap.append(
                {
                    "name": name,
                    "lenient": round(lenient, 1),
                    "strict": round(strict, 1),
                    "gap": round(gap, 1),
                    "wontfix_count": wontfix_count,
                }
            )
    biggest_gap.sort(key=lambda x: -x["gap"])
    return biggest_gap


def _stagnant_dimensions(dim_scores: dict, history: list[dict]) -> list[dict]:
    """Build summary entries for dimensions that have not moved recently."""
    if len(history) < 3:
        return []

    stagnant = []
    for name in dim_scores:
        scores = _recent_dimension_strict_scores(name, history)
        if len(scores) < 3 or max(scores) - min(scores) > 0.5:
            continue
        stagnant.append(
            {
                "name": name,
                "strict": round(dim_scores[name].get("strict", dim_scores[name]["score"]), 1),
                "stuck_scans": len(scores),
            }
        )
    return stagnant


def _recent_dimension_strict_scores(name: str, history: list[dict]) -> list[float]:
    """Collect recent strict score samples for one dimension."""
    scores: list[float] = []
    for history_entry in history[-5:]:
        dim_entry = (history_entry.get("dimension_scores") or {}).get(name)
        if not dim_entry:
            continue
        strict_value = dim_entry.get("strict", dim_entry.get("score"))
        if strict_value is not None:
            scores.append(float(strict_value))
    return scores


def _dominant_detector_impact(
    *,
    dim_scores: dict,
    detectors: dict,
    potentials: dict,
) -> float:
    """Estimate impact using the most consequential detector in a dimension."""
    normalized_scores = {
        key: {
            "score": value["score"],
            "tier": value.get("tier", 3),
            "detectors": value.get("detectors", {}),
        }
        for key, value in dim_scores.items()
    }
    impact = 0.0
    for detector_name, detector_data in detectors.items():
        issue_count = int(detector_data.get("issues", 0) or 0)
        if issue_count <= 0:
            continue
        detector_impact = compute_score_impact(
            normalized_scores,
            potentials,
            detector_name,
            issue_count,
        )
        impact = max(impact, detector_impact)
    return impact


def _finding_in_dimension(finding: dict, dim_name: str, dim_scores: dict) -> bool:
    """Check if a finding's detector belongs to a dimension."""
    detector = finding.get("detector", "")
    if detector in STRUCTURAL_MERGE:
        detector = "structural"
    for dim in DIMENSIONS:
        if dim.name == dim_name and detector in dim.detectors:
            return True
    return False


def _analyze_debt(dim_scores: dict, findings: dict, history: list[dict]) -> dict:
    """Compute wontfix debt analysis."""
    # Count wontfix
    wontfix_count = sum(1 for f in findings.values() if f["status"] == "wontfix")

    # Compute gap per dimension
    worst_dim = None
    worst_gap = 0.0
    overall_lenient = 0.0
    overall_strict = 0.0
    if dim_scores:
        w_sum_l = 0.0
        w_sum_s = 0.0
        w_total = 0.0
        for name, ds in dim_scores.items():
            tier = ds.get("tier", 3)
            w = TIER_WEIGHTS.get(tier, 2)
            w_sum_l += ds["score"] * w
            w_sum_s += ds.get("strict", ds["score"]) * w
            w_total += w
            gap = ds["score"] - ds.get("strict", ds["score"])
            if gap > worst_gap:
                worst_gap = gap
                worst_dim = name
        if w_total > 0:
            overall_lenient = round(w_sum_l / w_total, 1)
            overall_strict = round(w_sum_s / w_total, 1)

    overall_gap = round(overall_lenient - overall_strict, 1)

    # Trend from history
    trend = "stable"
    if len(history) >= 3:
        gaps = []
        for h in history[-5:]:
            hs = h.get("strict_score")
            hl = h.get("overall_score")
            if hs is not None and hl is not None:
                gaps.append(hl - hs)
        if len(gaps) >= 2:
            if gaps[-1] > gaps[0] + 0.5:
                trend = "growing"
            elif gaps[-1] < gaps[0] - 0.5:
                trend = "shrinking"

    return {
        "overall_gap": overall_gap,
        "wontfix_count": wontfix_count,
        "worst_dimension": worst_dim,
        "worst_gap": round(worst_gap, 1),
        "trend": trend,
    }
