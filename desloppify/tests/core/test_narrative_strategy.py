"""Direct tests for narrative strategy/dimensions/phase submodules."""

from __future__ import annotations

import pytest

from desloppify.engine.state_internal.schema import empty_state as empty_state_factory
from desloppify.intelligence.narrative.dimensions import (
    _analyze_debt,
    _analyze_dimensions,
)
from desloppify.intelligence.narrative.phase import _detect_milestone, _detect_phase
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


@pytest.fixture
def empty_state():
    return empty_state_factory()


class TestOpenFilesByDetector:
    def test_empty(self):
        assert _open_files_by_detector({}) == {}

    def test_groups_by_detector(self):
        findings = {
            "f1": {"status": "open", "detector": "unused", "file": "a.ts"},
            "f2": {"status": "open", "detector": "unused", "file": "b.ts"},
            "f3": {"status": "open", "detector": "smells", "file": "a.ts"},
            "f4": {"status": "resolved", "detector": "unused", "file": "c.ts"},
        }
        result = _open_files_by_detector(findings)
        assert len(result["unused"]) == 2
        assert len(result["smells"]) == 1
        assert "resolved" not in str(result)

    def test_merges_structural(self):
        findings = {
            "f1": {"status": "open", "detector": "gods", "file": "big.ts"},
            "f2": {"status": "open", "detector": "large", "file": "huge.ts"},
        }
        result = _open_files_by_detector(findings)
        assert "structural" in result
        assert len(result["structural"]) == 2


class TestComputeFixerLeverage:
    def test_no_fixers_python(self):
        result = _compute_fixer_leverage({"unused": 5}, [], "early_momentum", "python")
        assert result["recommendation"] == "none"

    def test_strong_leverage(self):
        actions = [{"type": "auto_fix", "count": 50, "impact": 10}]
        result = _compute_fixer_leverage(
            {"unused": 50}, actions, "early_momentum", "typescript"
        )
        assert result["auto_fixable_count"] == 50


class TestComputeStrategy:
    def test_empty(self):
        result = _compute_strategy({}, {}, [], "first_scan", "typescript")
        assert "hint" in result
        assert "lanes" in result

    def test_with_findings(self):
        findings = {"f1": {"status": "open", "detector": "unused", "file": "a.ts"}}
        result = _compute_strategy(
            findings, {"unused": 5}, [], "early_momentum", "typescript"
        )
        assert "hint" in result
        assert "fixer_leverage" in result


class TestComputeStrategyHint:
    def test_empty(self):
        result = _compute_strategy_hint({}, {}, [], "first_scan")
        assert isinstance(result, str)


class TestComputeLanes:
    def test_empty_actions(self):
        result = _compute_lanes([], {})
        assert result == {}

    def test_identifies_lanes(self):
        actions = [
            {"type": "auto_fix", "detector": "unused", "count": 5, "priority": 1},
            {"type": "reorganize", "detector": "structural", "count": 3, "priority": 2},
        ]
        files_by_det = {
            "unused": {"a.ts", "b.ts"},
            "structural": {"c.ts"},
        }
        result = _compute_lanes(actions, files_by_det)
        assert isinstance(result, dict)


class TestAnalyzeDimensions:
    def test_empty(self, empty_state):
        result = _analyze_dimensions({}, [], empty_state)
        assert result == {}

    def test_basic_analysis(self, empty_state):
        dim_scores = {
            "Import hygiene": {
                "score": 100,
                "strict": 100,
                "tier": 1,
                "issues": 0,
                "detectors": {},
            },
            "Code quality": {
                "score": 80,
                "strict": 75,
                "tier": 3,
                "issues": 20,
                "detectors": {"smells": {"issues": 20}},
            },
        }
        result = _analyze_dimensions(dim_scores, [], empty_state)
        assert isinstance(result, dict)


class TestAnalyzeDebt:
    def test_empty(self):
        result = _analyze_debt({}, {}, [])
        assert "overall_gap" in result

    def test_with_wontfix(self):
        findings = {
            "f1": {
                "status": "wontfix",
                "confidence": "high",
                "detector": "smells",
                "tier": 2,
                "note": "intentional",
            },
        }
        result = _analyze_debt({}, findings, [])
        assert isinstance(result["overall_gap"], int | float)


class TestDetectPhase:
    def test_first_scan_empty(self):
        assert _detect_phase([], None) == "first_scan"

    def test_first_scan_single(self):
        assert _detect_phase([{"strict_score": 80}], 80) == "first_scan"

    def test_early_momentum(self):
        history = [
            {"strict_score": 70},
            {"strict_score": 75},
            {"strict_score": 80},
        ]
        result = _detect_phase(history, 80)
        assert result in (
            "early_momentum",
            "steady_progress",
            "high_plateau",
            "regression",
        )


class TestDetectMilestone:
    def test_no_history(self, empty_state):
        result = _detect_milestone(empty_state, None, [])
        assert result is None

    def test_with_history(self, empty_state):
        empty_state["strict_score"] = 85.0
        history = [
            {"strict_score": 70},
            {"strict_score": 80},
        ]
        result = _detect_milestone(empty_state, None, history)
        assert result is None or isinstance(result, str)
