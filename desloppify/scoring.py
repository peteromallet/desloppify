"""Objective dimension-based scoring system.

Groups detectors into dimensions (coherent aspects of code quality),
computes per-dimension pass rates from potentials, and produces a
tier-weighted overall health score.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    Dimension("Organization",        3, ["orphaned", "flat_dirs", "naming", "facade"]),
    Dimension("Code quality",        3, ["smells", "react"]),
    Dimension("Duplication",         3, ["dupes"]),
    Dimension("Pattern consistency", 3, ["patterns"]),
    Dimension("Dependency health",   4, ["cycles"]),
]

TIER_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4}
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.7, "low": 0.3}

# Minimum checks for full dimension weight — below this, weight is dampened
# proportionally. Prevents small-sample dimensions from swinging the overall score.
MIN_SAMPLE = 200

# Detectors where potential = file count but findings are per-(file, sub-type).
# Per-file weighted failures are capped at 1.0 to match the file-based denominator.
_FILE_BASED_DETECTORS = {"smells"}

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

    For file-based detectors (potential = file count, multiple findings per file),
    per-file weighted failures are capped at 1.0 to prevent unit mismatch.
    """
    if potential <= 0:
        return 1.0, 0, 0.0

    failure_set = _STRICT_FAILURES if strict else _LENIENT_FAILURES
    issue_count = 0

    if detector in _FILE_BASED_DETECTORS:
        # Group by file, cap per-file weight at 1.0
        by_file: dict[str, float] = {}
        for f in findings.values():
            if f.get("detector") != detector:
                continue
            if f["status"] in failure_set:
                weight = CONFIDENCE_WEIGHTS.get(f.get("confidence", "medium"), 0.7)
                file_key = f.get("file", "")
                by_file[file_key] = by_file.get(file_key, 0) + weight
                issue_count += 1
        weighted_failures = sum(min(1.0, w) for w in by_file.values())
    else:
        weighted_failures = 0.0
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
        total_checks = 0
        total_issues = 0
        total_weighted_failures = 0.0
        detector_detail = {}

        for det in dim.detectors:
            pot = potentials.get(det, 0)
            if pot <= 0:
                continue
            rate, issues, weighted = _detector_pass_rate(
                det, findings, pot, strict=strict)
            total_checks += pot
            total_issues += issues
            total_weighted_failures += weighted
            detector_detail[det] = {
                "potential": pot, "pass_rate": rate,
                "issues": issues, "weighted_failures": weighted,
            }

        if total_checks <= 0:
            continue

        # Potential-weighted pass rate: treats the dimension as one big pool
        dim_score = max(0.0, (total_checks - total_weighted_failures) / total_checks) * 100

        results[dim.name] = {
            "score": round(dim_score, 1),
            "tier": dim.tier,
            "checks": total_checks,
            "issues": total_issues,
            "detectors": detector_detail,
        }

    return results


def compute_objective_score(dimension_scores: dict) -> float:
    """Tier-weighted average of dimension scores, dampened by sample size.

    Dimensions with fewer than MIN_SAMPLE checks get proportionally reduced
    weight, preventing small-sample dimensions from swinging the overall score.
    """
    if not dimension_scores:
        return 100.0

    weighted_sum = 0.0
    weight_total = 0.0
    for name, data in dimension_scores.items():
        tier = data["tier"]
        w = TIER_WEIGHTS.get(tier, 2)
        # Dampen weight for small-sample dimensions
        sample_factor = min(1.0, data.get("checks", 0) / MIN_SAMPLE)
        effective_weight = w * sample_factor
        weighted_sum += data["score"] * effective_weight
        weight_total += effective_weight

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

    # Recompute dimension score with potential-weighted averaging
    total_pot = 0
    total_new_wf = 0.0
    for det in target_dim.detectors:
        d = dim_data["detectors"].get(det)
        if not d:
            continue
        total_pot += d["potential"]
        if det == detector:
            total_new_wf += new_weighted
        else:
            total_new_wf += d["weighted_failures"]
    if total_pot <= 0:
        return 0.0
    new_dim_score = max(0.0, (total_pot - total_new_wf) / total_pot) * 100

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
