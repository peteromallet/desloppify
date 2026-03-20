"""Split narrative tests: headline, strategy, and review reminder flows."""

from __future__ import annotations

from desloppify.intelligence.narrative.core import (
    NarrativeContext,
    _count_open_by_detector,
    compute_narrative,
)
from desloppify.intelligence.narrative.headline import compute_headline
from desloppify.intelligence.narrative.reminders import compute_reminders
from desloppify.intelligence.narrative.strategy_engine import (
    compute_fixer_leverage as _compute_fixer_leverage,
)
from desloppify.intelligence.narrative.strategy_engine import (
    compute_lanes as _compute_lanes,
)
from desloppify.intelligence.narrative.strategy_engine import (
    compute_strategy as _compute_strategy,
)
from desloppify.intelligence.narrative.strategy_engine import (
    compute_strategy_hint as _compute_strategy_hint,
)
from desloppify.intelligence.narrative.strategy_engine import (
    open_files_by_detector as _open_files_by_detector,
)
from desloppify.tests.narrative.test_narrative import _history_entry, _issue, _issues_dict
# compute_headline
# ===================================================================


class TestComputeHeadline:
    def test_milestone_takes_priority(self):
        """If a milestone is set, it becomes the headline."""
        result = compute_headline(
            phase="maintenance",
            dimensions={
                "lowest_dimensions": [
                    {"name": "Org", "failing": 3, "impact": 5.0, "strict": 80}
                ]
            },
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
        result = compute_headline(
            phase="first_scan",
            dimensions={
                "lowest_dimensions": [
                    {"name": "A", "failing": 1, "impact": 1.0, "strict": 90},
                    {"name": "B", "failing": 2, "impact": 2.0, "strict": 80},
                    {"name": "C", "failing": 3, "impact": 3.0, "strict": 70},
                ]
            },
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
        assert "15 open issues" in result
        assert "3 dimensions" in result

    def test_first_scan_no_dimensions(self):
        result = compute_headline(
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
        assert "8 issues detected" in result

    def test_regression_message(self):
        history = [
            _history_entry(strict_score=80.0),
            _history_entry(strict_score=75.0),
        ]
        result = compute_headline(
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
                {"name": "Organization", "failing": 10, "impact": 5.0, "strict": 60.0},
            ],
        }
        result = compute_headline(
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
                {"name": "Organization", "failing": 10, "impact": 5.0, "strict": 60.0},
            ],
        }
        result = compute_headline(
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
                {"name": "Import hygiene", "failing": 20, "impact": 8.5, "strict": 70.0},
            ],
        }
        result = compute_headline(
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
        result = compute_headline(
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
                {
                    "name": "Debug cleanliness",
                    "failing": 15,
                    "impact": 0,
                    "strict": 55.0,
                },
            ],
        }
        result = compute_headline(
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
        assert "30 issues open" in result
        assert "Debug cleanliness" in result
        assert "`desloppify next`" in result

    def test_early_momentum_headline(self):
        result = compute_headline(
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
        result = compute_headline(
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
        result = compute_headline(
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
    def test_empty_issues(self):
        assert _open_files_by_detector({}) == {}

    def test_only_open_counted(self):
        issues = _issues_dict(
            _issue("unused", status="open", file="a.py"),
            _issue("unused", status="resolved", file="b.py"),
            _issue("unused", status="wontfix", file="c.py"),
        )
        result = _open_files_by_detector(issues)
        assert result == {"unused": {"a.py"}}

    def test_multiple_detectors(self):
        issues = _issues_dict(
            _issue("unused", file="a.py"),
            _issue("logs", file="b.py"),
        )
        result = _open_files_by_detector(issues)
        assert result == {"unused": {"a.py"}, "logs": {"b.py"}}

    def test_structural_merge(self):
        issues = _issues_dict(
            _issue("large", file="big.py"),
            _issue("complexity", file="complex.py"),
        )
        result = _open_files_by_detector(issues)
        assert result == {"structural": {"big.py", "complex.py"}}

    def test_dedup_same_file(self):
        issues = _issues_dict(
            _issue("unused", file="a.py"),
            _issue("unused", file="a.py"),
        )
        result = _open_files_by_detector(issues)
        assert result == {"unused": {"a.py"}}

    def test_empty_file_excluded(self):
        issues = _issues_dict(
            _issue("unused", file=""),
            _issue("unused", file="a.py"),
        )
        result = _open_files_by_detector(issues)
        assert result == {"unused": {"a.py"}}


# ===================================================================
# _compute_fixer_leverage
# ===================================================================


class TestFixerLeverage:
    def test_no_auto_fix_actions_recommend_none(self):
        result = _compute_fixer_leverage(
            {"unused": 10},
            [{"type": "manual_fix", "count": 10, "impact": 5.0}],
            "middle_grind",
            "python",
        )
        assert result["recommendation"] == "none"

    def test_no_auto_fix_issues(self):
        result = _compute_fixer_leverage(
            {"structural": 10},
            [{"type": "refactor", "count": 10, "impact": 5.0}],
            "middle_grind",
            "typescript",
        )
        assert result["recommendation"] == "none"
        assert result["auto_fixable_count"] == 0

    def test_high_coverage_strong(self):
        result = _compute_fixer_leverage(
            {"unused": 50, "logs": 10},
            [
                {"type": "auto_fix", "count": 50, "impact": 8.0},
                {"type": "refactor", "count": 10, "impact": 2.0},
            ],
            "middle_grind",
            "typescript",
        )
        assert result["recommendation"] == "strong"
        assert result["coverage"] > 0.4

    def test_high_impact_ratio_strong(self):
        result = _compute_fixer_leverage(
            {"unused": 5, "structural": 40},
            [
                {"type": "auto_fix", "count": 5, "impact": 8.0},
                {"type": "refactor", "count": 40, "impact": 2.0},
            ],
            "middle_grind",
            "typescript",
        )
        # impact_ratio = 8/10 = 0.8 > 0.3
        assert result["recommendation"] == "strong"

    def test_phase_boost_first_scan(self):
        result = _compute_fixer_leverage(
            {"unused": 10, "structural": 40},
            [
                {"type": "auto_fix", "count": 10, "impact": 1.0},
                {"type": "refactor", "count": 40, "impact": 5.0},
            ],
            "first_scan",
            "typescript",
        )
        # coverage = 10/50 = 0.2 > 0.15, phase is first_scan
        assert result["recommendation"] == "strong"

    def test_phase_boost_stagnation(self):
        result = _compute_fixer_leverage(
            {"unused": 10, "structural": 40},
            [
                {"type": "auto_fix", "count": 10, "impact": 1.0},
                {"type": "refactor", "count": 40, "impact": 5.0},
            ],
            "stagnation",
            "typescript",
        )
        assert result["recommendation"] == "strong"

    def test_moderate_coverage(self):
        result = _compute_fixer_leverage(
            {"unused": 8, "structural": 60},
            [
                {"type": "auto_fix", "count": 8, "impact": 1.0},
                {"type": "refactor", "count": 60, "impact": 10.0},
            ],
            "middle_grind",
            "typescript",
        )
        # coverage = 8/68 ≈ 0.12 > 0.1, impact_ratio = 1/11 ≈ 0.09 < 0.3
        assert result["recommendation"] == "moderate"

    def test_low_coverage_none(self):
        result = _compute_fixer_leverage(
            {"unused": 2, "structural": 60},
            [
                {"type": "auto_fix", "count": 2, "impact": 0.5},
                {"type": "refactor", "count": 60, "impact": 10.0},
            ],
            "middle_grind",
            "typescript",
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
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 5,
                "impact": 3.0,
            }
        ]
        files = {"unused": {"a.py", "b.py"}}
        lanes = _compute_lanes(actions, files)
        assert "cleanup" in lanes
        assert lanes["cleanup"]["actions"] == [1]
        assert lanes["cleanup"]["file_count"] == 2
        assert lanes["cleanup"]["automation"] == "full"

    def test_single_reorganize_restructure_lane(self):
        actions = [
            {
                "priority": 1,
                "type": "reorganize",
                "detector": "orphaned",
                "count": 3,
                "impact": 2.0,
            }
        ]
        files = {"orphaned": {"x.py"}}
        lanes = _compute_lanes(actions, files)
        assert "restructure" in lanes
        assert lanes["restructure"]["actions"] == [1]
        assert lanes["restructure"]["automation"] == "manual"

    def test_independent_refactor_lanes(self):
        actions = [
            {
                "priority": 1,
                "type": "refactor",
                "detector": "structural",
                "count": 5,
                "impact": 3.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "props",
                "count": 4,
                "impact": 2.0,
            },
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
            {
                "priority": 1,
                "type": "refactor",
                "detector": "structural",
                "count": 5,
                "impact": 3.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "props",
                "count": 4,
                "impact": 2.0,
            },
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
            {
                "priority": 1,
                "type": "refactor",
                "detector": "structural",
                "count": 5,
                "impact": 3.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "test_coverage",
                "count": 4,
                "impact": 2.0,
            },
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
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 5,
                "impact": 3.0,
            },
            {
                "priority": 2,
                "type": "auto_fix",
                "detector": "logs",
                "count": 3,
                "impact": 2.0,
            },
        ]
        files = {"unused": {"a.py"}, "logs": {"b.py"}}
        lanes = _compute_lanes(actions, files)
        # logs cascades into unused, so logs should come first
        assert lanes["cleanup"]["actions"] == [2, 1]

    def test_debt_review_lane(self):
        actions = [
            {
                "priority": 1,
                "type": "debt_review",
                "detector": None,
                "count": 0,
                "impact": 0.0,
                "gap": 5.0,
            }
        ]
        lanes = _compute_lanes(actions, {})
        assert "debt_review" in lanes
        assert lanes["debt_review"]["file_count"] == 0

    def test_cleanup_run_first_on_overlap(self):
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 5,
                "impact": 3.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "structural",
                "count": 4,
                "impact": 2.0,
            },
        ]
        files = {
            "unused": {"a.py", "shared.py"},
            "structural": {"shared.py", "b.py"},
        }
        lanes = _compute_lanes(actions, files)
        assert lanes["cleanup"]["run_first"] is True

    def test_cleanup_no_run_first_when_disjoint(self):
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 5,
                "impact": 3.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "structural",
                "count": 4,
                "impact": 2.0,
            },
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
        issues = _issues_dict(
            _issue("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 1,
                "impact": 1.0,
            }
        ]
        result = _compute_strategy(
            issues, by_det, actions, "middle_grind", "typescript"
        )
        assert "fixer_leverage" in result
        assert "lanes" in result
        assert "can_parallelize" in result
        assert "hint" in result

    def test_actions_annotated_with_lane(self):
        issues = _issues_dict(
            _issue("unused", file="a.py"),
            _issue("structural", file="b.py"),
        )
        by_det = {"unused": 1, "structural": 1}
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 1,
                "impact": 1.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "structural",
                "count": 1,
                "impact": 2.0,
            },
        ]
        _compute_strategy(issues, by_det, actions, "middle_grind", "typescript")
        assert actions[0].get("lane") == "cleanup"
        assert actions[1].get("lane") is not None
        assert actions[1]["lane"].startswith("refactor")

    def test_python_no_cleanup_lane(self):
        issues = _issues_dict(
            _issue("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        # Python actions are manual_fix, not auto_fix
        actions = [
            {
                "priority": 1,
                "type": "manual_fix",
                "detector": "unused",
                "count": 1,
                "impact": 1.0,
            }
        ]
        result = _compute_strategy(issues, by_det, actions, "middle_grind", "python")
        assert "cleanup" not in result["lanes"]
        assert result["fixer_leverage"]["recommendation"] == "none"

    def test_can_parallelize_true(self):
        issues = _issues_dict(
            *[_issue("structural", file=f"file_{i}.py") for i in range(10)],
            *[_issue("props", file=f"comp_{i}.tsx") for i in range(10)],
        )
        by_det = {"structural": 10, "props": 10}
        actions = [
            {
                "priority": 1,
                "type": "refactor",
                "detector": "structural",
                "count": 10,
                "impact": 5.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "props",
                "count": 10,
                "impact": 3.0,
            },
        ]
        result = _compute_strategy(
            issues, by_det, actions, "middle_grind", "typescript"
        )
        assert result["can_parallelize"] is True

    def test_can_parallelize_ignores_insignificant_lanes(self):
        """One tiny lane shouldn't block parallelism of larger lanes."""
        issues = _issues_dict(
            *[_issue("structural", file=f"file_{i}.py") for i in range(10)],
            *[_issue("props", file=f"comp_{i}.tsx") for i in range(10)],
            _issue("deprecated", file="tiny.ts"),  # 1 file, tiny lane
        )
        by_det = {"structural": 10, "props": 10, "deprecated": 1}
        actions = [
            {
                "priority": 1,
                "type": "refactor",
                "detector": "structural",
                "count": 10,
                "impact": 5.0,
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "props",
                "count": 10,
                "impact": 3.0,
            },
            {
                "priority": 3,
                "type": "manual_fix",
                "detector": "deprecated",
                "count": 1,
                "impact": 0.2,
            },
        ]
        result = _compute_strategy(
            issues, by_det, actions, "middle_grind", "typescript"
        )
        # structural and props are significant, deprecated is not — still parallelizable
        assert result["can_parallelize"] is True

    def test_can_parallelize_false_single_lane(self):
        issues = _issues_dict(
            _issue("structural", file="a.py"),
        )
        by_det = {"structural": 1}
        actions = [
            {
                "priority": 1,
                "type": "refactor",
                "detector": "structural",
                "count": 1,
                "impact": 1.0,
            }
        ]
        result = _compute_strategy(
            issues, by_det, actions, "middle_grind", "typescript"
        )
        assert result["can_parallelize"] is False


# ===================================================================
# Review headline / reminder / strategy tests
# ===================================================================


class TestReviewHeadline:
    """Headline should mention review work items in all phases."""

    def test_review_suffix_in_middle_grind(self):
        """Review suffix should appear even during middle_grind (not just maintenance)."""
        by_det = {"unused": 5, "review": 3, "review_uninvestigated": 2}
        headline = compute_headline(
            "middle_grind",
            {"lowest_dimensions": []},
            {},
            None,
            None,
            85.0,
            85.0,
            {"open": 8},
            [],
            open_by_detector=by_det,
        )
        assert headline is not None
        assert "review work item" in headline.lower()

    def test_review_suffix_with_uninvestigated(self):
        """Uninvestigated review work items should mention show review."""
        by_det = {"review": 2, "review_uninvestigated": 2}
        headline = compute_headline(
            "maintenance",
            {},
            {},
            None,
            None,
            95.0,
            95.0,
            {},
            [],
            open_by_detector=by_det,
        )
        assert headline is not None
        assert "desloppify show review" in headline

    def test_review_suffix_all_investigated(self):
        """When all review work items are investigated, show 'pending' not 'issues'."""
        by_det = {"review": 2, "review_uninvestigated": 0}
        headline = compute_headline(
            "maintenance",
            {},
            {},
            None,
            None,
            95.0,
            95.0,
            {},
            [],
            open_by_detector=by_det,
        )
        assert headline is not None
        assert "pending" in headline
        assert "desloppify show review" not in headline

    def test_no_review_suffix_when_zero(self):
        by_det = {"unused": 3, "review": 0, "review_uninvestigated": 0}
        headline = compute_headline(
            "middle_grind",
            {"lowest_dimensions": []},
            {},
            None,
            None,
            85.0,
            85.0,
            {"open": 3},
            [],
            open_by_detector=by_det,
        )
        # Should not mention review at all
        if headline:
            assert "review work item" not in headline.lower()


class TestReviewUninvestigatedCount:
    """_count_open_by_detector should track review_uninvestigated."""

    def test_uninvestigated_count(self):
        issues = {
            "a": {"status": "open", "detector": "review", "detail": {}},
            "b": {
                "status": "open",
                "detector": "review",
                "detail": {"investigation": "looked at it"},
            },
            "c": {"status": "open", "detector": "review", "detail": {}},
            "d": {"status": "fixed", "detector": "review", "detail": {}},
        }
        result = _count_open_by_detector(issues)
        assert result["review"] == 3  # a, b, c
        assert result["review_uninvestigated"] == 2  # a, c

    def test_no_review_issues(self):
        issues = {
            "a": {"status": "open", "detector": "unused"},
        }
        result = _count_open_by_detector(issues)
        assert result.get("review_uninvestigated", 0) == 0


class TestReviewReminders:
    """Review-related reminders: pending issues + re-review needed."""

    def _base_state(self):
        work_items = {
            "r1": {"status": "open", "detector": "review", "detail": {}},
            "r2": {
                "status": "open",
                "detector": "review",
                "detail": {"investigation": "done"},
            },
        }
        return {
            "work_items": work_items,
            "issues": work_items,
            "reminder_history": {},
        }

    def test_review_issues_pending_reminder(self):
        state = self._base_state()
        reminders, _ = compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "scan"
        )
        types = [r["type"] for r in reminders]
        assert "review_issues_pending" in types
        msg = next(r for r in reminders if r["type"] == "review_issues_pending")
        assert "1 review work item" in msg["message"]
        assert "desloppify show review" in msg["message"]

    def test_no_review_pending_when_all_investigated(self):
        state = self._base_state()
        state["work_items"]["r1"]["detail"]["investigation"] = "done too"
        reminders, _ = compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "scan"
        )
        types = [r["type"] for r in reminders]
        assert "review_issues_pending" not in types

    def test_rereview_needed_after_resolve(self):
        state = self._base_state()
        state["subjective_assessments"] = {"naming_quality": {"score": 70}}
        reminders, _ = compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "resolve"
        )
        types = [r["type"] for r in reminders]
        assert "rereview_needed" in types
        msg = next(r for r in reminders if r["type"] == "rereview_needed")
        assert "review --prepare" in msg["message"]

    def test_no_rereview_when_not_resolve_command(self):
        state = self._base_state()
        state["subjective_assessments"] = {"naming_quality": {"score": 70}}
        reminders, _ = compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "scan"
        )
        types = [r["type"] for r in reminders]
        assert "rereview_needed" not in types

    def test_no_rereview_without_assessments(self):
        state = self._base_state()
        reminders, _ = compute_reminders(
            state, "typescript", "middle_grind", {}, [], {}, {}, "resolve"
        )
        types = [r["type"] for r in reminders]
        assert "rereview_needed" not in types


class TestStrategyReviewHint:
    """Strategy hint should mention review work items when issue_queue action exists."""

    def test_review_appended_to_hint(self):
        issues = _issues_dict(
            _issue("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 1,
                "impact": 1.0,
                "command": "desloppify autofix unused",
            },
            {
                "priority": 2,
                "type": "refactor",
                "detector": "review",
                "count": 3,
                "impact": 0,
                "command": "desloppify show review --status open",
            },
        ]
        result = _compute_strategy(
            issues, by_det, actions, "middle_grind", "typescript"
        )
        assert "desloppify show review" in result["hint"]
        assert "3 issue" in result["hint"]

    def test_no_review_in_hint_without_action(self):
        issues = _issues_dict(
            _issue("unused", file="a.py"),
        )
        by_det = {"unused": 1}
        actions = [
            {
                "priority": 1,
                "type": "auto_fix",
                "detector": "unused",
                "count": 1,
                "impact": 1.0,
                "command": "desloppify autofix unused",
            },
        ]
        result = _compute_strategy(
            issues, by_det, actions, "middle_grind", "typescript"
        )
        assert "desloppify show review" not in result["hint"]


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
                    "failing": 4,
                    "checks": 10,
                    "detectors": {"smells": {"failing": 4}},
                },
            },
            "stats": {"open": 4, "total": 6},
            "issues": {
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
            context=NarrativeContext(
                lang="typescript",
                command="scan",
                config={"review_max_age_days": 30},
            ),
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
        assert narrative["strict_target"]["target"] == 85.0
        assert narrative["strict_target"]["current"] == 78.0
        assert narrative["strict_target"]["gap"] == 7.0
        assert narrative["strict_target"]["state"] == "below"

    def test_strict_target_invalid_config_falls_back(self):
        state = {
            "strict_score": 91.0,
            "scan_history": [_history_entry(strict_score=91.0, lang="typescript")],
            "dimension_scores": {},
            "stats": {"open": 1, "total": 1},
            "issues": {},
            "reminder_history": {},
        }
        narrative = compute_narrative(
            state,
            context=NarrativeContext(
                lang="typescript",
                command="scan",
                config={"target_strict_score": "nope"},
            ),
        )
        strict_target = narrative["strict_target"]
        assert strict_target["target"] == 85.0
        assert strict_target["current"] == 91.0
        assert strict_target["gap"] == -6.0
        assert strict_target["state"] == "above"
        assert "Invalid config `target_strict_score='nope'`" in strict_target["warning"]
