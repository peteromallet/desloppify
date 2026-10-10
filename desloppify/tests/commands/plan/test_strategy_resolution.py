"""Stored strategy findings resolve through the ordinary public command."""

from __future__ import annotations

import argparse
from copy import deepcopy

from desloppify import state as state_mod
from desloppify.app.commands.plan.override.resolve_cmd import cmd_plan_resolve
from desloppify.app.commands.plan.triage.stages.strategize import (
    _create_strategic_work_items,
)
from desloppify.engine.plan_state import empty_plan, load_plan, save_plan


def test_plan_resolve_persists_a_strategy_finding_without_changing_other_work(
    set_project_root, monkeypatch
) -> None:
    monkeypatch.chdir(set_project_root)
    state_file = set_project_root / ".desloppify/state.json"
    plan_file = state_file.with_name("plan.json")
    state = state_mod.empty_state()
    state["scan_count"] = 3
    state["last_scan"] = "2026-03-01T00:00:00+00:00"
    other = state_mod.make_issue(
        "smells", "src/module.py", "retained", tier=2,
        confidence="high", summary="Separate pending work.",
    )
    state["work_items"][other["id"]] = other
    plan = empty_plan()
    plan["queue_order"] = [other["id"]]
    _create_strategic_work_items(state, plan, [{
        "identifier": "consolidate-boundary-refactors",
        "priority": "medium",
        "summary": "Group related changes around their workflow owner.",
        "recommendation": "Deliver a bounded batch with meaningful verification.",
        "dimensions_affected": ["Contracts"],
    }])
    issue_id = "strategy::consolidate-boundary-refactors"
    state_mod.save_state(state, state_file)
    save_plan(plan, plan_file)
    other_before = deepcopy(state_mod.load_state(state_file)["work_items"][other["id"]])

    cmd_plan_resolve(argparse.Namespace(
        patterns=[issue_id],
        note="Delivered the workflow-owned batch with verified native behavior.",
        confirm=True,
        state=str(state_file),
        lang=None,
        path=str(set_project_root),
    ))

    persisted = state_mod.load_state(state_file)
    assert persisted["work_items"][issue_id]["status"] == "fixed"
    assert persisted["work_items"][issue_id]["resolved_at"] is not None
    assert persisted["work_items"][other["id"]] == other_before
    assert persisted["scan_count"] == 3
    assert persisted["last_scan"] == "2026-03-01T00:00:00+00:00"
    assert load_plan(plan_file)["queue_order"] == [other["id"]]
