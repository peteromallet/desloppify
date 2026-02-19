"""Direct coverage tests for narrative engine split modules."""

from __future__ import annotations

from desloppify.intelligence.narrative.action_engine import (
    compute_actions,
    supported_fixers,
)
from desloppify.intelligence.narrative.action_models import ActionContext
from desloppify.intelligence.narrative.action_tools import compute_tools
from desloppify.intelligence.narrative.strategy_engine import compute_strategy


def test_action_engine_supported_fixers_reads_capabilities():
    state = {"lang_capabilities": {"python": {"fixers": ["unused-imports", "logs"]}}}
    assert supported_fixers(state, "python") == {"unused-imports", "logs"}


def test_action_engine_compute_actions_returns_ranked_items():
    ctx = ActionContext(
        by_detector={"unused": 2},
        dimension_scores={},
        state={"lang_capabilities": {"python": {"fixers": ["unused-imports"]}}},
        debt={"overall_gap": 0.0},
        lang="python",
    )
    actions = compute_actions(ctx)
    assert actions
    assert actions[0]["priority"] == 1
    assert actions[0]["detector"] == "unused"


def test_action_tools_compute_tools_emits_fixer_inventory():
    tools = compute_tools(
        by_detector={"unused": 3},
        state={"lang_capabilities": {"python": {"fixers": ["unused-imports"]}}},
        lang="python",
        badge={},
    )
    assert tools["fixers"]
    assert tools["fixers"][0]["name"] == "unused-imports"


def test_strategy_engine_compute_strategy_populates_hint_and_lanes():
    findings = {
        "unused::a": {
            "status": "open",
            "detector": "unused",
            "file": "src/a.py",
            "confidence": "high",
            "tier": 1,
            "detail": {},
        }
    }
    actions = [
        {
            "priority": 1,
            "type": "auto_fix",
            "detector": "unused",
            "count": 1,
            "impact": 1.2,
            "description": "",
            "command": "",
        }
    ]
    strategy = compute_strategy(
        findings, {"unused": 1}, actions, "first_scan", "python"
    )
    assert "hint" in strategy
    assert "lanes" in strategy
    assert actions[0]["lane"] is not None
