"""Direct coverage tests for plan step auto-completion helpers."""

from __future__ import annotations

import pytest

from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.step_completion import auto_complete_steps
from desloppify.engine.plan_ops import purge_ids, skip_items


def test_auto_complete_steps_marks_done_when_all_refs_leave_queue() -> None:
    plan = {
        "queue_order": ["review::id::abc123", "review::open::keep999"],
        "clusters": {
            "epic/cleanup": {
                "action_steps": [
                    {"title": "Fix abc", "issue_refs": ["abc123"]},
                    {"title": "Fix stale refs", "issue_refs": ["gone1", "gone2"]},
                ]
            }
        },
    }

    messages = auto_complete_steps(plan)

    steps = plan["clusters"]["epic/cleanup"]["action_steps"]
    assert steps[0].get("done") is not True
    assert steps[1]["done"] is True
    assert messages == ["  Step 2 of 'epic/cleanup' auto-completed: Fix stale refs"]


def test_auto_complete_steps_matches_exact_issue_ids() -> None:
    plan = {
        "queue_order": ["review::still-open"],
        "clusters": {
            "epic/exact": {
                "action_steps": [
                    {"title": "Exact open", "issue_refs": ["review::still-open"]},
                    {"title": "Exact gone", "issue_refs": ["review::gone"]},
                ]
            }
        },
    }

    messages = auto_complete_steps(plan)

    steps = plan["clusters"]["epic/exact"]["action_steps"]
    assert steps[0].get("done") is not True
    assert steps[1]["done"] is True
    assert "Step 2" in messages[0]


def test_auto_complete_steps_ignores_done_steps_and_invalid_step_shapes() -> None:
    plan = {
        "queue_order": [],
        "clusters": {
            "epic/mixed": {
                "action_steps": [
                    {"title": "Already done", "issue_refs": ["gone"], "done": True},
                    {"title": "No refs"},
                    "not-a-dict",
                ]
            }
        },
    }

    messages = auto_complete_steps(plan)

    assert messages == []
    assert plan["clusters"]["epic/mixed"]["action_steps"][0]["done"] is True


@pytest.mark.parametrize("ref", ["pending123", "review::later.py::pending123"])
def test_resolving_other_work_keeps_temporarily_deferred_step_pending(ref: str) -> None:
    current_id = "review::current.py::current123"
    pending_id = "review::later.py::pending123"
    plan = empty_plan()
    plan["queue_order"] = [current_id, pending_id]
    plan["clusters"] = {
        "current": {
            "issue_ids": [current_id],
            "action_steps": [{"title": "Current work", "issue_refs": [current_id]}],
        },
        "later": {
            "issue_ids": [pending_id],
            "action_steps": [{"title": "Deferred work", "issue_refs": [ref]}],
        },
    }

    skip_items(plan, [pending_id], kind="temporary")
    purge_ids(plan, [current_id])
    messages = auto_complete_steps(plan)

    assert plan["clusters"]["current"]["action_steps"][0]["done"] is True
    assert plan["clusters"]["later"]["action_steps"][0].get("done") is not True
    assert plan["skipped"][pending_id]["kind"] == "temporary"
    assert messages == ["  Step 1 of 'current' auto-completed: Current work"]
