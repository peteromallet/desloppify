"""Persisted strategy work must use the attested state resolution lifecycle."""

from __future__ import annotations

import argparse
import copy

import pytest

from desloppify.app.commands.plan.override.resolve_cmd import cmd_plan_resolve
from desloppify.app.commands.plan.override.resolve_helpers import (
    split_synthetic_patterns,
)
from desloppify.app.commands.plan.triage.stages.strategize import (
    _create_strategic_work_items,
)
from desloppify.engine._work_queue.core import QueueBuildOptions, build_work_queue
from desloppify.engine.plan_state import empty_plan, load_plan, save_plan
from desloppify.state_io import empty_state, load_state, save_state

STRATEGY = "strategy::focus"
WORKFLOW = "workflow::communicate-score"
SENTINEL = "smells::src/example.py::long_function"
NOTE = "Reviewed the synthetic request boundary and implemented the documented completion action."
ATTEST = f"I have actually {NOTE} and I am not gaming the score."


def arguments(state_file, patterns, **changes):
    return argparse.Namespace(
        **{
            "patterns": patterns,
            "state": str(state_file),
            "lang": None,
            "path": ".",
            "exclude": None,
            "note": NOTE,
            "attest": ATTEST,
            "confirm": False,
            "force_resolve": False,
            **changes,
        }
    )


@pytest.fixture
def persisted_strategy(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    state_file = tmp_path / ".desloppify" / "state.json"
    state = empty_state()
    state["scan_count"] = 1
    state["last_scan"] = "2026-01-01T00:00:00+00:00"
    state["scan_metadata"] = {"source": "scan"}
    state["work_items"][SENTINEL] = {
        "id": SENTINEL,
        "detector": "smells",
        "file": "src/example.py",
        "status": "open",
        "tier": 3,
        "confidence": "high",
        "summary": "Another synthetic action remains queued",
    }
    plan = empty_plan()
    plan["queue_order"] = [SENTINEL]
    _create_strategic_work_items(
        state,
        plan,
        [
            {
                "identifier": "focus",
                "priority": "high",
                "summary": "Complete the synthetic request-boundary action",
                "recommendation": "Verify the action through its observable contract",
                "dimensions_affected": ["logic_clarity"],
            }
        ],
    )
    save_state(state, state_file)
    save_plan(plan)
    return state_file


@pytest.mark.parametrize("storage", ["work_items", "issues"])
@pytest.mark.parametrize("pattern", [STRATEGY, "strategy::*", "strategy::fo"])
@pytest.mark.parametrize("status", ["open", "fixed", "suppressed"])
def test_persisted_strategy_patterns_are_not_virtual_even_when_not_open(
    storage, pattern, status
):
    state = {
        storage: {STRATEGY: {"status": status, "suppressed": status == "suppressed"}}
    }
    before = copy.deepcopy(state)

    assert split_synthetic_patterns([WORKFLOW, pattern, SENTINEL], state=state) == (
        [WORKFLOW],
        [pattern, SENTINEL],
    )
    assert state == before


def test_virtual_strategy_and_workflow_patterns_keep_existing_resolution_path():
    assert split_synthetic_patterns([WORKFLOW, STRATEGY, SENTINEL], state={}) == (
        [WORKFLOW, STRATEGY],
        [SENTINEL],
    )
    assert split_synthetic_patterns([WORKFLOW, STRATEGY]) == ([WORKFLOW, STRATEGY], [])


@pytest.mark.parametrize("pattern", [STRATEGY, "strategy::*"])
@pytest.mark.parametrize("confirm", [False, True])
def test_strategy_completion_survives_reload_and_no_longer_appears_in_queue(
    persisted_strategy, pattern, confirm
):
    cmd_plan_resolve(
        arguments(
            persisted_strategy,
            [pattern],
            confirm=confirm,
            attest=None if confirm else ATTEST,
        )
    )

    state = load_state(persisted_strategy)
    issue = state["work_items"][STRATEGY]
    assert issue["status"] == "fixed"
    assert issue["note"] == NOTE
    assert issue["resolved_at"]
    assert issue["resolution_attestation"]["kind"] == "manual"
    assert issue["resolution_attestation"]["text"] == ATTEST
    plan = load_plan()
    assert STRATEGY not in plan["queue_order"]
    queue = build_work_queue(
        state, options=QueueBuildOptions(scope=STRATEGY, plan=plan, count=None)
    )
    assert STRATEGY not in {item["id"] for item in queue["items"]}


def test_virtual_strategy_resolution_does_not_create_state_record(persisted_strategy):
    plan = load_plan()
    virtual = "strategy::virtual"
    plan["queue_order"].insert(0, virtual)
    save_plan(plan)
    before = persisted_strategy.read_bytes()

    cmd_plan_resolve(arguments(persisted_strategy, [virtual], note=None, attest=None))

    assert virtual not in load_plan()["queue_order"]
    assert persisted_strategy.read_bytes() == before
    assert virtual not in load_state(persisted_strategy)["work_items"]


@pytest.mark.parametrize(
    "invalid", [{"note": None}, {"note": "short"}, {"attest": None}]
)
def test_invalid_state_completion_cannot_partially_resolve_mixed_virtual_work(
    persisted_strategy, invalid
):
    plan = load_plan()
    plan["queue_order"].insert(0, WORKFLOW)
    save_plan(plan)
    before_state = persisted_strategy.read_bytes()
    before_order = list(plan["queue_order"])

    cmd_plan_resolve(arguments(persisted_strategy, [WORKFLOW, STRATEGY], **invalid))

    assert persisted_strategy.read_bytes() == before_state
    assert load_plan()["queue_order"] == before_order


def test_mixed_virtual_and_persisted_completion_updates_both_owners(persisted_strategy):
    plan = load_plan()
    plan["queue_order"].insert(0, WORKFLOW)
    save_plan(plan)

    cmd_plan_resolve(arguments(persisted_strategy, [WORKFLOW, STRATEGY]))

    assert load_state(persisted_strategy)["work_items"][STRATEGY]["status"] == "fixed"
    order = load_plan()["queue_order"]
    assert WORKFLOW not in order
    assert STRATEGY not in order
    assert SENTINEL in order


def test_virtual_strategy_without_scan_state_keeps_plan_only_lifecycle(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    state_file = tmp_path / ".desloppify" / "state.json"
    plan = empty_plan()
    plan["queue_order"] = [STRATEGY]
    save_plan(plan)

    cmd_plan_resolve(arguments(state_file, [STRATEGY], note=None, attest=None))

    assert STRATEGY not in load_plan()["queue_order"]
    assert not state_file.exists()
