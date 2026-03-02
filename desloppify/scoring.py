"""Objective dimension-based scoring system facade."""

from __future__ import annotations

from desloppify.engine._scoring.detection import (
    detector_pass_rate,
    detector_stats_by_mode,
    merge_potentials,
)
from desloppify.engine._scoring.policy.core import (
    CONFIDENCE_WEIGHTS,
    DETECTOR_SCORING_POLICIES,
    DIMENSIONS,
    FILE_BASED_DETECTORS,
    HOLISTIC_MULTIPLIER,
    HOLISTIC_POTENTIAL,
    MECHANICAL_DIMENSION_WEIGHTS,
    MECHANICAL_WEIGHT_FRACTION,
    MIN_SAMPLE,
    SCORING_MODES,
    SECURITY_EXCLUDED_ZONES,
    SUBJECTIVE_CHECKS,
    SUBJECTIVE_DIMENSION_WEIGHTS,
    SUBJECTIVE_TARGET_MATCH_TOLERANCE,
    SUBJECTIVE_WEIGHT_FRACTION,
    TIER_WEIGHTS,
    DetectorScoringPolicy,
    Dimension,
    ScoreMode,
    matches_target_score,
    register_scoring_policy,
    reset_registered_scoring_policies,
)
from desloppify.engine._scoring.results.core import (
    ScoreBundle,
    compute_dimension_scores,
    compute_dimension_scores_by_mode,
    compute_health_breakdown,
    compute_health_score,
    compute_score_bundle,
    compute_score_impact,
    get_dimension_for_detector,
)
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES

__all__ = [
    # Constants
    "CONFIDENCE_WEIGHTS",
    "DETECTOR_SCORING_POLICIES",
    "DIMENSIONS",
    "DISPLAY_NAMES",
    "FILE_BASED_DETECTORS",
    "HOLISTIC_MULTIPLIER",
    "HOLISTIC_POTENTIAL",
    "MECHANICAL_DIMENSION_WEIGHTS",
    "MECHANICAL_WEIGHT_FRACTION",
    "MIN_SAMPLE",
    "SCORING_MODES",
    "SECURITY_EXCLUDED_ZONES",
    "SUBJECTIVE_CHECKS",
    "SUBJECTIVE_DIMENSION_WEIGHTS",
    "SUBJECTIVE_TARGET_MATCH_TOLERANCE",
    "SUBJECTIVE_WEIGHT_FRACTION",
    "TIER_WEIGHTS",
    # Types
    "DetectorScoringPolicy",
    "Dimension",
    "ScoreBundle",
    "ScoreMode",
    # Functions
    "compute_dimension_scores",
    "compute_dimension_scores_by_mode",
    "compute_health_breakdown",
    "compute_health_score",
    "compute_score_bundle",
    "compute_score_impact",
    "detector_pass_rate",
    "detector_stats_by_mode",
    "get_dimension_for_detector",
    "matches_target_score",
    "merge_potentials",
    "register_scoring_policy",
    "reset_registered_scoring_policies",
]
