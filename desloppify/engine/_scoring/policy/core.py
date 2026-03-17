"""Scoring policies, detector mappings, and shared constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from desloppify.base.enums import Tier
from desloppify.base.registry import DETECTORS
from desloppify.base.scoring_constants import (
    CONFIDENCE_WEIGHTS,
    HOLISTIC_MULTIPLIER,
)
from desloppify.engine._state.issue_semantics import is_scoring_excluded_detector
from desloppify.engine.policy.zones import EXCLUDED_ZONE_VALUES

ScoreMode = Literal["lenient", "strict", "verified_strict"]
SCORING_MODES: tuple[ScoreMode, ...] = ("lenient", "strict", "verified_strict")


@dataclass(frozen=True)
class Dimension:
    name: str
    tier: int
    detectors: list[str]


@dataclass(frozen=True)
class DetectorScoringPolicy:
    detector: str
    dimension: str | None
    tier: int | None
    file_based: bool = False
    use_loc_weight: bool = False
    excluded_zones: frozenset[str] = frozenset(EXCLUDED_ZONE_VALUES)


# Security issues are excluded in non-production zones.
SECURITY_EXCLUDED_ZONES = frozenset({"test", "config", "generated", "vendor"})
_DEFAULT_EXCLUDED_ZONES = frozenset(EXCLUDED_ZONE_VALUES)

# Keep policy details that are independent of tier/dimension wiring.
_FILE_BASED_POLICY_DETECTORS = frozenset(
    {
        "smells",
        "dict_keys",
        "test_coverage",
        "security",
        "concerns",
        "review",
        "nextjs",
        "next_lint",
    }
)
_LOC_WEIGHT_POLICY_DETECTORS = frozenset({"test_coverage"})
_EXCLUDED_ZONE_OVERRIDES: dict[str, frozenset[str]] = {
    "security": SECURITY_EXCLUDED_ZONES,
}

# Legacy test/import surface for code that still expects subjective detectors
# to be grouped in scoring core.
_NON_OBJECTIVE_DETECTORS = frozenset(
    {"review", "concerns", "subjective_review", "subjective_assessment"}
)


def _build_builtin_detector_scoring_policies() -> dict[str, DetectorScoringPolicy]:
    """Build baseline scoring policies from DetectorMeta plus policy overrides."""
    policies: dict[str, DetectorScoringPolicy] = {}
    for detector, meta in DETECTORS.items():
        if is_scoring_excluded_detector(detector):
            dimension: str | None = None
            tier: int | None = None
        else:
            dimension = meta.dimension
            tier = meta.tier

        policies[detector] = DetectorScoringPolicy(
            detector=detector,
            dimension=dimension,
            tier=tier,
            file_based=detector in _FILE_BASED_POLICY_DETECTORS,
            use_loc_weight=detector in _LOC_WEIGHT_POLICY_DETECTORS,
            excluded_zones=_EXCLUDED_ZONE_OVERRIDES.get(
                detector,
                _DEFAULT_EXCLUDED_ZONES,
            ),
        )
    return policies


# Central scoring policy for each detector: tier/dimension come from registry,
# while file-based and zone behavior are preserved via local overrides.
DETECTOR_SCORING_POLICIES: dict[str, DetectorScoringPolicy] = (
    _build_builtin_detector_scoring_policies()
)
_BASE_DETECTOR_SCORING_POLICIES: dict[str, DetectorScoringPolicy] = dict(
    DETECTOR_SCORING_POLICIES
)

# Detectors where potential = file count but issues are per-(file, sub-type).
# Per-file weighted failures are capped at 1.0 to match the file-based denominator.
FILE_BASED_DETECTORS = {
    detector
    for detector, policy in DETECTOR_SCORING_POLICIES.items()
    if policy.file_based
}


def _build_dimensions() -> list[Dimension]:
    """Derive dimensions from DETECTOR_SCORING_POLICIES.

    Each unique (dimension, tier) pair becomes a Dimension, with its detectors
    collected automatically. Order follows first-seen in the policies dict.
    """
    # Collect (dimension_name -> tier) preserving first-seen order,
    # and group detectors by dimension.
    dim_tiers: dict[str, int] = {}
    grouped: dict[str, list[str]] = {}
    for detector, policy in DETECTOR_SCORING_POLICIES.items():
        if policy.dimension is None or policy.tier is None:
            continue
        if policy.dimension not in dim_tiers:
            dim_tiers[policy.dimension] = policy.tier
            grouped[policy.dimension] = []
        grouped[policy.dimension].append(detector)
    return [
        Dimension(name=name, tier=tier, detectors=grouped[name])
        for name, tier in dim_tiers.items()
    ]


DIMENSIONS = _build_dimensions()
DIMENSIONS_BY_NAME = {d.name: d for d in DIMENSIONS}

TIER_WEIGHTS = {
    Tier.AUTO_FIX: 1,
    Tier.QUICK_FIX: 2,
    Tier.JUDGMENT: 3,
    Tier.MAJOR_REFACTOR: 4,
}
# Minimum checks for full dimension weight — below this, weight is dampened
# proportionally. Prevents small-sample dimensions from swinging the overall score.
MIN_SAMPLE = 200
HOLISTIC_POTENTIAL = 10

# Budget: subjective dimensions get this fraction of the overall score.
# Mechanical dimensions get the remainder.
SUBJECTIVE_WEIGHT_FRACTION = 0.75
MECHANICAL_WEIGHT_FRACTION = 1.0 - SUBJECTIVE_WEIGHT_FRACTION

# Per-dimension weighting within the mechanical pool.
# Keep this balanced: no special boost for security/test in the pool itself.
MECHANICAL_DIMENSION_WEIGHTS: dict[str, float] = {
    "file health": 2.0,
    "code quality": 1.0,
    "duplication": 1.0,
    "test health": 1.0,
    "security": 1.0,
    # Open Paws advocacy dimensions
    "advocacy language": 1.0,
    "advocacy security": 1.0,
    # Persona-based browser QA
    "persona qa": 1.0,
}

# Per-dimension weighting within the subjective pool.
# Rationale (kept in sync with review metadata modules):
# - High/mid elegance carry the most weight because architectural decomposition
#   and seam quality drive broad maintainability and change velocity.
# - Low elegance, contracts, and type safety remain high because they prevent
#   correctness drift and interface ambiguity.
# - Design coherence is a medium-high bridge between architecture intent and
#   the detector-led concern stream.
# - Structure navigation and error consistency are meaningful but secondary
#   signals compared to core architecture/correctness dimensions.
# - Naming quality and AI-generated debt are intentionally low-weight nudges:
#   useful for polish/cleanup, but they should not dominate score movement.
SUBJECTIVE_DIMENSION_WEIGHTS: dict[str, float] = {
    "high elegance": 22.0,
    "mid elegance": 22.0,
    "low elegance": 12.0,
    "contracts": 12.0,
    "type safety": 12.0,
    "abstraction fit": 8.0,
    "logic clarity": 6.0,
    # Low-but-meaningful structural signal (about half of the subjective
    # average weight) so it matters without dominating craftsmanship axes.
    "structure nav": 5.0,
    "error consistency": 3.0,
    "naming quality": 2.0,
    "ai generated debt": 1.0,
    "design coherence": 10.0,
}

# Synthetic check count for subjective dimensions in dimension_scores.
SUBJECTIVE_CHECKS = 10

FAILURE_STATUSES_BY_MODE: dict[ScoreMode, frozenset[str]] = {
    "lenient": frozenset({"open", "deferred", "triaged_out"}),
    "strict": frozenset({"open", "wontfix", "auto_resolved", "deferred", "triaged_out"}),
    "verified_strict": frozenset({"open", "wontfix", "fixed", "false_positive", "deferred", "triaged_out"}),
}

# Tolerance for treating a subjective score as "on target" in integrity checks.
# Scores within this band of the target are flagged as potential gaming.
SUBJECTIVE_TARGET_MATCH_TOLERANCE = 0.05


def matches_target_score(
    score: object,
    target: object,
    *,
    tolerance: float = SUBJECTIVE_TARGET_MATCH_TOLERANCE,
) -> bool:
    """Return True when score is within tolerance of target."""
    try:
        score_value = float(score)
        target_value = float(target)
        tolerance_value = max(0.0, float(tolerance))
    except (TypeError, ValueError):
        return False
    return abs(score_value - target_value) <= tolerance_value


def register_scoring_policy(policy: DetectorScoringPolicy) -> None:
    """Register a scoring policy at runtime (used by generic plugins)."""
    DETECTOR_SCORING_POLICIES[policy.detector] = policy
    _rebuild_derived()


def reset_registered_scoring_policies() -> None:
    """Reset runtime-added scoring policies to built-in defaults."""
    DETECTOR_SCORING_POLICIES.clear()
    DETECTOR_SCORING_POLICIES.update(_BASE_DETECTOR_SCORING_POLICIES)
    _rebuild_derived()


def _rebuild_derived() -> None:
    """Rebuild DIMENSIONS, DIMENSIONS_BY_NAME, FILE_BASED_DETECTORS from current state.

    Mutates existing objects in-place so that all references (including imports
    that bound the original objects) see the updates.
    """
    new_dims = _build_dimensions()
    DIMENSIONS.clear()
    DIMENSIONS.extend(new_dims)
    DIMENSIONS_BY_NAME.clear()
    DIMENSIONS_BY_NAME.update({d.name: d for d in DIMENSIONS})
    FILE_BASED_DETECTORS.clear()
    FILE_BASED_DETECTORS.update(
        det for det, pol in DETECTOR_SCORING_POLICIES.items() if pol.file_based
    )


def detector_policy(detector: str) -> DetectorScoringPolicy:
    """Get scoring policy for a detector, with a safe default fallback."""
    return DETECTOR_SCORING_POLICIES.get(
        detector,
        DetectorScoringPolicy(detector=detector, dimension=None, tier=None),
    )


__all__ = [
    "CONFIDENCE_WEIGHTS",
    "DETECTOR_SCORING_POLICIES",
    "DIMENSIONS",
    "DIMENSIONS_BY_NAME",
    "FAILURE_STATUSES_BY_MODE",
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
    "DetectorScoringPolicy",
    "Dimension",
    "ScoreMode",
    "detector_policy",
    "matches_target_score",
    "register_scoring_policy",
    "reset_registered_scoring_policies",
]
