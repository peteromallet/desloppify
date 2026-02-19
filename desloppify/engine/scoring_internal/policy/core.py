"""Scoring policies, detector mappings, and shared constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from desloppify.core.enums import Confidence, Tier
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


_DIMENSION_SPECS: tuple[tuple[str, int], ...] = (
    ("File health", 3),
    ("Code quality", 3),
    ("Duplication", 3),
    ("Test health", 4),
    ("Security", 4),
)

# Security findings are excluded in non-production zones.
SECURITY_EXCLUDED_ZONES = frozenset({"test", "config", "generated", "vendor"})

# Central scoring policy for each detector: dimension/tier assignment,
# weighting mode, and zone exclusions.
DETECTOR_SCORING_POLICIES: dict[str, DetectorScoringPolicy] = {
    # File health
    "structural": DetectorScoringPolicy("structural", "File health", 3),
    # Code quality
    "unused": DetectorScoringPolicy("unused", "Code quality", 3),
    "logs": DetectorScoringPolicy("logs", "Code quality", 3),
    "exports": DetectorScoringPolicy("exports", "Code quality", 3),
    "deprecated": DetectorScoringPolicy("deprecated", "Code quality", 3),
    "props": DetectorScoringPolicy("props", "Code quality", 3),
    "smells": DetectorScoringPolicy("smells", "Code quality", 3, file_based=True),
    "react": DetectorScoringPolicy("react", "Code quality", 3),
    "dict_keys": DetectorScoringPolicy("dict_keys", "Code quality", 3, file_based=True),
    "global_mutable_config": DetectorScoringPolicy(
        "global_mutable_config", "Code quality", 3
    ),
    "orphaned": DetectorScoringPolicy("orphaned", "Code quality", 3),
    "flat_dirs": DetectorScoringPolicy("flat_dirs", "Code quality", 3),
    "naming": DetectorScoringPolicy("naming", "Code quality", 3),
    "facade": DetectorScoringPolicy("facade", "Code quality", 3),
    "stale_exclude": DetectorScoringPolicy("stale_exclude", "Code quality", 3),
    "patterns": DetectorScoringPolicy("patterns", "Code quality", 3),
    "single_use": DetectorScoringPolicy("single_use", "Code quality", 3),
    "coupling": DetectorScoringPolicy("coupling", "Code quality", 3),
    "responsibility_cohesion": DetectorScoringPolicy(
        "responsibility_cohesion", "Code quality", 3
    ),
    "private_imports": DetectorScoringPolicy("private_imports", "Code quality", 3),
    "layer_violation": DetectorScoringPolicy("layer_violation", "Code quality", 3),
    # Duplication
    "dupes": DetectorScoringPolicy("dupes", "Duplication", 3),
    "boilerplate_duplication": DetectorScoringPolicy(
        "boilerplate_duplication", "Duplication", 3
    ),
    # Test health
    "test_coverage": DetectorScoringPolicy(
        "test_coverage", "Test health", 4, file_based=True, use_loc_weight=True
    ),
    "subjective_review": DetectorScoringPolicy(
        "subjective_review", "Test health", 4, file_based=True
    ),
    # Security
    "security": DetectorScoringPolicy(
        "security",
        "Security",
        4,
        file_based=True,
        excluded_zones=SECURITY_EXCLUDED_ZONES,
    ),
    "cycles": DetectorScoringPolicy("cycles", "Security", 4),
    # Review findings are scored via subjective dimensions, not mechanical dimensions.
    "review": DetectorScoringPolicy("review", None, None, file_based=True),
}

# Detectors where potential = file count but findings are per-(file, sub-type).
# Per-file weighted failures are capped at 1.0 to match the file-based denominator.
FILE_BASED_DETECTORS = {
    detector
    for detector, policy in DETECTOR_SCORING_POLICIES.items()
    if policy.file_based
}


def _build_dimensions() -> list[Dimension]:
    grouped: dict[str, list[str]] = {name: [] for name, _tier in _DIMENSION_SPECS}
    for detector, policy in DETECTOR_SCORING_POLICIES.items():
        if policy.dimension is None:
            continue
        grouped[policy.dimension].append(detector)
    return [
        Dimension(name=name, tier=tier, detectors=grouped[name])
        for name, tier in _DIMENSION_SPECS
    ]


DIMENSIONS = _build_dimensions()
DIMENSIONS_BY_NAME = {d.name: d for d in DIMENSIONS}

TIER_WEIGHTS = {
    Tier.AUTO_FIX: 1,
    Tier.QUICK_FIX: 2,
    Tier.JUDGMENT: 3,
    Tier.MAJOR_REFACTOR: 4,
}
CONFIDENCE_WEIGHTS = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.7, Confidence.LOW: 0.3}

# Minimum checks for full dimension weight — below this, weight is dampened
# proportionally. Prevents small-sample dimensions from swinging the overall score.
MIN_SAMPLE = 200

# Holistic review scoring: findings with file="." and detail.holistic=True
# bypass per-file caps and get a 10x weight multiplier.
HOLISTIC_MULTIPLIER = 10.0
HOLISTIC_POTENTIAL = 10

# Budget: subjective dimensions get this fraction of the overall score.
# Mechanical dimensions get the remainder.
SUBJECTIVE_WEIGHT_FRACTION = 0.60
MECHANICAL_WEIGHT_FRACTION = 1.0 - SUBJECTIVE_WEIGHT_FRACTION

# Per-dimension weighting within the mechanical pool.
# Keep this balanced: no special boost for security/test in the pool itself.
MECHANICAL_DIMENSION_WEIGHTS: dict[str, float] = {
    "file health": 2.0,
    "code quality": 1.0,
    "duplication": 1.0,
    "test health": 1.0,
    "security": 1.0,
}

# Per-dimension weighting within the subjective pool.
# Emphasize elegance and contract/type coherence for a stronger architecture north star.
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
}

# Synthetic check count for subjective dimensions in dimension_scores.
SUBJECTIVE_CHECKS = 10

FAILURE_STATUSES_BY_MODE: dict[ScoreMode, frozenset[str]] = {
    "lenient": frozenset({"open"}),
    "strict": frozenset({"open", "wontfix"}),
    "verified_strict": frozenset({"open", "wontfix", "fixed", "false_positive"}),
}


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
    "SUBJECTIVE_WEIGHT_FRACTION",
    "TIER_WEIGHTS",
    "DetectorScoringPolicy",
    "Dimension",
    "ScoreMode",
    "detector_policy",
]
