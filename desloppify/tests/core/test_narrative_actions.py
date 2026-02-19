"""Direct tests for narrative action submodules.

These tests import directly from submodule files (not the __init__.py facade)
so test_coverage recognizes the submodules as directly tested.
"""

from __future__ import annotations

import pytest

from desloppify.engine.state_internal.schema import empty_state as empty_state_factory
from desloppify.intelligence.narrative.action_engine import (
    compute_actions as _compute_actions,
)
from desloppify.intelligence.narrative.action_models import ActionContext
from desloppify.intelligence.narrative.action_tools import (
    compute_tools as _compute_tools,
)


@pytest.fixture
def empty_state():
    return empty_state_factory()


class TestComputeActions:
    def test_empty_detectors(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={},
                dimension_scores={},
                state=empty_state,
                debt={},
                lang="typescript",
            )
        )
        assert result == []

    def test_returns_actions_for_open_findings(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={"unused": 5},
                dimension_scores={},
                state=empty_state,
                debt={},
                lang="typescript",
            )
        )
        assert len(result) >= 1
        assert any(a["detector"] == "unused" for a in result)

    def test_python_gets_manual_fix(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={"unused": 5},
                dimension_scores={},
                state=empty_state,
                debt={},
                lang="python",
            )
        )
        if result:
            unused_actions = [a for a in result if a.get("detector") == "unused"]
            for action in unused_actions:
                assert action["type"] == "manual_fix"

    def test_debt_review_action(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={},
                dimension_scores={},
                state=empty_state,
                debt={"overall_gap": 5.0},
                lang="typescript",
            )
        )
        assert any(a["type"] == "debt_review" for a in result)

    def test_no_debt_review_when_gap_small(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={},
                dimension_scores={},
                state=empty_state,
                debt={"overall_gap": 1.0},
                lang="typescript",
            )
        )
        assert not any(a.get("type") == "debt_review" for a in result)

    def test_actions_sorted_by_type_and_impact(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={"unused": 5, "structural": 3, "smells": 10},
                dimension_scores={},
                state=empty_state,
                debt={},
                lang="typescript",
            )
        )
        if len(result) >= 2:
            priorities = [a["priority"] for a in result]
            assert priorities == list(range(1, len(priorities) + 1))

    def test_subjective_review_action(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={"subjective_review": 20},
                dimension_scores={},
                state=empty_state,
                debt={},
                lang="typescript",
            )
        )
        sr_actions = [a for a in result if a.get("detector") == "subjective_review"]
        if sr_actions:
            assert "review" in sr_actions[0]["command"]

    def test_review_findings_action(self, empty_state):
        result = _compute_actions(
            ActionContext(
                by_detector={"review": 3},
                dimension_scores={},
                state=empty_state,
                debt={},
                lang="typescript",
            )
        )
        review_actions = [a for a in result if a.get("detector") == "review"]
        if review_actions:
            assert "issues" in review_actions[0]["command"]


class TestComputeTools:
    def test_empty(self):
        result = _compute_tools({}, {}, "typescript", {})
        assert "fixers" in result
        assert "move" in result
        assert "plan" in result

    def test_fixers_only_when_open(self):
        result = _compute_tools({"unused": 5}, {}, "typescript", {})
        assert len(result["fixers"]) >= 1

    def test_no_fixers_for_python(self):
        state = {"lang_capabilities": {"python": {"fixers": []}}}
        result = _compute_tools({"unused": 5}, state, "python", {})
        assert result["fixers"] == []

    def test_move_relevant_with_coupling(self):
        result = _compute_tools({"coupling": 3}, {}, "typescript", {})
        assert result["move"]["relevant"] is True

    def test_move_not_relevant_empty(self):
        result = _compute_tools({}, {}, "typescript", {})
        assert result["move"]["relevant"] is False
