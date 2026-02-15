"""Objective dimension-based scoring system.

Groups detectors into dimensions (coherent aspects of code quality),
computes per-dimension pass rates from potentials, and produces a
tier-weighted overall health score.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import Confidence, Tier
from .zones import EXCLUDED_ZONE_VALUES


@dataclass
class Dimension:
    name: str
    tier: int
    detectors: list[str]


DIMENSIONS = [
    Dimension("File health",  3, ["structural"]),
    Dimension("Code quality", 3, [
        "unused", "logs", "exports", "deprecated", "props",
        "smells", "react", "dict_keys", "global_mutable_config",
        "orphaned", "flat_dirs", "naming", "facade", "stale_exclude",
        "patterns", "single_use", "coupling", "private_imports",
        "layer_violation",
    ]),
    Dimension("Duplication",  3, ["dupes"]),
    Dimension("Test health",  4, ["test_coverage", "subjective_review"]),
    Dimension("Security",     4, ["security", "cycles"]),
]

TIER_WEIGHTS = {Tier.AUTO_FIX: 1, Tier.QUICK_FIX: 2, Tier.JUDGMENT: 3, Tier.MAJOR_REFACTOR: 4}
CONFIDENCE_WEIGHTS = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.7, Confidence.LOW: 0.3}

# Minimum checks for full dimension weight — below this, weight is dampened
# proportionally. Prevents small-sample dimensions from swinging the overall score.
MIN_SAMPLE = 200

# Detectors where potential = file count but findings are per-(file, sub-type).
# Per-file weighted failures are capped at 1.0 to match the file-based denominator.
_FILE_BASED_DETECTORS = {"smells", "dict_keys", "test_coverage", "security", "review", "subjective_review"}


# Security findings are only excluded in generated/vendor zones (secrets in tests are real risks)
_SECURITY_EXCLUDED_ZONES = {"generated", "vendor"}

# Holistic review scoring: findings with file="." and detail.holistic=True
# bypass per-file caps and get a 10x weight multiplier.
HOLISTIC_MULTIPLIER = 10.0
HOLISTIC_POTENTIAL = 10

# Budget: subjective dimensions get this fraction of the overall score.
# Mechanical dimensions get the remainder. This decouples subjective weight
# from sample size and dimension count.
SUBJECTIVE_WEIGHT_FRACTION = 0.25

# Synthetic check count for subjective dimensions in the dimension_scores
# data structure. Used for pass_rate/weighted_failures display consistency
# only — does NOT affect overall score weight (that's controlled by
# SUBJECTIVE_WEIGHT_FRACTION).
SUBJECTIVE_CHECKS = 10

# Backward-compatible alias
ASSESSMENT_CHECKS = SUBJECTIVE_CHECKS

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


def _iter_failed_findings(
    detector: str, findings: dict, failure_set: set, excluded_zones: set,
):
    """Yield findings that are failed and in-scope for a detector."""
    for f in findings.values():
        if f.get("detector") != detector:
            continue
        if f.get("zone", "production") in excluded_zones:
            continue
        if f["status"] in failure_set:
            yield f


def _finding_weight(f: dict, use_loc_weight: bool) -> float:
    """Compute the scoring weight for a single finding."""
    if use_loc_weight:
        return f.get("detail", {}).get("loc_weight", 1.0)
    return CONFIDENCE_WEIGHTS.get(f.get("confidence", "medium"), 0.7)


def _file_based_failures(
    detector: str, findings: dict, failure_set: set, excluded_zones: set,
) -> tuple[int, float]:
    """Accumulate weighted failures for file-based detectors.

    Groups by file and caps per-file weight at 1.0 (or loc_weight for
    test_coverage). Holistic findings bypass caps with a 10x multiplier.
    Returns (issue_count, weighted_failures).
    """
    use_loc_weight = (detector == "test_coverage")
    by_file: dict[str, float] = {}
    file_cap: dict[str, float] = {}
    holistic_sum = 0.0
    issue_count = 0

    for f in _iter_failed_findings(detector, findings, failure_set, excluded_zones):
        # Holistic findings: no per-file cap, 10x multiplier
        if f.get("file") == "." and f.get("detail", {}).get("holistic"):
            holistic_sum += _finding_weight(f, False) * HOLISTIC_MULTIPLIER
            issue_count += 1
            continue

        weight = _finding_weight(f, use_loc_weight)
        file_key = f.get("file", "")
        by_file[file_key] = by_file.get(file_key, 0) + weight
        if use_loc_weight and file_key not in file_cap:
            file_cap[file_key] = weight
        issue_count += 1

    if use_loc_weight:
        weighted = sum(min(w, file_cap.get(fk, w)) for fk, w in by_file.items())
    else:
        weighted = sum(min(1.0, w) for w in by_file.values())
    return issue_count, weighted + holistic_sum


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
    excluded_zones = _SECURITY_EXCLUDED_ZONES if detector == "security" else EXCLUDED_ZONE_VALUES

    if detector in _FILE_BASED_DETECTORS:
        issue_count, weighted_failures = _file_based_failures(
            detector, findings, failure_set, excluded_zones)
    else:
        weighted_failures = 0.0
        issue_count = 0
        for f in _iter_failed_findings(detector, findings, failure_set, excluded_zones):
            weighted_failures += CONFIDENCE_WEIGHTS.get(f.get("confidence", "medium"), 0.7)
            issue_count += 1

    pass_rate = max(0.0, (potential - weighted_failures) / potential)
    return pass_rate, issue_count, weighted_failures


def compute_dimension_scores(
    findings: dict,
    potentials: dict[str, int],
    *,
    strict: bool = False,
    subjective_assessments: dict | None = None,
    review_assessments: dict | None = None,
) -> dict[str, dict]:
    """Compute per-dimension scores from findings and potentials.

    Returns {dimension_name: {"score": float, "checks": int, "issues": int, "detectors": dict}}.
    Dimensions with no active detectors (all potentials = 0 or missing) are excluded.

    If *subjective_assessments* is provided, each assessed dimension becomes a
    first-class scoring dimension (tier 4) with score driven by the assessment,
    not by findings.

    *review_assessments* is a deprecated alias for *subjective_assessments*.
    """
    # Support deprecated kwarg
    if subjective_assessments is None and review_assessments is not None:
        subjective_assessments = review_assessments
    results: dict[str, dict] = {}
    failure_set = _STRICT_FAILURES if strict else _LENIENT_FAILURES

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

    _append_subjective_dimensions(results, findings, subjective_assessments, failure_set)
    return results


_SHORT_NAMES: dict[str, str] = {
    "abstraction_fitness": "Abstraction Fit",
    "ai_generated_debt": "AI Generated Debt",
    "package_organization": "Package Org",
}


def _append_subjective_dimensions(
    results: dict, findings: dict,
    assessments: dict | None, failure_set: set,
) -> None:
    """Append subjective review dimensions to results dict (mutates results)."""
    from .review import DEFAULT_DIMENSIONS
    assessed = assessments or {}
    existing_lower = {k.lower() for k in results}

    all_dims = list(DEFAULT_DIMENSIONS)
    for dim_name in assessed:
        if dim_name not in DEFAULT_DIMENSIONS:
            all_dims.append(dim_name)

    for dim_name in all_dims:
        is_default = dim_name in DEFAULT_DIMENSIONS
        assessment = assessed.get(dim_name)
        if not is_default and not assessment:
            continue

        display = _SHORT_NAMES.get(dim_name, dim_name.replace("_", " ").title())
        if display.lower() in existing_lower:
            display = f"{display} (subjective)"

        issue_count = sum(
            1 for f in findings.values()
            if f.get("detector") == "review"
            and f["status"] in failure_set
            and f.get("detail", {}).get("dimension") == dim_name
        )

        score = max(0, min(100, assessment.get("score", 0))) if assessment else 0.0
        pass_rate = score / 100.0

        results[display] = {
            "score": round(float(score), 1),
            "tier": 4,
            "checks": SUBJECTIVE_CHECKS,
            "issues": issue_count,
            "detectors": {"subjective_assessment": {
                "potential": SUBJECTIVE_CHECKS,
                "pass_rate": round(pass_rate, 4),
                "issues": issue_count,
                "weighted_failures": round(SUBJECTIVE_CHECKS * (1 - pass_rate), 4),
            }},
        }


def compute_objective_score(dimension_scores: dict) -> float:
    """Budget-weighted blend of mechanical and subjective dimension scores.

    Mechanical dimensions use sample-dampened tier weights.
    Subjective dimensions use tier weights without dampening (they are
    holistic judgments, not statistical samples).
    The two pools are blended at a fixed ratio (SUBJECTIVE_WEIGHT_FRACTION)
    so that adding/removing subjective dimensions redistributes weight
    within the budget rather than changing the budget.
    """
    if not dimension_scores:
        return 100.0

    mech_sum = 0.0
    mech_weight = 0.0
    subj_sum = 0.0
    subj_weight = 0.0

    for _name, data in dimension_scores.items():
        tier = data["tier"]
        w = TIER_WEIGHTS.get(tier, 2)
        is_subjective = "subjective_assessment" in data.get("detectors", {})

        if is_subjective:
            subj_sum += data["score"] * w
            subj_weight += w
        else:
            sample_factor = min(1.0, data.get("checks", 0) / MIN_SAMPLE)
            effective = w * sample_factor
            mech_sum += data["score"] * effective
            mech_weight += effective

    mech_avg = (mech_sum / mech_weight) if mech_weight > 0 else 100.0
    subj_avg = (subj_sum / subj_weight) if subj_weight > 0 else None

    # Pure mechanical if no subjective dimensions assessed
    if subj_avg is None:
        return round(mech_avg, 1)

    # Pure subjective if no mechanical dimensions active
    if mech_weight == 0:
        return round(subj_avg, 1)

    # Budget blend
    blended = mech_avg * (1 - SUBJECTIVE_WEIGHT_FRACTION) + subj_avg * SUBJECTIVE_WEIGHT_FRACTION
    return round(blended, 1)


def compute_score_impact(
    dimension_scores: dict,
    potentials: dict[str, int],
    detector: str,
    issues_to_fix: int,
) -> float:
    """Estimate score improvement from fixing N issues in a detector.

    Returns estimated point increase in the objective score.
    """
    # Find which dimension this detector belongs to.
    # Subjective dimensions (detector="subjective_assessment") have no entry
    # in DIMENSIONS — score changes only via re-review, so impact is 0.
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
