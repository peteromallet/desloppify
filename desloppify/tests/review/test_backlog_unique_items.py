"""Backlog partitions expose each tracked issue once before ranking and paging."""

from __future__ import annotations

from copy import deepcopy

from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine._work_queue.snapshot import build_queue_snapshot
from desloppify.engine.planning.queue_policy import build_backlog_queue


def _issue(identifier: str, *, detector: str = "smells", status: str = "open") -> dict:
    return {
        "id": identifier,
        "detector": detector,
        "file": "src/example.py",
        "tier": 3,
        "confidence": "high",
        "summary": "Synthetic issue",
        "status": status,
        "detail": {},
    }


def _state_and_plan(*unplanned_ids: str) -> tuple[dict, dict]:
    planned_id = "smells::src/planned.py::example"
    issues = {
        identifier: _issue(identifier)
        for identifier in (planned_id, *unplanned_ids)
    }
    state = {"issues": issues, "work_items": issues, "dimension_scores": {}}
    plan = empty_plan()
    plan["queue_order"] = [planned_id]
    return state, plan


def test_unplanned_mechanical_issue_occurs_once_across_backlog_partitions() -> None:
    issue_id = "smells::src/unplanned.py::example"
    state, plan = _state_and_plan(issue_id)
    original_state = deepcopy(state)
    snapshot = build_queue_snapshot(state, plan=plan)
    queue = build_backlog_queue(
        state,
        options=QueueBuildOptions(count=None, include_subjective=False, plan=plan),
    )

    assert [item["id"] for item in snapshot.backlog_items if item["kind"] == "issue"] == [issue_id]
    assert [item["id"] for item in queue["items"]] == [issue_id]
    assert queue["total"] == snapshot.objective_backlog_count == 1
    assert state == original_state


def test_backlog_count_limit_is_applied_to_distinct_issue_ids() -> None:
    issue_ids = [f"smells::src/{letter}.py::example" for letter in "abcd"]
    state, plan = _state_and_plan(*issue_ids)
    queue = build_backlog_queue(
        state,
        options=QueueBuildOptions(count=2, include_subjective=False, plan=plan),
    )

    assert queue["total"] == 4
    assert [item["id"] for item in queue["items"]] == issue_ids[:2]
    assert [item["queue_position"] for item in queue["items"]] == [1, 2]


def test_backlog_scope_preserves_each_matching_issue_once() -> None:
    smell_id = "smells::src/unplanned.py::example"
    other_id = "structural::src/other.py::example"
    state, plan = _state_and_plan(smell_id)
    state["work_items"][other_id] = _issue(other_id, detector="structural")
    queue = build_backlog_queue(
        state,
        options=QueueBuildOptions(count=None, scope="smells", include_subjective=False, plan=plan),
    )

    assert [item["id"] for item in queue["items"]] == [smell_id]
    assert queue["total"] == 1


def test_skipped_and_resolved_issues_retain_visibility_policy() -> None:
    open_id = "smells::src/open.py::example"
    skipped_id = "smells::src/skipped.py::example"
    fixed_id = "smells::src/fixed.py::example"
    state, plan = _state_and_plan(open_id, skipped_id, fixed_id)
    state["work_items"][fixed_id]["status"] = "fixed"
    plan["skipped"][skipped_id] = {"kind": "temporary"}
    default = build_backlog_queue(
        state,
        options=QueueBuildOptions(count=None, include_subjective=False, plan=plan),
    )
    with_skipped = build_backlog_queue(
        state,
        options=QueueBuildOptions(count=None, include_subjective=False, include_skipped=True, plan=plan),
    )

    assert [item["id"] for item in default["items"]] == [open_id]
    assert [item["id"] for item in with_skipped["items"]] == [open_id, skipped_id]
    assert default["total"] == 1
    assert with_skipped["total"] == 2
