"""Direct coverage smoke tests for recently split helper modules."""

from __future__ import annotations

import desloppify.app.output.scorecard_parts.dimensions as scorecard_dimensions
import desloppify.app.output.scorecard_parts.theme as scorecard_theme
import desloppify.engine._scoring.detection as scoring_detection
import desloppify.engine._scoring.policy.core as scoring_policy
import desloppify.engine._scoring.results.core as scoring_results
import desloppify.engine._scoring.subjective.core as scoring_subjective
import desloppify.engine._state.merge_findings as merge_findings
import desloppify.engine._state.merge_history as merge_history
import desloppify.engine._work_queue.helpers as work_queue_helpers
import desloppify.engine._work_queue.ranking as work_queue_ranking
import desloppify.intelligence.review.prepare_batches as review_prepare_batches


def test_split_module_direct_coverage_smoke_signals():
    assert callable(scorecard_dimensions.prepare_scorecard_dimensions)
    assert callable(scorecard_dimensions.prepare_scorecard_dimensions)
    assert callable(scorecard_theme.score_color)
    assert isinstance(scorecard_theme.BG, tuple)

    assert callable(review_prepare_batches.build_investigation_batches)

    assert callable(scoring_detection.detector_pass_rate)
    assert callable(scoring_detection.merge_potentials)
    assert isinstance(scoring_policy.DIMENSIONS, list)
    assert isinstance(scoring_policy.FILE_BASED_DETECTORS, set)
    assert callable(scoring_results.compute_score_bundle)
    assert callable(scoring_subjective.append_subjective_dimensions)

    assert callable(merge_findings.upsert_findings)
    assert callable(merge_findings.auto_resolve_disappeared)
    assert callable(merge_history._append_scan_history)
    assert callable(merge_history._build_merge_diff)

    assert callable(work_queue_helpers.build_subjective_items)
    assert callable(work_queue_helpers._subjective_dimension_aliases)
    assert callable(work_queue_ranking.item_sort_key)
    assert callable(work_queue_ranking.group_queue_items)


# ---------------------------------------------------------------------------
# Behavioral tests for key split-module functions
# ---------------------------------------------------------------------------


def test_merge_potentials_sums_across_langs():
    """merge_potentials sums detector counts across language partitions."""
    potentials = {
        "python": {"smells": 10, "unused": 5},
        "typescript": {"smells": 20, "deps": 3},
    }
    merged = scoring_detection.merge_potentials(potentials)
    assert merged["smells"] == 30
    assert merged["unused"] == 5
    assert merged["deps"] == 3


def test_merge_potentials_empty():
    """merge_potentials returns empty dict for empty input."""
    assert scoring_detection.merge_potentials({}) == {}


def test_item_sort_key_tier_ordering():
    """item_sort_key orders by tier (lower first)."""
    t1_item = {"tier": 1, "effective_tier": 1, "confidence": "high", "id": "a"}
    t3_item = {"tier": 3, "effective_tier": 3, "confidence": "high", "id": "b"}
    assert work_queue_ranking.item_sort_key(t1_item) < work_queue_ranking.item_sort_key(
        t3_item
    )


def test_item_sort_key_review_uses_natural_tier():
    """Review findings sort by their natural tier like mechanical findings."""
    review_t2 = {
        "is_review": True,
        "review_weight": 1.0,
        "effective_tier": 2,
        "tier": 2,
        "confidence": "high",
        "id": "r1",
    }
    t1_item = {"tier": 1, "effective_tier": 1, "confidence": "high", "id": "a"}
    # T1 mechanical sorts before T2 review
    assert work_queue_ranking.item_sort_key(t1_item) < work_queue_ranking.item_sort_key(
        review_t2
    )


def test_group_queue_items_by_detector():
    """group_queue_items groups items by detector field."""
    items = [
        {"detector": "smells", "file": "a.py"},
        {"detector": "smells", "file": "b.py"},
        {"detector": "unused", "file": "c.py"},
    ]
    grouped = work_queue_ranking.group_queue_items(items, "detector")
    assert len(grouped["smells"]) == 2
    assert len(grouped["unused"]) == 1


def test_group_queue_items_by_tier():
    """group_queue_items groups items by effective tier."""
    items = [
        {"effective_tier": 1, "tier": 1},
        {"effective_tier": 2, "tier": 2},
        {"effective_tier": 1, "tier": 1},
    ]
    grouped = work_queue_ranking.group_queue_items(items, "tier")
    assert len(grouped["T1"]) == 2
    assert len(grouped["T2"]) == 1


def test_scoring_policy_dimensions_non_empty():
    """DIMENSIONS list has real entries with required fields."""
    assert len(scoring_policy.DIMENSIONS) > 0
    first = scoring_policy.DIMENSIONS[0]
    assert hasattr(first, "name")
    assert hasattr(first, "tier")
    assert hasattr(first, "detectors")


def test_scorecard_theme_score_color():
    """score_color returns a color tuple for any score value."""
    color = scorecard_theme.score_color(0.0)
    assert isinstance(color, tuple) and len(color) == 3
    color_high = scorecard_theme.score_color(100.0)
    assert isinstance(color_high, tuple) and len(color_high) == 3
