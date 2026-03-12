"""Detector-to-score impact helpers."""

from __future__ import annotations

from desloppify.engine._scoring.policy.core import (
    DETECTOR_SCORING_POLICIES,
    DIMENSIONS,
    DIMENSIONS_BY_NAME,
    Dimension,
)
from desloppify.engine._scoring.results.health import compute_health_score


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
    failing = det_data.get("failing")
    if not isinstance(failing, (int, float)) or failing <= 0:
        failing = det_data.get("count")
    avg_weight = old_weighted / max(1, int(failing) if isinstance(failing, (int, float)) else 1)
    new_weighted = max(0.0, old_weighted - issues_to_fix * avg_weight)

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

    simulated = {name: dict(data) for name, data in dimension_scores.items()}
    simulated[target_dim.name] = {**dim_data, "score": round(new_dim_score, 1)}
    new_score = compute_health_score(simulated)
    return round(new_score - old_score, 1)


def get_dimension_for_detector(detector: str) -> Dimension | None:
    """Look up which dimension a detector belongs to."""
    policy = DETECTOR_SCORING_POLICIES.get(detector)
    if not policy or policy.dimension is None:
        return None
    return DIMENSIONS_BY_NAME.get(policy.dimension)


__all__ = ["compute_score_impact", "get_dimension_for_detector"]

