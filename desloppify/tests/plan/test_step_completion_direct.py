"""Direct coverage tests for plan step auto-completion helpers."""

from __future__ import annotations

from desloppify.engine._plan.step_completion import auto_complete_steps


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


def test_auto_complete_steps_ignores_unrelated_stale_refs() -> None:
    plan = {
        "queue_order": [],
        "clusters": {
            "target": {
                "action_steps": [
                    {"title": "Target step", "issue_refs": ["target-id"]},
                ]
            },
            "unrelated": {
                "action_steps": [
                    {"title": "Unrelated step", "issue_refs": ["stale-id"]},
                ]
            },
        },
    }

    messages = auto_complete_steps(plan, resolved_ids=["target-id"])

    assert plan["clusters"]["target"]["action_steps"][0]["done"] is True
    assert plan["clusters"]["unrelated"]["action_steps"][0].get("done") is not True
    assert messages == ["  Step 1 of 'target' auto-completed: Target step"]
