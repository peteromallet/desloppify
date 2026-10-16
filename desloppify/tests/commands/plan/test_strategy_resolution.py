"""Persisted strategist items must resolve through the canonical state path."""

from __future__ import annotations

import argparse

import pytest

from desloppify.app.commands.plan.override.resolve_cmd import cmd_plan_resolve
from desloppify.app.commands.plan.override.resolve_helpers import (
    split_synthetic_patterns,
)
from desloppify.app.commands.plan.triage.stages.strategize import (
    _create_strategic_work_items,
)
from desloppify.engine._plan.constants import is_synthetic_id
from desloppify.engine.plan_state import empty_plan, load_plan, save_plan
from desloppify.state_io import empty_state, load_state, save_state

NOTE = "Verified the synthetic strategy requirement against its completed work."
ATTEST = "I have actually verified this work and I am not gaming the score."


@pytest.fixture
def strategy_project(set_project_root, monkeypatch):
    """Only newly created synthetic data is written under pytest's temp root."""
    monkeypatch.chdir(set_project_root)
    state = empty_state()
    state["scan_count"] = 1
    state["last_scan"] = "2026-01-01T00:00:00+00:00"
    plan = empty_plan()
    _create_strategic_work_items(
        state,
        plan,
        [
            {
                "identifier": identifier,
                "priority": "high",
                "summary": f"Synthetic strategy {identifier}",
                "recommendation": "Verify this synthetic requirement.",
                "dimensions_affected": ["Test health"],
            }
            for identifier in ("first", "second")
        ],
    )
    state_file = set_project_root / ".desloppify" / "state-python.json"
    save_state(state, state_file)
    save_plan(plan)
    return state_file


def _args(state_file, patterns, **overrides):
    values = {
        "patterns": patterns,
        "attest": ATTEST,
        "note": NOTE,
        "confirm": False,
        # Exercise the real state/plan persistence path independently of queue
        # position and triage gates, which have their own integration tests.
        "force_resolve": True,
        "state": str(state_file),
        "lang": "python",
        "path": ".",
        "exclude": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.mark.parametrize("pattern", ["strategy::first", "strategy::*"])
def test_created_strategies_persist_resolution(strategy_project, pattern):
    cmd_plan_resolve(_args(strategy_project, [pattern]))

    state = load_state(strategy_project)
    resolved = ["strategy::first"]
    if pattern == "strategy::*":
        resolved.append("strategy::second")
    for issue_id in resolved:
        issue = state["work_items"][issue_id]
        assert issue["status"] == "fixed"
        assert issue["resolved_at"]
        assert issue["note"] == NOTE
        assert issue["resolution_attestation"]["text"] == ATTEST
    if pattern == "strategy::first":
        assert state["work_items"]["strategy::second"]["status"] == "open"
        assert "strategy::second" in load_plan()["queue_order"]
    assert not set(resolved) & set(load_plan()["queue_order"])


@pytest.mark.parametrize("overrides", [{"note": "short"}, {"attest": None}])
def test_strategy_resolution_requires_normal_evidence(strategy_project, overrides):
    before = strategy_project.read_bytes()
    queue_before = list(load_plan()["queue_order"])

    cmd_plan_resolve(_args(strategy_project, ["strategy::first"], **overrides))

    assert strategy_project.read_bytes() == before
    assert load_plan()["queue_order"] == queue_before


def test_missing_strategy_is_not_reported_as_resolved(strategy_project, capsys):
    before = strategy_project.read_bytes()
    cmd_plan_resolve(_args(strategy_project, ["strategy::missing"]))

    assert strategy_project.read_bytes() == before
    output = capsys.readouterr().out
    assert "No open issues" in output
    assert "Resolved:" not in output


def test_mixed_workflow_and_strategy_resolution_preserves_both_paths(strategy_project):
    plan = load_plan()
    workflow_id = "workflow::communicate-score"
    plan["queue_order"].insert(0, workflow_id)
    save_plan(plan)

    cmd_plan_resolve(_args(strategy_project, [workflow_id, "strategy::first"]))

    assert (
        load_state(strategy_project)["work_items"]["strategy::first"]["status"]
        == "fixed"
    )
    assert workflow_id not in load_plan()["queue_order"]
    assert "strategy::first" not in load_plan()["queue_order"]
    assert "strategy::second" in load_plan()["queue_order"]


def test_only_resolution_routing_distinguishes_persisted_strategies():
    # Strategy remains synthetic for queue ordering and other plan consumers.
    assert is_synthetic_id("strategy::first")
    assert split_synthetic_patterns(
        [
            "workflow::communicate-score",
            "triage::observe",
            "subjective::naming",
            "strategy::first",
            "strategy::*",
        ]
    ) == (
        ["workflow::communicate-score", "triage::observe", "subjective::naming"],
        ["strategy::first", "strategy::*"],
    )
