"""Objective dimension-based scoring system.

Groups detectors into dimensions (coherent aspects of code quality),
computes per-dimension pass rates from potentials, and produces a
tier-weighted overall health score.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Dimension:
    name: str
    tier: int
    detectors: list[str]


DIMENSIONS = [
    Dimension("Import hygiene",      1, ["unused"]),
    Dimension("Debug cleanliness",   1, ["logs"]),
    Dimension("API surface",         2, ["exports", "deprecated"]),
    Dimension("File health",         3, ["structural"]),
    Dimension("Component design",    3, ["props"]),
    Dimension("Coupling",            3, ["single_use", "coupling"]),
    Dimension("Organization",        3, ["orphaned", "flat_dirs", "naming"]),
    Dimension("Code quality",        3, ["smells", "react"]),
    Dimension("Duplication",         3, ["dupes"]),
    Dimension("Pattern consistency", 3, ["patterns"]),
    Dimension("Dependency health",   4, ["cycles"]),
]

TIER_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4}
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.7, "low": 0.3}

# Statuses that count as failures
_LENIENT_FAILURES = {"open"}
_STRICT_FAILURES = {"open", "wontfix"}


def merge_potentials(potentials_by_lang: dict) -> dict[str, int]:
    """Sum potentials across languages per detector."""
    merged: dict[str, int] = {}
    for lang_potentials in potentials_by_lang.values():
        for detector, count in lang_potentials.items():
            merged[detector] = merged.get(detector, 0) + count
    return merged


def _detector_pass_rate(
    detector: str,
    findings: dict,
    potential: int,
    *,
    strict: bool = False,
) -> tuple[float, int, float]:
    """Pass rate for one detector.

    Returns (pass_rate, issue_count, weighted_failures).
    Zero potential -> (1.0, 0, 0.0).
    """
    if potential <= 0:
        return 1.0, 0, 0.0

    failure_set = _STRICT_FAILURES if strict else _LENIENT_FAILURES
    weighted_failures = 0.0
    issue_count = 0
    for f in findings.values():
        if f.get("detector") != detector:
            continue
        if f["status"] in failure_set:
            weight = CONFIDENCE_WEIGHTS.get(f.get("confidence", "medium"), 0.7)
            weighted_failures += weight
            issue_count += 1

    pass_rate = max(0.0, (potential - weighted_failures) / potential)
    return pass_rate, issue_count, weighted_failures


def compute_dimension_scores(
    findings: dict,
    potentials: dict[str, int],
    *,
    strict: bool = False,
) -> dict[str, dict]:
    """Compute per-dimension scores from findings and potentials.

    Returns {dimension_name: {"score": float, "checks": int, "issues": int, "detectors": dict}}.
    Dimensions with no active detectors (all potentials = 0 or missing) are excluded.
    """
    results: dict[str, dict] = {}

    for dim in DIMENSIONS:
        detector_rates = []
        total_checks = 0
        total_issues = 0
        detector_detail = {}

        for det in dim.detectors:
            pot = potentials.get(det, 0)
            if pot <= 0:
                continue
            rate, issues, weighted = _detector_pass_rate(
                det, findings, pot, strict=strict)
            detector_rates.append(rate)
            total_checks += pot
            total_issues += issues
            detector_detail[det] = {
                "potential": pot, "pass_rate": rate,
                "issues": issues, "weighted_failures": weighted,
            }

        if not detector_rates:
            continue

        dim_score = sum(detector_rates) / len(detector_rates) * 100

        results[dim.name] = {
            "score": round(dim_score, 1),
            "tier": dim.tier,
            "checks": total_checks,
            "issues": total_issues,
            "detectors": detector_detail,
        }

    return results


def compute_objective_score(dimension_scores: dict) -> float:
    """Tier-weighted average of dimension scores."""
    if not dimension_scores:
        return 100.0

    weighted_sum = 0.0
    weight_total = 0.0
    for name, data in dimension_scores.items():
        tier = data["tier"]
        w = TIER_WEIGHTS.get(tier, 2)
        weighted_sum += data["score"] * w
        weight_total += w

    if weight_total == 0:
        return 100.0
    return round(weighted_sum / weight_total, 1)


def compute_score_impact(
    dimension_scores: dict,
    potentials: dict[str, int],
    detector: str,
    issues_to_fix: int,
) -> float:
    """Estimate score improvement from fixing N issues in a detector.

    Returns estimated point increase in the objective score.
    """
    # Find which dimension this detector belongs to
    target_dim = None
    for dim in DIMENSIONS:
        if detector in dim.detectors:
            target_dim = dim
            break
    if target_dim is None or target_dim.name not in dimension_scores:
        return 0.0

    pot = potentials.get(detector, 0)
    if pot <= 0:
        return 0.0

    dim_data = dimension_scores[target_dim.name]
    old_score = compute_objective_score(dimension_scores)

    # Simulate fixing: reduce weighted failures by issues_to_fix * avg_weight
    det_data = dim_data["detectors"].get(detector)
    if not det_data:
        return 0.0

    old_weighted = det_data["weighted_failures"]
    # Assume fixes are high-confidence (weight=1.0) — conservative estimate
    new_weighted = max(0.0, old_weighted - issues_to_fix * 1.0)
    new_rate = max(0.0, (pot - new_weighted) / pot)

    # Recompute dimension score with new rate
    other_rates = []
    for det in target_dim.detectors:
        if det == detector:
            continue
        d = dim_data["detectors"].get(det)
        if d:
            other_rates.append(d["pass_rate"])
    all_rates = other_rates + [new_rate]
    new_dim_score = sum(all_rates) / len(all_rates) * 100

    # Recompute overall with the new dimension score
    simulated = {k: dict(v) for k, v in dimension_scores.items()}
    simulated[target_dim.name] = {**dim_data, "score": round(new_dim_score, 1)}
    new_score = compute_objective_score(simulated)

    return round(new_score - old_score, 1)


def get_dimension_for_detector(detector: str) -> Dimension | None:
    """Look up which dimension a detector belongs to."""
    for dim in DIMENSIONS:
        if detector in dim.detectors:
            return dim
    return None
