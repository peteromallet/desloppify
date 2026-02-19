"""Direct tests for subjective-integrity helper utilities."""

from __future__ import annotations

from desloppify.intelligence.integrity.subjective import (
    SUBJECTIVE_TARGET_MATCH_TOLERANCE,
    matches_target_score,
)


def test_matches_target_score_uses_shared_tolerance():
    assert matches_target_score(95.0, 95.0)
    assert matches_target_score(95.0 + SUBJECTIVE_TARGET_MATCH_TOLERANCE, 95.0)
    assert not matches_target_score(
        95.0 + SUBJECTIVE_TARGET_MATCH_TOLERANCE + 0.01, 95.0
    )
