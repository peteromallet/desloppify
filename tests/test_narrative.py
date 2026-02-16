"""Tests for desloppify.narrative — pure narrative computation functions."""

from __future__ import annotations


from desloppify.narrative import (
    STRUCTURAL_MERGE,
    _analyze_debt,
    _compute_fixer_leverage,
    _compute_headline,
    _compute_lanes,
    _compute_reminders,
    _compute_strategy,
    _compute_strategy_hint,
    _count_open_by_detector,
    _detect_milestone,
    _detect_phase,
    _open_files_by_detector,
    compute_narrative,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    detector: str,
    *,
    status: str = "open",
    confidence: str = "high",
    file: str = "a.py",
    zone: str = "production",
) -> dict:
    """Build a minimal finding dict."""
    return {
        "detector": detector,
        "status": status,
        "confidence": confidence,
        "file": file,
        "zone": zone,
    }


def _findings_dict(*findings: dict) -> dict:
    """Wrap a list of finding dicts into an id-keyed dict."""
    return {str(i): f for i, f in enumerate(findings)}


def _history_entry(
    strict_score: float | None = None,
    objective_score: float | None = None,
    lang: str | None = None,
    dimension_scores: dict | None = None,
) -> dict:
    entry: dict = {}
    if strict_score is not None:
        entry["strict_score"] = strict_score
    if objective_score is not None:
        entry["objective_score"] = objective_score
        entry["overall_score"] = objective_score
    if lang is not None:
        entry["lang"] = lang
    if dimension_scores is not None:
        entry["dimension_scores"] = dimension_scores
    return entry


# ===================================================================
# _count_open_by_detector
# ===================================================================

class TestCountOpenByDetector:
    def test_empty_findings(self):
        assert _count_open_by_detector({}) == {}

    def test_only_open_counted(self):
        findings = _findings_dict(
            _finding("unused", status="open"),
            _finding("unused", status="resolved"),
            _finding("unused", status="wontfix"),
            _finding("unused", status="false_positive"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"unused": 1}

    def test_multiple_detectors(self):
        findings = _findings_dict(
            _finding("unused", status="open"),
            _finding("unused", status="open"),
            _finding("logs", status="open"),
            _finding("smells", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"unused": 2, "logs": 1, "smells": 1}

    def test_structural_merge_large(self):
        findings = _findings_dict(
            _finding("large", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"structural": 1}

    def test_structural_merge_complexity(self):
        findings = _findings_dict(
            _finding("complexity", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"structural": 1}

    def test_structural_merge_gods(self):
        findings = _findings_dict(
            _finding("gods", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"structural": 1}

    def test_structural_merge_concerns(self):
        findings = _findings_dict(
            _finding("concerns", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"structural": 1}

    def test_structural_merge_combines_all_subdetectors(self):
        """All four structural sub-detectors merge into a single count."""
        findings = _findings_dict(
            _finding("large", status="open"),
            _finding("complexity", status="open"),
            _finding("gods", status="open"),
            _finding("concerns", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"structural": 4}

    def test_structural_merge_set_matches_constant(self):
        assert STRUCTURAL_MERGE == {"large", "complexity", "gods", "concerns"}

    def test_non_structural_not_merged(self):
        """Detectors not in STRUCTURAL_MERGE stay separate."""
        findings = _findings_dict(
            _finding("unused", status="open"),
            _finding("large", status="open"),
        )
        result = _count_open_by_detector(findings)
        assert result == {"unused": 1, "structural": 1}

    def test_missing_detector_key(self):
        findings = {"0": {"status": "open"}}
        result = _count_open_by_detector(findings)
        assert result == {"unknown": 1}


# ===================================================================
# _detect_phase
# ===================================================================

class TestDetectPhase:
    def test_empty_history(self):
        assert _detect_phase([], None) == "first_scan"

    def test_single_entry_history(self):
        history = [_history_entry(strict_score=50.0)]
        assert _detect_phase(history, 50.0) == "first_scan"

    def test_regression_strict_dropped(self):
        """Strict dropped > 0.5 from previous scan."""
        history = [
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=79.0),
        ]
        assert _detect_phase(history, 79.0) == "regression"

    def test_regression_exact_half_point_no_regression(self):
        """Dropping exactly 0.5 is NOT regression (must exceed 0.5)."""
        history = [
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=79.5),
        ]
        assert _detect_phase(history, 79.5) != "regression"

    def test_stagnation_three_scans_unchanged(self):
        """Strict unchanged (spread <= 0.5) for 3+ scans."""
        history = [
            _history_entry(strict_score=75.0),
            _history_entry(strict_score=75.2),
            _history_entry(strict_score=75.3),
        ]
        assert _detect_phase(history, 75.3) == "stagnation"

    def test_stagnation_requires_three_scans(self):
        """Only two scans with same score is not stagnation."""
        history = [
            _history_entry(strict_score=75.0),
            _history_entry(strict_score=75.0),
        ]
        # Two scans, same score but len(history) < 3 so no stagnation
        # This should trigger early_momentum check (len 2, and first==last)
        # Since first == last (not last > first), it won't be early_momentum
        # Falls through to score thresholds
        assert _detect_phase(history, 75.0) != "stagnation"

    def test_early_momentum_scans_2_to_5_rising(self):
        """Scans 2-5, score rising from first to last."""
        history = [
            _history_entry(strict_score=60.0),
            _history_entry(strict_score=70.0),
        ]
        assert _detect_phase(history, 70.0) == "early_momentum"

    def test_early_momentum_at_five_scans(self):
        history = [
            _history_entry(strict_score=50.0),
            _history_entry(strict_score=55.0),
            _history_entry(strict_score=60.0),
            _history_entry(strict_score=65.0),
            _history_entry(strict_score=70.0),
        ]
        assert _detect_phase(history, 70.0) == "early_momentum"

    def test_early_momentum_not_at_six_scans(self):
        """More than 5 scans should not be early_momentum."""
        history = [
            _history_entry(strict_score=50.0),
            _history_entry(strict_score=55.0),
            _history_entry(strict_score=60.0),
            _history_entry(strict_score=65.0),
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=75.0),
        ]
        # len=6, not in 2-5 range, falls through
        result = _detect_phase(history, 75.0)
        assert result != "early_momentum"

    def test_declining_trajectory_not_early_momentum(self):
        """Score declining from first scan should NOT return early_momentum."""
        history = [
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=75.0),
        ]
        # last (75) < first (80), so not early_momentum
        # Also triggers regression (80 - 75 = 5 > 0.5)
        result = _detect_phase(history, 75.0)
        assert result != "early_momentum"
        assert result == "regression"

    def test_flat_trajectory_not_early_momentum(self):
        """Score equal from first scan should NOT return early_momentum."""
        history = [
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
        ]
        # last == first, not >
        result = _detect_phase(history, 70.0)
        assert result != "early_momentum"

    def test_maintenance_above_93(self):
        """Score > 93 triggers maintenance phase."""
        history = [
            _history_entry(strict_score=85.0),
            _history_entry(strict_score=88.0),
            _history_entry(strict_score=90.0),
            _history_entry(strict_score=92.0),
            _history_entry(strict_score=93.5),
            _history_entry(strict_score=94.0),
        ]
        assert _detect_phase(history, 94.0) == "maintenance"

    def test_refinement_above_80(self):
        """Score > 80 but <= 93 triggers refinement."""
        history = [
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=75.0),
            _history_entry(strict_score=78.0),
            _history_entry(strict_score=81.0),
            _history_entry(strict_score=82.0),
            _history_entry(strict_score=85.0),
        ]
        assert _detect_phase(history, 85.0) == "refinement"

    def test_middle_grind_below_80(self):
        """Score <= 80 with > 5 scans, no regression/stagnation."""
        history = [
            _history_entry(strict_score=40.0),
            _history_entry(strict_score=45.0),
            _history_entry(strict_score=50.0),
            _history_entry(strict_score=55.0),
            _history_entry(strict_score=60.0),
            _history_entry(strict_score=65.0),
        ]
        assert _detect_phase(history, 65.0) == "middle_grind"

    def test_regression_takes_priority_over_stagnation(self):
        """Regression is checked before stagnation."""
        # Last 3 scans: 80, 80, 79 — stagnation spread 1.0 > 0.5 so not stagnant
        # But prev=80, curr=79 — drop is 1 > 0.5, so regression
        history = [
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=79.0),
        ]
        assert _detect_phase(history, 79.0) == "regression"

    def test_stagnation_takes_priority_over_early_momentum(self):
        """Stagnation is checked before early_momentum for short histories."""
        history = [
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
        ]
        assert _detect_phase(history, 70.0) == "stagnation"

    def test_obj_strict_none_uses_last_history(self):
        """When obj_strict is None, fallback to history[-1].strict_score."""
        history = [
            _history_entry(strict_score=50.0),
            _history_entry(strict_score=55.0),
            _history_entry(strict_score=60.0),
            _history_entry(strict_score=65.0),
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=75.0),
        ]
        # obj_strict None -> uses history[-1] = 75.0 -> refinement (> 80 would be, but 75 is not)
        # 75 <= 80 -> middle_grind
        result = _detect_phase(history, None)
        assert result == "middle_grind"

    def test_regression_with_none_strict_values(self):
        """If prev or curr strict is None, regression check is skipped."""
        history = [
            _history_entry(),  # no strict_score
            _history_entry(strict_score=70.0),
        ]
        result = _detect_phase(history, 70.0)
        # No prev strict to compare, regression check skipped
        # len=2, first has no strict -> early_momentum check: first is None -> skip
        # strict=70 -> not > 93, not > 80 -> middle_grind
        assert result == "middle_grind"


# ===================================================================
# _detect_milestone
# ===================================================================

class TestDetectMilestone:
    def test_crossed_90_strict(self):
        state = {"strict_score": 91.0, "stats": {"by_tier": {}}}
        history = [
            _history_entry(strict_score=89.0),
            _history_entry(strict_score=91.0),
        ]
        result = _detect_milestone(state, None, history)
        assert result == "Crossed 90% strict!"

    def test_crossed_80_strict(self):
        state = {"strict_score": 82.0, "stats": {"by_tier": {}}}
        history = [
            _history_entry(strict_score=78.0),
            _history_entry(strict_score=82.0),
        ]
        result = _detect_milestone(state, None, history)
        assert result == "Crossed 80% strict!"

    def test_crossed_90_takes_priority_over_80(self):
        """If somehow both thresholds are crossed simultaneously, 90 wins."""
        state = {"strict_score": 91.0, "stats": {"by_tier": {}}}
        history = [
            _history_entry(strict_score=79.0),
            _history_entry(strict_score=91.0),
        ]
        result = _detect_milestone(state, None, history)
        assert result == "Crossed 90% strict!"

    def test_already_above_90_no_milestone(self):
        """If already above 90, no crossing milestone."""
        state = {"strict_score": 95.0, "stats": {"by_tier": {}}}
        history = [
            _history_entry(strict_score=92.0),
            _history_entry(strict_score=95.0),
        ]
        result = _detect_milestone(state, None, history)
        assert result is None

    def test_all_t1_t2_cleared(self):
        state = {
            "strict_score": 70.0,
            "stats": {
                "by_tier": {
                    "1": {"open": 0, "resolved": 5},
                    "2": {"open": 0, "resolved": 3},
                },
            },
        }
        history = [_history_entry(strict_score=70.0)]
        result = _detect_milestone(state, None, history)
        assert result == "All T1 and T2 items cleared!"

    def test_all_t1_cleared_with_t2_remaining(self):
        state = {
            "strict_score": 70.0,
            "stats": {
                "by_tier": {
                    "1": {"open": 0, "resolved": 5},
                    "2": {"open": 2, "resolved": 1},
                },
            },
        }
        history = [_history_entry(strict_score=70.0)]
        result = _detect_milestone(state, None, history)
        assert result == "All T1 items cleared!"

    def test_t1_still_open_no_milestone(self):
        state = {
            "strict_score": 70.0,
            "stats": {
                "by_tier": {
                    "1": {"open": 3, "resolved": 2},
                    "2": {"open": 1, "resolved": 0},
                },
            },
        }
        history = [_history_entry(strict_score=70.0)]
        result = _detect_milestone(state, None, history)
        assert result is None

    def test_zero_open_findings(self):
        state = {
            "strict_score": 100.0,
            "stats": {
                "open": 0,
                "total": 10,
                "by_tier": {},
            },
        }
        history = [_history_entry(strict_score=100.0)]
        result = _detect_milestone(state, None, history)
        assert result == "Zero open findings!"

    def test_zero_total_findings_no_milestone(self):
        """Zero open AND zero total means nothing was ever found -- no celebration."""
        state = {
            "strict_score": 100.0,
            "stats": {
                "open": 0,
                "total": 0,
                "by_tier": {},
            },
        }
        history = [_history_entry(strict_score=100.0)]
        result = _detect_milestone(state, None, history)
        assert result is None

    def test_no_milestone_ordinary_case(self):
        state = {
            "strict_score": 70.0,
            "stats": {
                "open": 15,
                "total": 50,
                "by_tier": {
                    "1": {"open": 2},
                    "2": {"open": 3},
                },
            },
        }
        history = [_history_entry(strict_score=70.0)]
        result = _detect_milestone(state, None, history)
        assert result is None

    def test_threshold_milestones_require_two_history_entries(self):
        """Single history entry cannot trigger 90/80 crossing."""
        state = {"strict_score": 95.0, "stats": {"by_tier": {}}}
        history = [_history_entry(strict_score=95.0)]
        result = _detect_milestone(state, None, history)
        assert result is None

    def test_t1_t2_cleared_requires_prior_items(self):
        """If there were never T1/T2 items, no clearing milestone."""
        state = {
            "strict_score": 70.0,
            "stats": {
                "by_tier": {
                    "1": {"open": 0},  # totals sum to 0
                    "2": {"open": 0},
                },
            },
        }
        history = [_history_entry(strict_score=70.0)]
        result = _detect_milestone(state, None, history)
        assert result is None


# ===================================================================
# _analyze_debt
# ===================================================================

class TestAnalyzeDebt:
    def test_empty_inputs(self):
        result = _analyze_debt({}, {}, [])
        assert result["overall_gap"] == 0.0
        assert result["wontfix_count"] == 0
        assert result["worst_dimension"] is None
        assert result["worst_gap"] == 0.0
        assert result["trend"] == "stable"

    def test_wontfix_count(self):
        findings = _findings_dict(
            _finding("unused", status="wontfix"),
            _finding("unused", status="wontfix"),
            _finding("logs", status="open"),
            _finding("smells", status="resolved"),
        )
        result = _analyze_debt({}, findings, [])
        assert result["wontfix_count"] == 2

    def test_worst_dimension_gap(self):
        dim_scores = {
            "Import hygiene": {"score": 90.0, "strict": 85.0, "tier": 1},
            "Debug cleanliness": {"score": 95.0, "strict": 80.0, "tier": 2},
        }
        result = _analyze_debt(dim_scores, {}, [])
        assert result["worst_dimension"] == "Debug cleanliness"
        assert result["worst_gap"] == 15.0

    def test_overall_gap_weighted(self):
        """Overall gap is tier-weighted average of (lenient - strict)."""
        dim_scores = {
            "Import hygiene": {"score": 90.0, "strict": 80.0, "tier": 1},
        }
        result = _analyze_debt(dim_scores, {}, [])
        # lenient=90, strict=80, gap=10
        assert result["overall_gap"] == 10.0

    def test_trend_growing(self):
        """Gap increased over history -> growing."""
        history = [
            _history_entry(strict_score=80.0, objective_score=82.0),
            _history_entry(strict_score=78.0, objective_score=84.0),
            _history_entry(strict_score=75.0, objective_score=85.0),
        ]
        # gaps: 2.0, 6.0, 10.0 -- last (10) > first (2) + 0.5 -> growing
        result = _analyze_debt({}, {}, history)
        assert result["trend"] == "growing"

    def test_trend_shrinking(self):
        """Gap decreased over history -> shrinking."""
        history = [
            _history_entry(strict_score=70.0, objective_score=80.0),
            _history_entry(strict_score=75.0, objective_score=80.0),
            _history_entry(strict_score=79.0, objective_score=80.0),
        ]
        # gaps: 10.0, 5.0, 1.0 -- last (1) < first (10) - 0.5 -> shrinking
        result = _analyze_debt({}, {}, history)
        assert result["trend"] == "shrinking"

    def test_trend_stable(self):
        """Gap unchanged -> stable."""
        history = [
            _history_entry(strict_score=75.0, objective_score=80.0),
            _history_entry(strict_score=75.0, objective_score=80.0),
            _history_entry(strict_score=75.0, objective_score=80.0),
        ]
        # gaps: 5.0, 5.0, 5.0 -- last == first -> stable
        result = _analyze_debt({}, {}, history)
        assert result["trend"] == "stable"

    def test_trend_requires_three_scans(self):
        """Fewer than 3 scans -> stable (no trend)."""
        history = [
            _history_entry(strict_score=70.0, objective_score=80.0),
            _history_entry(strict_score=60.0, objective_score=85.0),
        ]
        result = _analyze_debt({}, {}, history)
        assert result["trend"] == "stable"

    def test_no_gap_when_strict_equals_lenient(self):
        dim_scores = {
            "Import hygiene": {"score": 90.0, "strict": 90.0, "tier": 1},
        }
        result = _analyze_debt(dim_scores, {}, [])
        assert result["overall_gap"] == 0.0
        assert result["worst_dimension"] is None
        assert result["worst_gap"] == 0.0


# ===================================================================
# _compute_reminders
# ===================================================================

class TestComputeReminders:
    def test_returns_tuple(self):
        """Must return (list, dict) tuple."""
        state = {"strict_score": 50.0}
        result = _compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, None,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], dict)

    def test_decay_suppresses_after_three(self):
        """Reminders shown >= 3 times are suppressed."""
        state = {
            "strict_score": 50.0,
            "reminder_history": {"rescan_needed": 3},
        }
        reminders, history = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "fix",
        )
        # "rescan_needed" would fire for command="fix" but history count=3 -> suppressed
        reminder_types = [r["type"] for r in reminders]
        assert "rescan_needed" not in reminder_types

    def test_decay_allows_below_threshold(self):
        """Reminders shown < 3 times are allowed through."""
        state = {
            "strict_score": 50.0,
            "reminder_history": {"rescan_needed": 2},
        }
        reminders, history = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "fix",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "rescan_needed" in reminder_types

    def test_updated_history_increments_count(self):
        """Updated history increments count for shown reminders."""
        state = {
            "strict_score": 50.0,
            "reminder_history": {"rescan_needed": 1},
        }
        reminders, updated = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "fix",
        )
        assert updated["rescan_needed"] == 2

    def test_rescan_reminder_after_fix(self):
        state = {"strict_score": 50.0}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "fix",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "rescan_needed" in reminder_types

    def test_rescan_reminder_after_resolve(self):
        state = {"strict_score": 50.0}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "resolve",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "rescan_needed" in reminder_types

    def test_no_rescan_reminder_after_scan(self):
        state = {"strict_score": 50.0}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "scan",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "rescan_needed" not in reminder_types

    def test_ignore_suppression_reminder_when_high(self):
        state = {
            "strict_score": 50.0,
            "ignore_integrity": {"ignored": 12, "suppressed_pct": 42.0},
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "scan",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "ignore_suppression_high" in reminder_types

    def test_no_ignore_suppression_reminder_when_low(self):
        state = {
            "strict_score": 50.0,
            "ignore_integrity": {"ignored": 2, "suppressed_pct": 12.0},
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "scan",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "ignore_suppression_high" not in reminder_types

    def test_wontfix_growing_reminder(self):
        state = {"strict_score": 50.0}
        debt = {"trend": "growing"}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", debt,
            [], {}, {}, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "wontfix_growing" in reminder_types

    def test_badge_recommendation_above_90(self):
        state = {"strict_score": 92.0}
        badge = {"generated": True, "in_readme": False}
        reminders, _ = _compute_reminders(
            state, "typescript", "maintenance", {},
            [], {}, badge, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "badge_recommendation" in reminder_types

    def test_no_badge_recommendation_below_90(self):
        state = {"strict_score": 85.0}
        badge = {"generated": True, "in_readme": False}
        reminders, _ = _compute_reminders(
            state, "typescript", "refinement", {},
            [], {}, badge, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "badge_recommendation" not in reminder_types

    def test_no_badge_recommendation_already_in_readme(self):
        state = {"strict_score": 95.0}
        badge = {"generated": True, "in_readme": True}
        reminders, _ = _compute_reminders(
            state, "typescript", "maintenance", {},
            [], {}, badge, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "badge_recommendation" not in reminder_types

    def test_auto_fixers_available_typescript(self):
        state = {"strict_score": 50.0}
        actions = [{"type": "auto_fix", "count": 5, "command": "desloppify fix unused-imports --dry-run"}]
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            actions, {}, {}, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "auto_fixers_available" in reminder_types

    def test_auto_fixers_reminder_depends_on_actions_not_lang(self):
        """Auto-fixer reminder follows action availability, not language name."""
        state = {"strict_score": 50.0}
        actions = [{"type": "auto_fix", "count": 5, "command": "desloppify fix unused-imports --dry-run"}]
        reminders, _ = _compute_reminders(
            state, "python", "middle_grind", {},
            actions, {}, {}, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "auto_fixers_available" in reminder_types

    def test_stagnant_dimension_reminder(self):
        state = {"strict_score": 70.0}
        dimensions = {
            "stagnant_dimensions": [
                {"name": "Import hygiene", "strict": 80.0, "stuck_scans": 4},
            ],
        }
        reminders, _ = _compute_reminders(
            state, "typescript", "stagnation", {},
            [], dimensions, {}, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "stagnant_nudge" in reminder_types

    def test_dry_run_first_reminder(self):
        state = {"strict_score": 50.0}
        actions = [{"type": "auto_fix", "count": 3, "command": "desloppify fix unused-imports --dry-run"}]
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {},
            actions, {}, {}, None,
        )
        reminder_types = [r["type"] for r in reminders]
        assert "dry_run_first" in reminder_types

    def test_reminders_include_metadata_and_rank_high_priority_first(self):
        state = {"strict_score": 50.0}
        actions = [{"type": "auto_fix", "count": 3, "command": "desloppify fix unused-imports --dry-run"}]
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {"trend": "growing"},
            actions, {}, {}, "fix",
        )
        reminder_types = [r["type"] for r in reminders]
        assert "rescan_needed" in reminder_types
        assert "wontfix_growing" in reminder_types
        assert reminder_types.index("rescan_needed") < reminder_types.index("wontfix_growing")
        assert all("priority" in r for r in reminders)
        assert all("severity" in r for r in reminders)

    def test_does_not_mutate_state(self):
        """The reminder_history on state must not be mutated."""
        original_history = {"rescan_needed": 1}
        state = {
            "strict_score": 50.0,
            "reminder_history": original_history,
        }
        _, updated = _compute_reminders(
            state, "typescript", "middle_grind", {},
            [], {}, {}, "fix",
        )
        # Original should be unchanged
        assert original_history == {"rescan_needed": 1}
        # Updated should have incremented
        assert updated["rescan_needed"] == 2

    def test_feedback_nudge_after_two_scans(self):
        """General feedback nudge appears after 2+ scans with command=scan."""
        state = {
            "strict_score": 50.0,
            "scan_history": [{"strict_score": 45.0}, {"strict_score": 50.0}],
        }
        reminders, _ = _compute_reminders(
            state, "python", "middle_grind", {},
            [], {}, {}, "scan",
        )
        nudge_types = [r["type"] for r in reminders if r["type"] == "feedback_nudge"]
        assert len(nudge_types) == 1
        msg = next(r["message"] for r in reminders if r["type"] == "feedback_nudge")
        assert "issue" in msg.lower()

    def test_no_feedback_nudge_on_first_scan(self):
        """No feedback nudge on the very first scan."""
        state = {
            "strict_score": 50.0,
            "scan_history": [{"strict_score": 50.0}],
        }
        reminders, _ = _compute_reminders(
            state, "python", "first_scan", {},
            [], {}, {}, "scan",
        )
        nudge_types = [r["type"] for r in reminders if r["type"] == "feedback_nudge"]
        assert len(nudge_types) == 0

    def test_no_feedback_nudge_on_non_scan_command(self):
        """Feedback nudge only fires on scan, not fix/show/next."""
        state = {
            "strict_score": 50.0,
            "scan_history": [{"strict_score": 45.0}, {"strict_score": 50.0}],
        }
        for cmd in ("fix", "resolve", "show", "next", None):
            reminders, _ = _compute_reminders(
                state, "python", "middle_grind", {},
                [], {}, {}, cmd,
            )
            nudge_types = [r["type"] for r in reminders if r["type"] == "feedback_nudge"]
            assert len(nudge_types) == 0, f"nudge fired for command={cmd!r}"

    def test_feedback_nudge_stagnation_variant(self):
        """Stagnation phase triggers the stagnation-specific message."""
        state = {
            "strict_score": 70.0,
            "scan_history": [{"strict_score": 70.0}] * 4,
        }
        reminders, _ = _compute_reminders(
            state, "python", "stagnation", {},
            [], {}, {}, "scan",
        )
        nudge = next((r for r in reminders if r["type"] == "feedback_nudge"), None)
        assert nudge is not None
        assert "plateau" in nudge["message"].lower()

    def test_feedback_nudge_fp_variant(self):
        """High FP rate triggers the FP-specific message."""
        # Need 5+ findings per (detector, zone) with >30% FP rate
        findings = {}
        for i in range(4):
            findings[str(i)] = _finding("unused", status="open")
        for i in range(4, 7):
            findings[str(i)] = _finding("unused", status="false_positive")
        # 7 total, 3 FP → 43% FP rate
        state = {
            "strict_score": 50.0,
            "scan_history": [{"strict_score": 45.0}, {"strict_score": 50.0}],
            "findings": findings,
        }
        reminders, _ = _compute_reminders(
            state, "python", "middle_grind", {},
            [], {}, {}, "scan",
        )
        nudge = next((r for r in reminders if r["type"] == "feedback_nudge"), None)
        assert nudge is not None
        assert "false-positive" in nudge["message"].lower()

    def test_feedback_nudge_shared_decay(self):
        """All variants share one decay counter — 3 total then suppressed."""
        state = {
            "strict_score": 50.0,
            "scan_history": [{"strict_score": 45.0}, {"strict_score": 50.0}],
            "reminder_history": {"feedback_nudge": 3},
        }
        # Generic variant
        reminders, _ = _compute_reminders(
            state, "python", "middle_grind", {},
            [], {}, {}, "scan",
        )
        assert not any(r["type"] == "feedback_nudge" for r in reminders)
        # Stagnation variant — still suppressed because same key
        reminders, _ = _compute_reminders(
            state, "python", "stagnation", {},
            [], {}, {}, "scan",
        )
        assert not any(r["type"] == "feedback_nudge" for r in reminders)

    def test_feedback_nudge_contains_url(self):
        """Feedback nudge message includes the issue tracker URL."""
        from desloppify.narrative import _FEEDBACK_URL
        state = {
            "strict_score": 50.0,
            "scan_history": [{"strict_score": 45.0}, {"strict_score": 50.0}],
        }
        reminders, _ = _compute_reminders(
            state, "python", "middle_grind", {},
            [], {}, {}, "scan",
        )
        nudge = next((r for r in reminders if r["type"] == "feedback_nudge"), None)
        assert nudge is not None
        assert _FEEDBACK_URL in nudge["message"]


# ===================================================================
# _compute_headline
# ===================================================================

class TestComputeHeadline:
    def test_milestone_takes_priority(self):
        """If a milestone is set, it becomes the headline."""
        result = _compute_headline(
            phase="maintenance",
            dimensions={"lowest_dimensions": [{"name": "Org", "issues": 3, "impact": 5.0, "strict": 80}]},
            debt={"overall_gap": 0},
            milestone="Crossed 90% strict!",
            diff=None,
            obj_strict=91.0,
            obj_score=91.0,
            stats={"open": 5},
            history=[],
        )
        assert result == "Crossed 90% strict!"

    def test_first_scan_with_dimensions(self):
        result = _compute_headline(
            phase="first_scan",
            dimensions={"lowest_dimensions": [
                {"name": "A", "issues": 1, "impact": 1.0, "strict": 90},
                {"name": "B", "issues": 2, "impact": 2.0, "strict": 80},
                {"name": "C", "issues": 3, "impact": 3.0, "strict": 70},
            ]},
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=70.0,
            obj_score=70.0,
            stats={"open": 15},
            history=[],
        )
        assert result is not None
        assert "First scan complete" in result
        assert "15 open findings" in result
        assert "3 dimensions" in result

    def test_first_scan_no_dimensions(self):
        result = _compute_headline(
            phase="first_scan",
            dimensions={},
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=70.0,
            obj_score=70.0,
            stats={"open": 8},
            history=[],
        )
        assert result is not None
        assert "First scan complete" in result
        assert "8 findings detected" in result

    def test_regression_message(self):
        history = [
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=75.0),
        ]
        result = _compute_headline(
            phase="regression",
            dimensions={},
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=75.0,
            obj_score=75.0,
            stats={"open": 10},
            history=history,
        )
        assert result is not None
        assert "5.0 pts" in result
        assert "normal after structural changes" in result

    def test_stagnation_with_lowest_dim(self):
        history = [
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
        ]
        dimensions = {
            "lowest_dimensions": [
                {"name": "Organization", "issues": 10, "impact": 5.0, "strict": 60.0},
            ],
        }
        result = _compute_headline(
            phase="stagnation",
            dimensions=dimensions,
            debt={"overall_gap": 0, "wontfix_count": 0},
            milestone=None,
            diff=None,
            obj_strict=70.0,
            obj_score=70.0,
            stats={"open": 10},
            history=history,
        )
        assert result is not None
        assert "plateaued" in result
        assert "Organization" in result
        assert "breakthrough" in result

    def test_stagnation_with_wontfix(self):
        history = [
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
            _history_entry(strict_score=70.0),
        ]
        dimensions = {
            "lowest_dimensions": [
                {"name": "Organization", "issues": 10, "impact": 5.0, "strict": 60.0},
            ],
        }
        result = _compute_headline(
            phase="stagnation",
            dimensions=dimensions,
            debt={"overall_gap": 3.0, "wontfix_count": 5},
            milestone=None,
            diff=None,
            obj_strict=70.0,
            obj_score=73.0,
            stats={"open": 10},
            history=history,
        )
        assert result is not None
        assert "wontfix" in result
        assert "5" in result

    def test_leverage_point_headline(self):
        """Lowest dimension with impact > 0 generates a leverage headline."""
        dimensions = {
            "lowest_dimensions": [
                {"name": "Import hygiene", "issues": 20, "impact": 8.5, "strict": 70.0},
            ],
        }
        result = _compute_headline(
            phase="refinement",
            dimensions=dimensions,
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=82.0,
            obj_score=82.0,
            stats={"open": 20},
            history=[_history_entry()] * 6,
        )
        assert result is not None
        assert "Import hygiene" in result
        assert "biggest lever" in result
        assert "+8.5 pts" in result

    def test_maintenance_headline(self):
        result = _compute_headline(
            phase="maintenance",
            dimensions={"lowest_dimensions": []},
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=95.0,
            obj_score=95.0,
            stats={"open": 2},
            history=[_history_entry()] * 10,
        )
        assert result is not None
        assert "maintenance mode" in result
        assert "95.0" in result

    def test_middle_grind_with_lowest_dim(self):
        dimensions = {
            "lowest_dimensions": [
                {"name": "Debug cleanliness", "issues": 15, "impact": 0, "strict": 55.0},
            ],
        }
        result = _compute_headline(
            phase="middle_grind",
            dimensions=dimensions,
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=60.0,
            obj_score=60.0,
            stats={"open": 30},
            history=[_history_entry()] * 6,
        )
        assert result is not None
        assert "30 findings open" in result
        assert "Debug cleanliness" in result
        assert "`desloppify next`" in result

    def test_early_momentum_headline(self):
        result = _compute_headline(
            phase="early_momentum",
            dimensions={"lowest_dimensions": []},
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=72.0,
            obj_score=72.0,
            stats={"open": 10},
            history=[_history_entry()] * 3,
        )
        assert result is not None
        assert "72.0" in result
        assert "momentum" in result

    def test_returns_none_when_no_headline_matches(self):
        """Edge case: early_momentum with obj_strict None."""
        result = _compute_headline(
            phase="early_momentum",
            dimensions={"lowest_dimensions": []},
            debt={"overall_gap": 0},
            milestone=None,
            diff=None,
            obj_strict=None,
            obj_score=None,
            stats={"open": 0},
            history=[],
        )
        assert result is None

    def test_gap_callout_headline(self):
        """Debt gap > 5 generates gap callout headline."""
        result = _compute_headline(
            phase="refinement",
            dimensions={"lowest_dimensions": []},
            debt={"overall_gap": 8.0, "worst_dimension": "Organization"},
            milestone=None,
            diff=None,
            obj_strict=82.0,
            obj_score=90.0,
            stats={"open": 10},
            history=[_history_entry()] * 6,
        )
        assert result is not None
        assert "wontfix debt" in result
        assert "Organization" in result


# ===================================================================
# _open_files_by_detector
# ===================================================================

class TestOpenFilesByDetector:
    def test_empty_findings(self):
        assert _open_files_by_detector({}) == {}

    def test_only_open_counted(self):
        findings = _findings_dict(
            _finding("unused", status="open", file="a.py"),
            _finding("unused", status="resolved", file="b.py"),
            _finding("unused", status="wontfix", file="c.py"),
        )
        result = _open_files_by_detector(findings)
        assert result == {"unused": {"a.py"}}

    def test_multiple_detectors(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
            _finding("logs", file="b.py"),
        )
        result = _open_files_by_detector(findings)
        assert result == {"unused": {"a.py"}, "logs": {"b.py"}}

    def test_structural_merge(self):
        findings = _findings_dict(
            _finding("large", file="big.py"),
            _finding("complexity", file="complex.py"),
        )
        result = _open_files_by_detector(findings)
        assert result == {"structural": {"big.py", "complex.py"}}

    def test_dedup_same_file(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
            _finding("unused", file="a.py"),
        )
        result = _open_files_by_detector(findings)
        assert result == {"unused": {"a.py"}}

    def test_empty_file_excluded(self):
        findings = _findings_dict(
            _finding("unused", file=""),
            _finding("unused", file="a.py"),
        )
        result = _open_files_by_detector(findings)
        assert result == {"unused": {"a.py"}}


# ===================================================================
# _compute_fixer_leverage
# ===================================================================

class TestFixerLeverage:
    def test_no_auto_fix_actions_recommend_none(self):
        result = _compute_fixer_leverage(
            {"unused": 10}, [{"type": "manual_fix", "count": 10, "impact": 5.0}],
            "middle_grind", "python",
        )
        assert result["recommendation"] == "none"

    def test_no_auto_fix_findings(self):
        result = _compute_fixer_leverage(
            {"structural": 10}, [{"type": "refactor", "count": 10, "impact": 5.0}],
            "middle_grind", "typescript",
        )
        assert result["recommendation"] == "none"
        assert result["auto_fixable_count"] == 0

    def test_high_coverage_strong(self):
        result = _compute_fixer_leverage(
            {"unused": 50, "logs": 10},
            [{"type": "auto_fix", "count": 50, "impact": 8.0},
             {"type": "refactor", "count": 10, "impact": 2.0}],
            "middle_grind", "typescript",
        )
        assert result["recommendation"] == "strong"
        assert result["coverage"] > 0.4

    def test_high_impact_ratio_strong(self):
        result = _compute_fixer_leverage(
            {"unused": 5, "structural": 40},
            [{"type": "auto_fix", "count": 5, "impact": 8.0},
             {"type": "refactor", "count": 40, "impact": 2.0}],
            "middle_grind", "typescript",
        )
        # impact_ratio = 8/10 = 0.8 > 0.3
        assert result["recommendation"] == "strong"

    def test_phase_boost_first_scan(self):
        result = _compute_fixer_leverage(
            {"unused": 10, "structural": 40},
            [{"type": "auto_fix", "count": 10, "impact": 1.0},
             {"type": "refactor", "count": 40, "impact": 5.0}],
            "first_scan", "typescript",
        )
        # coverage = 10/50 = 0.2 > 0.15, phase is first_scan
        assert result["recommendation"] == "strong"

    def test_phase_boost_stagnation(self):
        result = _compute_fixer_leverage(
            {"unused": 10, "structural": 40},
            [{"type": "auto_fix", "count": 10, "impact": 1.0},
             {"type": "refactor", "count": 40, "impact": 5.0}],
            "stagnation", "typescript",
        )
        assert result["recommendation"] == "strong"

    def test_moderate_coverage(self):
        result = _compute_fixer_leverage(
            {"unused": 8, "structural": 60},
            [{"type": "auto_fix", "count": 8, "impact": 1.0},
             {"type": "refactor", "count": 60, "impact": 10.0}],
            "middle_grind", "typescript",
        )
        # coverage = 8/68 ≈ 0.12 > 0.1, impact_ratio = 1/11 ≈ 0.09 < 0.3
        assert result["recommendation"] == "moderate"

    def test_low_coverage_none(self):
        result = _compute_fixer_leverage(
            {"unused": 2, "structural": 60},
            [{"type": "auto_fix", "count": 2, "impact": 0.5},
             {"type": "refactor", "count": 60, "impact": 10.0}],
            "middle_grind", "typescript",
        )
        # coverage = 2/62 ≈ 0.03 < 0.1
        assert result["recommendation"] == "none"


# ===================================================================
# _compute_lanes
# ===================================================================

class TestComputeLanes:
    def test_empty_actions(self):
        assert _compute_lanes([], {}) == {}

    def test_single_auto_fix_cleanup_lane(self):
        actions = [{"priority": 1, "type": "auto_fix", "detector": "unused",
                     "count": 5, "impact": 3.0}]
        files = {"unused": {"a.py", "b.py"}}
        lanes = _compute_lanes(actions, files)
        assert "cleanup" in lanes
        assert lanes["cleanup"]["actions"] == [1]
        assert lanes["cleanup"]["file_count"] == 2
        assert lanes["cleanup"]["automation"] == "full"

    def test_single_reorganize_restructure_lane(self):
        actions = [{"priority": 1, "type": "reorganize", "detector": "orphaned",
                     "count": 3, "impact": 2.0}]
        files = {"orphaned": {"x.py"}}
        lanes = _compute_lanes(actions, files)
        assert "restructure" in lanes
        assert lanes["restructure"]["actions"] == [1]
        assert lanes["restructure"]["automation"] == "manual"

    def test_independent_refactor_lanes(self):
        actions = [
            {"priority": 1, "type": "refactor", "detector": "structural",
             "count": 5, "impact": 3.0},
            {"priority": 2, "type": "refactor", "detector": "props",
             "count": 4, "impact": 2.0},
        ]
        files = {
            "structural": {"a.py", "b.py"},
            "props": {"c.tsx", "d.tsx"},  # disjoint from structural
        }
        lanes = _compute_lanes(actions, files)
        # Should create two separate refactor lanes
        refactor_lanes = [n for n in lanes if n.startswith("refactor")]
        assert len(refactor_lanes) == 2

    def test_overlapping_refactors_merged(self):
        actions = [
            {"priority": 1, "type": "refactor", "detector": "structural",
             "count": 5, "impact": 3.0},
            {"priority": 2, "type": "refactor", "detector": "props",
             "count": 4, "impact": 2.0},
        ]
        files = {
            "structural": {"a.py", "shared.py"},
            "props": {"shared.py", "c.tsx"},  # overlap via shared.py
        }
        lanes = _compute_lanes(actions, files)
        refactor_lanes = [n for n in lanes if n.startswith("refactor")]
        assert len(refactor_lanes) == 1
        assert sorted(lanes[refactor_lanes[0]]["actions"]) == [1, 2]

    def test_test_coverage_always_separate(self):
        actions = [
            {"priority": 1, "type": "refactor", "detector": "structural",
             "count": 5, "impact": 3.0},
            {"priority": 2, "type": "refactor", "detector": "test_coverage",
             "count": 4, "impact": 2.0},
        ]
        files = {
            "structural": {"a.py"},
            "test_coverage": {"a.py"},  # same file, but test_coverage separated
        }
        lanes = _compute_lanes(actions, files)
        assert "test_coverage" in lanes
        refactor_lanes = [n for n in lanes if n.startswith("refactor")]
        assert len(refactor_lanes) == 1
        assert 2 not in lanes[refactor_lanes[0]]["actions"]

    def test_cascade_ordering_in_cleanup(self):
        actions = [
            {"priority": 1, "type": "auto_fix", "detector": "unused",
             "count": 5, "impact": 3.0},
            {"priority": 2, "type": "auto_fix", "detector": "logs",
             "count": 3, "impact": 2.0},
        ]
        files = {"unused": {"a.py"}, "logs": {"b.py"}}
        lanes = _compute_lanes(actions, files)
        # logs cascades into unused, so logs should come first
        assert lanes["cleanup"]["actions"] == [2, 1]

    def test_debt_review_lane(self):
        actions = [{"priority": 1, "type": "debt_review", "detector": None,
                     "count": 0, "impact": 0.0, "gap": 5.0}]
        lanes = _compute_lanes(actions, {})
        assert "debt_review" in lanes
        assert lanes["debt_review"]["file_count"] == 0

    def test_cleanup_run_first_on_overlap(self):
        actions = [
            {"priority": 1, "type": "auto_fix", "detector": "unused",
             "count": 5, "impact": 3.0},
            {"priority": 2, "type": "refactor", "detector": "structural",
             "count": 4, "impact": 2.0},
        ]
        files = {
            "unused": {"a.py", "shared.py"},
            "structural": {"shared.py", "b.py"},
        }
        lanes = _compute_lanes(actions, files)
        assert lanes["cleanup"]["run_first"] is True

    def test_cleanup_no_run_first_when_disjoint(self):
        actions = [
            {"priority": 1, "type": "auto_fix", "detector": "unused",
             "count": 5, "impact": 3.0},
            {"priority": 2, "type": "refactor", "detector": "structural",
             "count": 4, "impact": 2.0},
        ]
        files = {
            "unused": {"a.py"},
            "structural": {"b.py"},
        }
        lanes = _compute_lanes(actions, files)
        assert lanes["cleanup"]["run_first"] is False


# ===================================================================
# _compute_strategy_hint
# ===================================================================

class TestComputeStrategyHint:
    def test_strong_fixer_and_parallel(self):
        fixer = {"recommendation": "strong", "coverage": 0.5}
        lanes = {
            "cleanup": {"run_first": True, "file_count": 10, "total_impact": 5.0},
            "refactor_0": {"run_first": False, "file_count": 8, "total_impact": 3.0},
            "refactor_1": {"run_first": False, "file_count": 6, "total_impact": 2.0},
        }
        hint = _compute_strategy_hint(fixer, lanes, True, "middle_grind")
        assert "fixers first" in hint.lower()
        assert "parallelize" in hint.lower()

    def test_strong_fixer_only(self):
        fixer = {"recommendation": "strong", "coverage": 0.45}
        lanes = {"cleanup": {"run_first": False, "file_count": 10, "total_impact": 5.0}}
        hint = _compute_strategy_hint(fixer, lanes, False, "middle_grind")
        assert "fixers first" in hint.lower()
        assert "45%" in hint

    def test_no_fixer_parallel(self):
        fixer = {"recommendation": "none", "coverage": 0.0}
        lanes = {
            "refactor_0": {"run_first": False, "file_count": 8, "total_impact": 3.0},
            "refactor_1": {"run_first": False, "file_count": 6, "total_impact": 2.0},
        }
        hint = _compute_strategy_hint(fixer, lanes, True, "middle_grind")
        assert "parallelize" in hint.lower()

    def test_maintenance_fallback(self):
        fixer = {"recommendation": "none", "coverage": 0.0}
        lanes = {"refactor": {"run_first": False, "file_count": 2, "total_impact": 1.0}}
        hint = _compute_strategy_hint(fixer, lanes, False, "maintenance")
        assert "maintenance" in hint.lower()

    def test_stagnation_fallback(self):
        fixer = {"recommendation": "none", "coverage": 0.0}
        lanes = {}
        hint = _compute_strategy_hint(fixer, lanes, False, "stagnation")
        assert "plateau" in hint.lower()

    def test_default_fallback(self):
        fixer = {"recommendation": "none", "coverage": 0.0}
        lanes = {}
        hint = _compute_strategy_hint(fixer, lanes, False, "middle_grind")
        assert "priority order" in hint.lower()

    def test_rescan_in_strong_parallel(self):
        fixer = {"recommendation": "strong", "coverage": 0.5}
        lanes = {
            "cleanup": {"run_first": True, "file_count": 10, "total_impact": 5.0},
            "refactor_0": {"run_first": False, "file_count": 8, "total_impact": 3.0},
            "refactor_1": {"run_first": False, "file_count": 6, "total_impact": 2.0},
        }
        hint = _compute_strategy_hint(fixer, lanes, True, "middle_grind")
        assert "rescan" in hint.lower()

    def test_rescan_in_strong_only(self):
        fixer = {"recommendation": "strong", "coverage": 0.45}
        lanes = {"cleanup": {"run_first": False, "file_count": 10, "total_impact": 5.0}}
        hint = _compute_strategy_hint(fixer, lanes, False, "middle_grind")
        assert "rescan" in hint.lower()

    def test_rescan_in_parallel_only(self):
        fixer = {"recommendation": "none", "coverage": 0.0}
        lanes = {
            "refactor_0": {"run_first": False, "file_count": 8, "total_impact": 3.0},
            "refactor_1": {"run_first": False, "file_count": 6, "total_impact": 2.0},
        }
        hint = _compute_strategy_hint(fixer, lanes, True, "middle_grind")
        assert "rescan" in hint.lower()

    def test_rescan_in_default_fallback(self):
        fixer = {"recommendation": "none", "coverage": 0.0}
        lanes = {}
        hint = _compute_strategy_hint(fixer, lanes, False, "middle_grind")
        assert "rescan" in hint.lower()


# ===================================================================
# _compute_strategy
# ===================================================================

class TestComputeStrategy:
    def test_structure_has_expected_keys(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        actions = [{"priority": 1, "type": "auto_fix", "detector": "unused",
                     "count": 1, "impact": 1.0}]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        assert "fixer_leverage" in result
        assert "lanes" in result
        assert "can_parallelize" in result
        assert "hint" in result

    def test_actions_annotated_with_lane(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
            _finding("structural", file="b.py"),
        )
        by_det = {"unused": 1, "structural": 1}
        actions = [
            {"priority": 1, "type": "auto_fix", "detector": "unused",
             "count": 1, "impact": 1.0},
            {"priority": 2, "type": "refactor", "detector": "structural",
             "count": 1, "impact": 2.0},
        ]
        _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        assert actions[0].get("lane") == "cleanup"
        assert actions[1].get("lane") is not None
        assert actions[1]["lane"].startswith("refactor")

    def test_python_no_cleanup_lane(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        # Python actions are manual_fix, not auto_fix
        actions = [{"priority": 1, "type": "manual_fix", "detector": "unused",
                     "count": 1, "impact": 1.0}]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "python")
        assert "cleanup" not in result["lanes"]
        assert result["fixer_leverage"]["recommendation"] == "none"

    def test_can_parallelize_true(self):
        findings = _findings_dict(
            *[_finding("structural", file=f"file_{i}.py") for i in range(10)],
            *[_finding("props", file=f"comp_{i}.tsx") for i in range(10)],
        )
        by_det = {"structural": 10, "props": 10}
        actions = [
            {"priority": 1, "type": "refactor", "detector": "structural",
             "count": 10, "impact": 5.0},
            {"priority": 2, "type": "refactor", "detector": "props",
             "count": 10, "impact": 3.0},
        ]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        assert result["can_parallelize"] is True

    def test_can_parallelize_ignores_insignificant_lanes(self):
        """One tiny lane shouldn't block parallelism of larger lanes."""
        findings = _findings_dict(
            *[_finding("structural", file=f"file_{i}.py") for i in range(10)],
            *[_finding("props", file=f"comp_{i}.tsx") for i in range(10)],
            _finding("deprecated", file="tiny.ts"),  # 1 file, tiny lane
        )
        by_det = {"structural": 10, "props": 10, "deprecated": 1}
        actions = [
            {"priority": 1, "type": "refactor", "detector": "structural",
             "count": 10, "impact": 5.0},
            {"priority": 2, "type": "refactor", "detector": "props",
             "count": 10, "impact": 3.0},
            {"priority": 3, "type": "manual_fix", "detector": "deprecated",
             "count": 1, "impact": 0.2},
        ]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        # structural and props are significant, deprecated is not — still parallelizable
        assert result["can_parallelize"] is True

    def test_can_parallelize_false_single_lane(self):
        findings = _findings_dict(
            _finding("structural", file="a.py"),
        )
        by_det = {"structural": 1}
        actions = [{"priority": 1, "type": "refactor", "detector": "structural",
                     "count": 1, "impact": 1.0}]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        assert result["can_parallelize"] is False


# ===================================================================
# Review headline / reminder / strategy tests
# ===================================================================

class TestReviewHeadline:
    """Headline should mention review findings in all phases."""

    def test_review_suffix_in_middle_grind(self):
        """Review suffix should appear even during middle_grind (not just maintenance)."""
        by_det = {"unused": 5, "review": 3, "review_uninvestigated": 2}
        headline = _compute_headline(
            "middle_grind", {"lowest_dimensions": []}, {}, None, None,
            85.0, 85.0, {"open": 8}, [],
            open_by_detector=by_det,
        )
        assert headline is not None
        assert "review finding" in headline.lower()

    def test_review_suffix_with_uninvestigated(self):
        """Uninvestigated review findings should mention `desloppify issues`."""
        by_det = {"review": 2, "review_uninvestigated": 2}
        headline = _compute_headline(
            "maintenance", {}, {}, None, None,
            95.0, 95.0, {}, [],
            open_by_detector=by_det,
        )
        assert headline is not None
        assert "desloppify issues" in headline

    def test_review_suffix_all_investigated(self):
        """When all review findings are investigated, show 'pending' not 'issues'."""
        by_det = {"review": 2, "review_uninvestigated": 0}
        headline = _compute_headline(
            "maintenance", {}, {}, None, None,
            95.0, 95.0, {}, [],
            open_by_detector=by_det,
        )
        assert headline is not None
        assert "pending" in headline
        assert "desloppify issues" not in headline

    def test_no_review_suffix_when_zero(self):
        by_det = {"unused": 3, "review": 0, "review_uninvestigated": 0}
        headline = _compute_headline(
            "middle_grind", {"lowest_dimensions": []}, {}, None, None,
            85.0, 85.0, {"open": 3}, [],
            open_by_detector=by_det,
        )
        # Should not mention review at all
        if headline:
            assert "review finding" not in headline.lower()


class TestReviewUninvestigatedCount:
    """_count_open_by_detector should track review_uninvestigated."""

    def test_uninvestigated_count(self):
        findings = {
            "a": {"status": "open", "detector": "review", "detail": {}},
            "b": {"status": "open", "detector": "review",
                   "detail": {"investigation": "looked at it"}},
            "c": {"status": "open", "detector": "review", "detail": {}},
            "d": {"status": "fixed", "detector": "review", "detail": {}},
        }
        result = _count_open_by_detector(findings)
        assert result["review"] == 3  # a, b, c
        assert result["review_uninvestigated"] == 2  # a, c

    def test_no_review_findings(self):
        findings = {
            "a": {"status": "open", "detector": "unused"},
        }
        result = _count_open_by_detector(findings)
        assert result.get("review_uninvestigated", 0) == 0


class TestReviewReminders:
    """Review-related reminders: pending findings + re-review needed."""

    def _base_state(self):
        return {
            "findings": {
                "r1": {"status": "open", "detector": "review",
                        "detail": {}},
                "r2": {"status": "open", "detector": "review",
                        "detail": {"investigation": "done"}},
            },
            "reminder_history": {},
        }

    def test_review_findings_pending_reminder(self):
        state = self._base_state()
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "scan")
        types = [r["type"] for r in reminders]
        assert "review_findings_pending" in types
        msg = next(r for r in reminders if r["type"] == "review_findings_pending")
        assert "1 review finding" in msg["message"]
        assert "desloppify issues" in msg["message"]

    def test_no_review_pending_when_all_investigated(self):
        state = self._base_state()
        state["findings"]["r1"]["detail"]["investigation"] = "done too"
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "scan")
        types = [r["type"] for r in reminders]
        assert "review_findings_pending" not in types

    def test_rereview_needed_after_resolve(self):
        state = self._base_state()
        state["subjective_assessments"] = {"naming_quality": {"score": 70}}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "resolve")
        types = [r["type"] for r in reminders]
        assert "rereview_needed" in types
        msg = next(r for r in reminders if r["type"] == "rereview_needed")
        assert "review --prepare" in msg["message"]

    def test_no_rereview_when_not_resolve_command(self):
        state = self._base_state()
        state["subjective_assessments"] = {"naming_quality": {"score": 70}}
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "scan")
        types = [r["type"] for r in reminders]
        assert "rereview_needed" not in types

    def test_no_rereview_without_assessments(self):
        state = self._base_state()
        reminders, _ = _compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "resolve")
        types = [r["type"] for r in reminders]
        assert "rereview_needed" not in types


class TestStrategyReviewHint:
    """Strategy hint should mention review findings when issue_queue action exists."""

    def test_review_appended_to_hint(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        actions = [
            {"priority": 1, "type": "auto_fix", "detector": "unused",
             "count": 1, "impact": 1.0, "command": "desloppify fix unused"},
            {"priority": 2, "type": "issue_queue", "detector": "review",
             "count": 3, "impact": 0, "command": "desloppify issues"},
        ]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        assert "desloppify issues" in result["hint"]
        assert "3 finding" in result["hint"]

    def test_no_review_in_hint_without_action(self):
        findings = _findings_dict(
            _finding("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        actions = [
            {"priority": 1, "type": "auto_fix", "detector": "unused",
             "count": 1, "impact": 1.0, "command": "desloppify fix unused"},
        ]
        result = _compute_strategy(findings, by_det, actions, "middle_grind", "typescript")
        assert "desloppify issues" not in result["hint"]


class TestComputeNarrativeContract:
    def test_includes_primary_action_verification_and_risks(self):
        state = {
            "overall_score": 84.0,
            "objective_score": 82.0,
            "strict_score": 78.0,
            "scan_history": [
                _history_entry(strict_score=75.0, objective_score=78.0, lang="typescript"),
                _history_entry(strict_score=78.0, objective_score=82.0, lang="typescript"),
            ],
            "dimension_scores": {
                "Code quality": {
                    "score": 78.0,
                    "strict": 72.0,
                    "tier": 2,
                    "issues": 4,
                    "checks": 10,
                    "detectors": {"smells": {"issues": 4}},
                },
            },
            "stats": {"open": 4, "total": 6},
            "findings": {
                "smells::a.ts::foo": {
                    "id": "smells::a.ts::foo",
                    "status": "open",
                    "detector": "smells",
                    "file": "a.ts",
                    "tier": 2,
                    "confidence": "high",
                    "summary": "smell",
                },
                "smells::b.ts::bar": {
                    "id": "smells::b.ts::bar",
                    "status": "wontfix",
                    "detector": "smells",
                    "file": "b.ts",
                    "tier": 2,
                    "confidence": "medium",
                    "summary": "intentional smell",
                    "note": "intentional",
                },
            },
            "ignore_integrity": {"ignored": 12, "suppressed_pct": 40.0},
            "reminder_history": {},
        }

        narrative = compute_narrative(
            state,
            lang="typescript",
            command="scan",
            config={"review_max_age_days": 30},
        )
        assert "primary_action" in narrative
        assert "why_now" in narrative
        assert "verification_step" in narrative
        assert "risk_flags" in narrative
        assert narrative["primary_action"] is not None
        assert narrative["verification_step"] is not None
        assert narrative["verification_step"]["command"] == "desloppify scan"
        assert isinstance(narrative["why_now"], str)
        assert narrative["why_now"] != ""
        assert isinstance(narrative["risk_flags"], list)
        risk_types = {f["type"] for f in narrative["risk_flags"]}
        assert "high_ignore_suppression" in risk_types
        assert "wontfix_gap" in risk_types
        assert narrative["strict_target"]["target"] == 95.0
        assert narrative["strict_target"]["current"] == 78.0
        assert narrative["strict_target"]["gap"] == 17.0
        assert narrative["strict_target"]["state"] == "below"

    def test_strict_target_invalid_config_falls_back(self):
        state = {
            "strict_score": 91.0,
            "scan_history": [_history_entry(strict_score=91.0, lang="typescript")],
            "dimension_scores": {},
            "stats": {"open": 1, "total": 1},
            "findings": {},
            "reminder_history": {},
        }
        narrative = compute_narrative(
            state,
            lang="typescript",
            command="scan",
            config={"target_strict_score": "nope"},
        )
        strict_target = narrative["strict_target"]
        assert strict_target["target"] == 95.0
        assert strict_target["current"] == 91.0
        assert strict_target["gap"] == 4.0
        assert strict_target["state"] == "below"
        assert "Invalid config `target_strict_score='nope'`" in strict_target["warning"]
