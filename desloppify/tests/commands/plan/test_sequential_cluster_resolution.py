"""Persisted cluster completion through ordinary sequential resolve commands."""

from __future__ import annotations

import argparse
from copy import deepcopy

import pytest

from desloppify import state as state_mod
from desloppify.app.commands.plan.override.resolve_cmd import cmd_plan_resolve
from desloppify.app.commands.resolve.living_plan import (
    capture_cluster_context,
    update_living_plan_after_resolve,
)
from desloppify.engine.plan_ops import (
    add_to_cluster,
    append_log_entry,
    create_cluster,
    move_items,
    purge_ids,
    skip_items,
)
from desloppify.engine.plan_state import empty_plan, load_plan, save_plan


def _seed_project(root, *, previous_status="open"):
    state_file = root / ".desloppify/state.json"
    plan_file = state_file.with_name("plan.json")
    state = state_mod.empty_state()
    state["scan_count"] = 3
    state["last_scan"] = "2026-03-01T00:00:00+00:00"
    issues = [
        state_mod.make_issue("smells", "src/module.py", name, tier=2, confidence="high", summary=name)
        for name in ("first", "second", "later")
    ]
    first, second, later = [issue["id"] for issue in issues]
    for issue in issues:
        state["work_items"][issue["id"]] = issue
    if previous_status is None:
        del state["work_items"][first]
    elif previous_status not in {"open", "temporary"}:
        state_mod.resolve_issues(state, first, previous_status, note="Previously resolved with evidence.")

    plan = empty_plan()
    for name, members in (("current-batch", [first, second]), ("later-batch", [later])):
        create_cluster(plan, name)
        add_to_cluster(plan, name, members)
        append_log_entry(plan, "cluster_create", cluster_name=name, issue_ids=members, actor="user")
    plan["clusters"]["current-batch"]["action_steps"] = [
        {"title": "Implement both changes", "done": True, "issue_refs": [first, second]}
    ]
    if previous_status == "temporary":
        skip_items(plan, [first], kind="temporary", note="Deferred until related work is ready.")
    elif previous_status != "open":
        purge_ids(plan, [first])
    state_mod.save_state(state, state_file)
    save_plan(plan, plan_file)
    return state_file, plan_file, (first, second, later)


def _resolve(state_file, issue_id: str) -> None:
    cmd_plan_resolve(argparse.Namespace(
        patterns=[issue_id],
        note="Implemented the change and verified the resulting behavior with regression tests.",
        confirm=True,
        state=str(state_file),
        lang=None,
        path=str(state_file.parent.parent),
    ))


def test_sequential_plan_resolve_completes_only_its_cluster(set_project_root, monkeypatch) -> None:
    monkeypatch.chdir(set_project_root)
    state_file, plan_file, (first, second, later) = _seed_project(set_project_root)
    unrelated_before = deepcopy(load_plan(plan_file)["clusters"]["later-batch"])

    _resolve(state_file, first)
    midway = load_plan(plan_file)
    assert state_mod.load_state(state_file)["work_items"][first]["status"] == "fixed"
    assert midway["clusters"]["current-batch"]["execution_status"] == "active"
    assert midway["active_cluster"] == "current-batch"
    assert midway["clusters"]["current-batch"]["issue_ids"] == [second, first]

    _resolve(state_file, second)
    persisted_state = state_mod.load_state(state_file)
    completed = load_plan(plan_file)
    assert all(persisted_state["work_items"][issue_id]["status"] == "fixed" for issue_id in (first, second))
    assert completed["clusters"]["current-batch"]["execution_status"] == "done"
    assert completed["active_cluster"] is None
    assert set(completed["clusters"]["current-batch"]["issue_ids"]) == {first, second}
    assert completed["clusters"]["current-batch"]["action_steps"][0]["done"] is True
    assert completed["clusters"]["later-batch"] == unrelated_before
    assert completed["queue_order"] == [later]
    assert persisted_state["work_items"][later]["status"] == "open"
    assert [entry["cluster_name"] for entry in completed["execution_log"] if entry["action"] == "cluster_done"] == ["current-batch"]


@pytest.mark.parametrize(("previous_status", "complete"), [
    ("fixed", True), ("auto_resolved", True), ("wontfix", True), ("false_positive", True),
    ("open", False), (None, False), ("temporary", False),
])
def test_plan_resolve_counts_persisted_member_statuses(
    set_project_root, monkeypatch, previous_status, complete
) -> None:
    monkeypatch.chdir(set_project_root)
    state_file, plan_file, (first, second, later) = _seed_project(set_project_root, previous_status=previous_status)
    plan = load_plan(plan_file)
    move_items(plan, [second], "top")
    save_plan(plan, plan_file)
    unrelated_before = deepcopy(plan["clusters"]["later-batch"])
    skipped_before = deepcopy(plan["skipped"])

    _resolve(state_file, second)

    persisted_state = state_mod.load_state(state_file)
    completed = load_plan(plan_file)
    assert persisted_state["work_items"][second]["status"] == "fixed"
    assert completed["clusters"]["current-batch"]["execution_status"] == ("done" if complete else "active")
    assert completed["active_cluster"] == (None if complete else "current-batch")
    assert set(completed["clusters"]["current-batch"]["issue_ids"]) == {first, second}
    assert completed["clusters"]["later-batch"] == unrelated_before
    assert completed["skipped"] == skipped_before
    assert persisted_state["work_items"][later]["status"] == "open"


def test_resolution_metadata_recovers_historical_membership_after_overrides_clear(
    set_project_root, monkeypatch
) -> None:
    monkeypatch.chdir(set_project_root)
    state_file, plan_file, (first, second, later) = _seed_project(set_project_root, previous_status="fixed")
    state = state_mod.load_state(state_file)
    state_mod.resolve_issues(state, second, "fixed", note="Resolved before metadata update was interrupted.")
    state_mod.save_state(state, state_file)
    plan = load_plan(plan_file)
    purge_ids(plan, [second])
    plan["active_cluster"] = "current-batch"
    save_plan(plan, plan_file)
    before = load_plan(plan_file)
    state_bytes = state_file.read_bytes()

    context = capture_cluster_context(before, [second], state=state)
    assert context.cluster_name == "current-batch"
    assert context.cluster_completed is True
    assert context.cluster_remaining == 0

    _, context = update_living_plan_after_resolve(
        args=argparse.Namespace(status="fixed", note="Finish the interrupted metadata update."),
        all_resolved=[second],
        attestation="I have actually resolved this and I am not gaming the score.",
        state=state,
        state_file=state_file,
    )

    after = load_plan(plan_file)
    assert context.cluster_completed is True
    assert after["clusters"]["current-batch"]["execution_status"] == "done"
    assert after["active_cluster"] is None
    assert set(after["clusters"]["current-batch"]["issue_ids"]) == {first, second}
    assert after["clusters"]["later-batch"] == before["clusters"]["later-batch"]
    assert after["queue_order"] == [later]
    assert state_file.read_bytes() == state_bytes


def test_explicit_membership_takes_precedence_over_other_cluster_history(set_project_root, monkeypatch) -> None:
    monkeypatch.chdir(set_project_root)
    state_file, plan_file, (_, second, _) = _seed_project(set_project_root, previous_status="fixed")
    plan = load_plan(plan_file)
    create_cluster(plan, "historical-batch")
    add_to_cluster(plan, "historical-batch", [second])
    append_log_entry(plan, "cluster_create", cluster_name="historical-batch", issue_ids=[second], actor="user")
    add_to_cluster(plan, "current-batch", [second])
    save_plan(plan, plan_file)
    unrelated_history = deepcopy(load_plan(plan_file)["clusters"]["historical-batch"])

    _resolve(state_file, second)

    after = load_plan(plan_file)
    assert after["clusters"]["current-batch"]["execution_status"] == "done"
    assert after["clusters"]["historical-batch"] == unrelated_history
