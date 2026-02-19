"""Numerical metrics helpers for test coverage detector."""

from __future__ import annotations

import math
from pathlib import Path

# Minimum LOC threshold — tiny files don't need dedicated tests
_MIN_LOC = 10

# Complexity score threshold for upgrading test coverage tier.
# Files above this are risky enough without tests to warrant tier 2.
_COMPLEXITY_TIER_UPGRADE = 20


def _file_loc(filepath: str) -> int:
    """Count lines in a file, returning 0 on error."""
    try:
        return len(Path(filepath).read_text().splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _loc_weight(loc: int) -> float:
    """Compute LOC weight for a file: sqrt(loc) capped at 50."""
    return min(math.sqrt(loc), 50)


def _quality_risk_level(loc: int, importer_count: int, complexity: float) -> str:
    """Classify module test-risk level for quality confidence gating."""
    if importer_count >= 10 or complexity >= _COMPLEXITY_TIER_UPGRADE or loc >= 400:
        return "high"
    if importer_count >= 4 or complexity >= 12 or loc >= 200:
        return "medium"
    return "low"


def _quality_threshold(risk: str) -> float:
    """Minimum acceptable test quality score by risk level."""
    return {"high": 0.60, "medium": 0.50}.get(risk, 0.35)
