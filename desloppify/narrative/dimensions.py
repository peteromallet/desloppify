"""Dimension analysis and debt computation."""

from __future__ import annotations

from ._constants import STRUCTURAL_MERGE


def _analyze_dimensions(dim_scores: dict, history: list[dict],
                        state: dict) -> dict:
    """Compute per-dimension structured analysis."""
    if not dim_scores:
        return {}

    from ..scoring import merge_potentials, compute_score_impact

    potentials = merge_potentials(state.get("potentials", {}))

    # Lowest dimensions (by strict score)
    sorted_dims = sorted(
        ((name, ds) for name, ds in dim_scores.items() if ds.get("strict", ds["score"]) < 100),
        key=lambda x: x[1].get("strict", x[1]["score"]),
    )
    lowest = []
    for name, ds in sorted_dims[:3]:
        strict = ds.get("strict", ds["score"])
        issues = ds["issues"]
        # Estimate impact from the dominant detector
        impact = 0.0
        for det, det_data in ds.get("detectors", {}).items():
            if det_data.get("issues", 0) > 0:
                imp = compute_score_impact(
                    {k: {"score": v["score"], "tier": v.get("tier", 3),
                          "detectors": v.get("detectors", {})}
                     for k, v in dim_scores.items()},
                    potentials, det, det_data["issues"])
                impact = max(impact, imp)
        # Subjective dimensions have "subjective_assessment" as their only detector
        is_subjective = "subjective_assessment" in ds.get("detectors", {})
        entry = {"name": name, "strict": round(strict, 1),
                 "issues": issues, "impact": round(impact, 1)}
        if is_subjective:
            entry["subjective"] = True
            entry["impact_description"] = "re-review to improve"
        lowest.append(entry)

    # Biggest gap dimensions (lenient - strict)
    biggest_gap = []
    for name, ds in dim_scores.items():
        lenient = ds["score"]
        strict = ds.get("strict", lenient)
        gap = lenient - strict
        if gap > 1.0:
            from ..state import path_scoped_findings
            scoped = path_scoped_findings(state.get("findings", {}), state.get("scan_path"))
            wontfix_count = sum(
                1 for f in scoped.values()
                if f["status"] == "wontfix" and _finding_in_dimension(f, name, dim_scores)
            )
            biggest_gap.append({"name": name, "lenient": round(lenient, 1),
                                "strict": round(strict, 1), "gap": round(gap, 1),
                                "wontfix_count": wontfix_count})
    biggest_gap.sort(key=lambda x: -x["gap"])

    # Stagnant dimensions (strict unchanged for 3+ scans)
    stagnant = []
    if len(history) >= 3:
        for name in dim_scores:
            scores = []
            for h in history[-5:]:
                hdim = (h.get("dimension_scores") or {}).get(name)
                if hdim:
                    scores.append(hdim.get("strict", hdim.get("score")))
            if len(scores) >= 3 and all(s is not None for s in scores):
                if max(scores) - min(scores) <= 0.5:
                    stagnant.append({"name": name,
                                     "strict": round(dim_scores[name].get("strict", dim_scores[name]["score"]), 1),
                                     "stuck_scans": len(scores)})

    return {
        "lowest_dimensions": lowest,
        "biggest_gap_dimensions": biggest_gap[:3],
        "stagnant_dimensions": stagnant,
    }


def _finding_in_dimension(finding: dict, dim_name: str, dim_scores: dict) -> bool:
    """Check if a finding's detector belongs to a dimension."""
    from ..scoring import DIMENSIONS
    det = finding.get("detector", "")
    if det in STRUCTURAL_MERGE:
        det = "structural"
    for dim in DIMENSIONS:
        if dim.name == dim_name and det in dim.detectors:
            return True
    return False


def _analyze_debt(dim_scores: dict, findings: dict,
                  history: list[dict]) -> dict:
    """Compute wontfix debt analysis."""
    # Count wontfix
    wontfix_count = sum(1 for f in findings.values() if f["status"] == "wontfix")

    # Compute gap per dimension
    worst_dim = None
    worst_gap = 0.0
    overall_lenient = 0.0
    overall_strict = 0.0
    if dim_scores:
        from ..scoring import TIER_WEIGHTS
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
            hs = h.get("strict_score", h.get("objective_strict"))
            hl = h.get("overall_score", h.get("objective_score"))
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
