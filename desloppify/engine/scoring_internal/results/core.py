"""Dimension and overall scoring aggregation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.engine.scoring_internal.detection import detector_stats_by_mode
from desloppify.engine.scoring_internal.policy.core import (
    DETECTOR_SCORING_POLICIES,
    DIMENSIONS,
    DIMENSIONS_BY_NAME,
    FAILURE_STATUSES_BY_MODE,
    MECHANICAL_DIMENSION_WEIGHTS,
    MECHANICAL_WEIGHT_FRACTION,
    MIN_SAMPLE,
    SCORING_MODES,
    SUBJECTIVE_DIMENSION_WEIGHTS,
    SUBJECTIVE_WEIGHT_FRACTION,
    ScoreMode,
)
from desloppify.engine.scoring_internal.subjective.core import (
    append_subjective_dimensions,
)


@dataclass(frozen=True)
class ScoreBundle:
    dimension_scores: dict[str, dict]
    strict_dimension_scores: dict[str, dict]
    verified_strict_dimension_scores: dict[str, dict]
    overall_score: float
    objective_score: float
    strict_score: float
    verified_strict_score: float


def compute_dimension_scores_by_mode(
    findings: dict,
    potentials: dict[str, int],
    *,
    subjective_assessments: dict | None = None,
    allowed_subjective_dimensions: set[str] | None = None,
) -> dict[ScoreMode, dict[str, dict]]:
    """Compute dimension scores for lenient/strict/verified_strict in one pass."""
    results: dict[ScoreMode, dict[str, dict]] = {mode: {} for mode in SCORING_MODES}

    for dim in DIMENSIONS:
        totals = {
            mode: {
                "checks": 0,
                "issues": 0,
                "weighted_failures": 0.0,
                "detectors": {},
            }
            for mode in SCORING_MODES
        }

        for detector in dim.detectors:
            potential = potentials.get(detector, 0)
            if potential <= 0:
                continue

            detector_stats = detector_stats_by_mode(detector, findings, potential)
            for mode in SCORING_MODES:
                pass_rate, issues, weighted = detector_stats[mode]
                totals[mode]["checks"] += potential
                totals[mode]["issues"] += issues
                totals[mode]["weighted_failures"] += weighted
                totals[mode]["detectors"][detector] = {
                    "potential": potential,
                    "pass_rate": pass_rate,
                    "issues": issues,
                    "weighted_failures": weighted,
                }

        for mode in SCORING_MODES:
            total_checks = totals[mode]["checks"]
            if total_checks <= 0:
                continue
            dim_score = (
                max(
                    0.0,
                    (total_checks - totals[mode]["weighted_failures"]) / total_checks,
                )
                * 100
            )
            results[mode][dim.name] = {
                "score": round(dim_score, 1),
                "tier": dim.tier,
                "checks": total_checks,
                "issues": totals[mode]["issues"],
                "detectors": totals[mode]["detectors"],
            }

    for mode in SCORING_MODES:
        append_subjective_dimensions(
            results[mode],
            findings,
            subjective_assessments,
            FAILURE_STATUSES_BY_MODE[mode],
            allowed_dimensions=allowed_subjective_dimensions,
        )
    return results


def compute_dimension_scores(
    findings: dict,
    potentials: dict[str, int],
    *,
    strict: bool = False,
    subjective_assessments: dict | None = None,
    allowed_subjective_dimensions: set[str] | None = None,
) -> dict[str, dict]:
    """Compute per-dimension scores from findings and potentials."""
    mode: ScoreMode = "strict" if strict else "lenient"
    return compute_dimension_scores_by_mode(
        findings,
        potentials,
        subjective_assessments=subjective_assessments,
        allowed_subjective_dimensions=allowed_subjective_dimensions,
    )[mode]


def _normalize_dimension_name(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


def _mechanical_dimension_weight(name: str) -> float:
    return float(
        MECHANICAL_DIMENSION_WEIGHTS.get(
            _normalize_dimension_name(name),
            1.0,
        )
    )


def _subjective_dimension_weight(name: str, data: dict) -> float:
    subjective_meta = (
        data.get("detectors", {}).get("subjective_assessment", {})
        if isinstance(data, dict)
        else {}
    )
    configured = (
        subjective_meta.get("configured_weight")
        if isinstance(subjective_meta, dict)
        else None
    )
    if isinstance(configured, int | float) and not isinstance(configured, bool):
        return max(0.0, float(configured))

    return float(
        SUBJECTIVE_DIMENSION_WEIGHTS.get(
            _normalize_dimension_name(name),
            1.0,
        )
    )


def compute_health_breakdown(dimension_scores: dict) -> dict[str, object]:
    """Return pool averages and weighted contribution breakdown for score transparency."""
    if not dimension_scores:
        return {
            "overall_score": 100.0,
            "mechanical_fraction": 1.0,
            "subjective_fraction": 0.0,
            "mechanical_avg": 100.0,
            "subjective_avg": None,
            "entries": [],
        }

    mech_sum = 0.0
    mech_weight = 0.0
    subj_sum = 0.0
    subj_weight = 0.0
    mechanical_rows: list[dict[str, float | str]] = []
    subjective_rows: list[dict[str, float | str]] = []

    for name, data in dimension_scores.items():
        score = float(data.get("score", 0.0))
        is_subjective = "subjective_assessment" in data.get("detectors", {})
        if is_subjective:
            configured = max(0.0, _subjective_dimension_weight(name, data))
            effective = configured
            subj_sum += score * effective
            subj_weight += effective
            subjective_rows.append(
                {
                    "name": str(name),
                    "score": score,
                    "configured_weight": configured,
                    "effective_weight": effective,
                }
            )
            continue

        checks = float(data.get("checks", 0) or 0)
        sample_factor = min(1.0, checks / MIN_SAMPLE) if checks > 0 else 0.0
        configured = max(0.0, _mechanical_dimension_weight(name))
        effective = configured * sample_factor
        mech_sum += score * effective
        mech_weight += effective
        mechanical_rows.append(
            {
                "name": str(name),
                "score": score,
                "checks": checks,
                "sample_factor": sample_factor,
                "configured_weight": configured,
                "effective_weight": effective,
            }
        )

    mech_avg = (mech_sum / mech_weight) if mech_weight > 0 else 100.0
    subj_avg = (subj_sum / subj_weight) if subj_weight > 0 else None

    if subj_avg is None:
        mechanical_fraction = 1.0
        subjective_fraction = 0.0
        overall_score = round(mech_avg, 1)
    elif mech_weight == 0:
        mechanical_fraction = 0.0
        subjective_fraction = 1.0
        overall_score = round(subj_avg, 1)
    else:
        mechanical_fraction = MECHANICAL_WEIGHT_FRACTION
        subjective_fraction = SUBJECTIVE_WEIGHT_FRACTION
        overall_score = round(
            mech_avg * mechanical_fraction + subj_avg * subjective_fraction,
            1,
        )

    entries: list[dict[str, float | str]] = []

    for row in mechanical_rows:
        pool_share = (
            float(row["effective_weight"]) / mech_weight if mech_weight > 0 else 0.0
        )
        per_point = mechanical_fraction * pool_share
        score = float(row["score"])
        entries.append(
            {
                "name": str(row["name"]),
                "pool": "mechanical",
                "score": score,
                "checks": float(row["checks"]),
                "sample_factor": float(row["sample_factor"]),
                "configured_weight": float(row["configured_weight"]),
                "effective_weight": float(row["effective_weight"]),
                "pool_share": pool_share,
                "overall_per_point": per_point,
                "overall_contribution": per_point * score,
                "overall_drag": per_point * (100.0 - score),
            }
        )

    for row in subjective_rows:
        pool_share = (
            float(row["effective_weight"]) / subj_weight if subj_weight > 0 else 0.0
        )
        per_point = subjective_fraction * pool_share
        score = float(row["score"])
        entries.append(
            {
                "name": str(row["name"]),
                "pool": "subjective",
                "score": score,
                "checks": 0.0,
                "sample_factor": 1.0,
                "configured_weight": float(row["configured_weight"]),
                "effective_weight": float(row["effective_weight"]),
                "pool_share": pool_share,
                "overall_per_point": per_point,
                "overall_contribution": per_point * score,
                "overall_drag": per_point * (100.0 - score),
            }
        )

    return {
        "overall_score": overall_score,
        "mechanical_fraction": mechanical_fraction,
        "subjective_fraction": subjective_fraction,
        "mechanical_avg": mech_avg,
        "subjective_avg": subj_avg,
        "entries": entries,
    }


def compute_health_score(dimension_scores: dict) -> float:
    """Budget-weighted blend of mechanical and subjective dimension scores."""
    return float(compute_health_breakdown(dimension_scores)["overall_score"])


def compute_score_bundle(
    findings: dict,
    potentials: dict[str, int],
    *,
    subjective_assessments: dict | None = None,
) -> ScoreBundle:
    """Compute all score channels from one scoring engine pass."""
    by_mode = compute_dimension_scores_by_mode(
        findings,
        potentials,
        subjective_assessments=subjective_assessments,
    )

    lenient_scores = by_mode["lenient"]
    strict_scores = by_mode["strict"]
    verified_strict_scores = by_mode["verified_strict"]

    mechanical_lenient_scores = {
        name: data
        for name, data in lenient_scores.items()
        if "subjective_assessment" not in data.get("detectors", {})
    }

    return ScoreBundle(
        dimension_scores=lenient_scores,
        strict_dimension_scores=strict_scores,
        verified_strict_dimension_scores=verified_strict_scores,
        overall_score=compute_health_score(lenient_scores),
        objective_score=compute_health_score(mechanical_lenient_scores),
        strict_score=compute_health_score(strict_scores),
        verified_strict_score=compute_health_score(verified_strict_scores),
    )


def compute_score_impact(
    dimension_scores: dict,
    potentials: dict[str, int],
    detector: str,
    issues_to_fix: int,
) -> float:
    """Estimate score improvement from fixing N issues in a detector."""
    target_dim = None
    for dim in DIMENSIONS:
        if detector in dim.detectors:
            target_dim = dim
            break
    if target_dim is None or target_dim.name not in dimension_scores:
        return 0.0

    potential = potentials.get(detector, 0)
    if potential <= 0:
        return 0.0

    dim_data = dimension_scores[target_dim.name]
    old_score = compute_health_score(dimension_scores)

    det_data = dim_data["detectors"].get(detector)
    if not det_data:
        return 0.0

    old_weighted = det_data["weighted_failures"]
    new_weighted = max(0.0, old_weighted - issues_to_fix * 1.0)

    total_potential = 0
    total_new_weighted_failures = 0.0
    for det in target_dim.detectors:
        det_values = dim_data["detectors"].get(det)
        if not det_values:
            continue
        total_potential += det_values["potential"]
        if det == detector:
            total_new_weighted_failures += new_weighted
        else:
            total_new_weighted_failures += det_values["weighted_failures"]
    if total_potential <= 0:
        return 0.0

    new_dim_score = (
        max(
            0.0,
            (total_potential - total_new_weighted_failures) / total_potential,
        )
        * 100
    )

    simulated = {k: dict(v) for k, v in dimension_scores.items()}
    simulated[target_dim.name] = {**dim_data, "score": round(new_dim_score, 1)}
    new_score = compute_health_score(simulated)

    return round(new_score - old_score, 1)


def get_dimension_for_detector(detector: str):
    """Look up which dimension a detector belongs to."""
    policy = DETECTOR_SCORING_POLICIES.get(detector)
    if not policy or policy.dimension is None:
        return None
    return DIMENSIONS_BY_NAME.get(policy.dimension)


__all__ = [
    "ScoreBundle",
    "compute_dimension_scores_by_mode",
    "compute_dimension_scores",
    "compute_health_breakdown",
    "compute_health_score",
    "compute_score_bundle",
    "compute_score_impact",
    "get_dimension_for_detector",
]
