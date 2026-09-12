"""Queue views must preserve configured targets and distinct work items."""

import argparse
from types import SimpleNamespace

import pytest

from desloppify.app.commands.plan import queue_render
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)


def _issue(issue_id, detector="smells"):
    return {
        "id": issue_id,
        "detector": detector,
        "file": "src/a.py",
        "tier": 3,
        "confidence": "medium",
        "summary": issue_id,
        "status": "open",
        "detail": {},
    }


def test_backlog_contains_each_mechanical_and_review_finding_once():
    planned = _issue("smells::planned")
    mechanical = _issue("smells::unplanned")
    review = _issue("review::unplanned", "review")
    concern = _issue("concerns::unplanned", "concerns")
    state = {
        "issues": {item["id"]: item for item in (planned, mechanical, review, concern)}
    }
    plan = empty_plan()
    plan["queue_order"] = [planned["id"]]

    queue = build_backlog_queue(state, options=QueueBuildOptions(plan=plan, count=None))

    ids = [item["id"] for item in queue["items"]]
    assert sorted(ids) == sorted([mechanical["id"], review["id"], concern["id"]])
    assert queue["total"] == 3


@pytest.mark.parametrize("target, expected", [(85, False), (95, True)])
def test_plan_queue_matches_execution_target(monkeypatch, capsys, target, expected):
    state = {
        "issues": {},
        "scan_count": 1,
        "last_scan": "2026-01-01T00:00:00Z",
        "dimension_scores": {
            "Naming quality": {
                "score": 90.0,
                "strict": 90.0,
                "checks": 1,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"}
                },
            },
        },
        "subjective_assessments": {"naming_quality": {"score": 90.0}},
    }
    plan = empty_plan()
    plan["refresh_state"]["postflight_scan_completed_at_scan_count"] = 1
    config = {"target_strict_score": target}
    monkeypatch.setattr(
        queue_render,
        "command_runtime",
        lambda _args: SimpleNamespace(state=state, config=config),
    )
    monkeypatch.setattr(queue_render, "load_plan", lambda: plan)

    next_queue = build_execution_queue(
        state,
        options=QueueBuildOptions(plan=plan, subjective_threshold=target, count=None),
    )
    assert (
        any(item["id"] == "subjective::naming_quality" for item in next_queue["items"])
        is expected
    )

    queue_render.cmd_plan_queue(
        argparse.Namespace(top=0, cluster=None, include_skipped=False, sort="priority")
    )
    assert ("Naming quality" in capsys.readouterr().out) is expected
