"""Regression tests for configured targets across queue command surfaces."""

from __future__ import annotations

import argparse
from copy import deepcopy
from types import SimpleNamespace

import pytest

import desloppify.app.commands.next.queue_flow as next_queue
import desloppify.app.commands.plan.queue_render as plan_queue
from desloppify.app.commands.helpers.command_runtime import CommandRuntime
from desloppify.app.commands.helpers.queue_progress import plan_aware_queue_breakdown
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)


@pytest.fixture
def postflight_queue():
    issue_id = "test_coverage::src/service.py::untested_module"
    state = {
        "work_items": {
            issue_id: {
                "id": issue_id,
                "detector": "test_coverage",
                "file": "src/service.py",
                "tier": 3,
                "confidence": "high",
                "summary": "Reopened mechanical finding",
                "status": "open",
                "detail": {},
            }
        },
        "dimension_scores": {
            "AI generated debt": {
                "score": 94.0,
                "strict": 94.0,
                "failing": 0,
                "stale": True,
            }
        },
        "scan_path": ".",
        "scan_count": 3,
        "last_scan": "2026-10-10T00:00:00+00:00",
    }
    plan = empty_plan()
    plan["queue_order"] = ["subjective::ai_generated_debt", issue_id]
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["refresh_state"].update(
        lifecycle_phase="plan",
        postflight_scan_completed_at_scan_count=3,
    )
    return state, plan, issue_id


def test_next_plan_queue_and_footer_share_configured_target(
    postflight_queue,
    monkeypatch,
    capsys,
) -> None:
    state, plan, issue_id = postflight_queue
    original = deepcopy((state, plan))
    config = {"target_strict_score": 85.0}
    captured = []

    next_queue.build_and_render_execution_queue(
        argparse.Namespace(
            count=1,
            scope=None,
            status="open",
            group="item",
            explain=False,
            cluster=None,
            include_skipped=False,
            output=None,
            format="terminal",
        ),
        state=state,
        config=config,
        deps=next_queue.QueueRenderDeps(
            resolve_lang_fn=lambda _args: SimpleNamespace(name="python"),
            load_plan_fn=lambda: plan,
            write_query_fn=lambda payload: captured.append(payload),
        ),
    )
    capsys.readouterr()
    assert [item["id"] for item in captured[0]["items"]] == [issue_id]

    monkeypatch.setattr(
        plan_queue,
        "command_runtime",
        lambda _args: CommandRuntime(config=config, state=state, state_path=None),
    )
    monkeypatch.setattr(plan_queue, "load_plan", lambda: plan)
    monkeypatch.setattr(plan_queue, "print_triage_guardrail_info", lambda **_kw: None)
    plan_queue.cmd_plan_queue(argparse.Namespace(top=30))
    rendered = capsys.readouterr().out
    assert "Reopened mechanical finding" in rendered
    assert "subjective_assessment" not in rendered

    context = queue_context(state, config=config, plan=plan)
    breakdown = plan_aware_queue_breakdown(state, context=context)
    assert breakdown.queue_total == 1
    assert breakdown.subjective == 0
    assert breakdown.plan_ordered == 1
    assert breakdown.stale_plan_ordered == 1
    assert (state, plan) == original


@pytest.mark.parametrize("target,expected", [(85.0, 0), (95.0, 1)])
def test_execution_queue_defaults_to_context_target(postflight_queue, target, expected):
    state, plan, _ = postflight_queue
    context = queue_context(state, config={"target_strict_score": target}, plan=plan)
    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(count=None, context=context),
    )
    assert (
        sum(item["kind"] == "subjective_dimension" for item in queue["items"])
        == expected
    )
    assert {item["id"] for item in queue["items"]} == {
        item["id"] for item in context.snapshot.execution_items
    }


def test_backlog_does_not_invent_assessment_above_context_target(postflight_queue):
    state, plan, _ = postflight_queue
    plan["refresh_state"]["lifecycle_phase"] = "execute"
    context = queue_context(state, config={"target_strict_score": 85.0}, plan=plan)
    queue = build_backlog_queue(
        state,
        options=QueueBuildOptions(count=None, context=context),
    )
    assert all(item["kind"] != "subjective_dimension" for item in queue["items"])


def test_execution_queue_uses_default_target_when_no_context_is_provided(
    postflight_queue,
):
    state, plan, issue_id = postflight_queue
    state["dimension_scores"]["AI generated debt"].update(score=99.0, strict=99.0)
    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(count=None, plan=plan),
    )
    assert [item["id"] for item in queue["items"]] == [issue_id]


def test_execution_queue_preserves_explicit_threshold_without_context(postflight_queue):
    state, plan, issue_id = postflight_queue
    queue = build_execution_queue(
        state,
        options=QueueBuildOptions(count=None, plan=plan, subjective_threshold=85.0),
    )
    assert [item["id"] for item in queue["items"]] == [issue_id]
