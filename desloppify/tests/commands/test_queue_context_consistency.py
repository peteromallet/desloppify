"""Queue consumers must agree on the resolved subjective review target."""

from __future__ import annotations

import pytest

from desloppify.app.commands.next.queue_flow import NextOptions, _resolve_queue_items
from desloppify.app.commands.plan.queue_render import _build_queue_items
from desloppify.app.commands.resolve.plan_load import (
    DegradedPlanWarningState,
    ResolvePlanAccess,
)
from desloppify.app.commands.resolve.queue_guard import _check_queue_order_guard
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.core import QueueBuildOptions, build_work_queue
from desloppify.engine._work_queue.inputs import resolve_queue_inputs
from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)


@pytest.fixture
def reviewed_work() -> tuple[dict, dict]:
    """A triaged finding and an unrelated stale assessment above the default target."""
    issue_id = "review::src/widget.py::ownership"
    state = {
        "issues": {
            issue_id: {
                "id": issue_id,
                "detector": "review",
                "status": "open",
                "file": "src/widget.py",
                "tier": 4,
                "confidence": "high",
                "summary": "Separate ownership",
                "detail": {"dimension": "cross_module_architecture"},
            },
        },
        "scan_count": 5,
        "dimension_scores": {
            "Naming quality": {
                "score": 90.0,
                "strict": 90.0,
                "failing": 0,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
        "subjective_assessments": {
            "naming_quality": {
                "score": 90.0,
                "needs_review_refresh": True,
                "stale_since": "2026-01-01T00:00:00+00:00",
                "refresh_reason": "mechanical_issues_changed",
            },
        },
    }
    plan = empty_plan()
    plan.update({
        "queue_order": [issue_id],
        "plan_start_scores": {"strict": 80.0},
        "clusters": {
            "ownership": {
                "name": "ownership",
                "auto": False,
                "issue_ids": [issue_id],
            },
        },
        "epic_triage_meta": {"triaged_ids": [issue_id]},
        "refresh_state": {"lifecycle_phase": "plan"},
    })
    return state, plan


@pytest.mark.parametrize("target, option_threshold", [(85.0, 100.0), (95.0, 80.0)])
def test_context_target_is_authoritative(reviewed_work, target, option_threshold):
    state, plan = reviewed_work
    ctx = queue_context(state, plan=plan, target_strict=target)
    opts = QueueBuildOptions(
        count=None, context=ctx, subjective_threshold=option_threshold,
    )

    assert resolve_queue_inputs(opts, state)[3] == target
    result = build_work_queue(state, options=opts)
    assert [item["id"] for item in result["items"]] == [
        item["id"] for item in ctx.snapshot.execution_items
    ]


def test_queue_options_keep_explicit_threshold_without_context(reviewed_work):
    state, plan = reviewed_work
    opts = QueueBuildOptions(subjective_threshold=95.0, plan=plan)
    assert resolve_queue_inputs(opts, state)[3] == 95.0


@pytest.mark.parametrize("builder", [build_execution_queue, build_backlog_queue])
def test_policy_builders_keep_explicit_threshold_without_context(reviewed_work, builder, monkeypatch):
    import desloppify.engine.planning.queue_policy as queue_policy

    state, plan = reviewed_work
    contexts = []

    def capture_context(*args, **kwargs):
        ctx = queue_context(*args, **kwargs)
        contexts.append(ctx)
        return ctx

    monkeypatch.setattr(queue_policy, "queue_context", capture_context)
    result = builder(
        state,
        options=QueueBuildOptions(count=None, plan=plan, subjective_threshold=95.0),
    )
    assert contexts[0].target_strict == 95.0
    expected = (
        "subjective::naming_quality" if builder is build_execution_queue
        else "review::src/widget.py::ownership"
    )
    assert [item["id"] for item in result["items"]] == [expected]


def test_next_and_plan_queue_agree_on_default_target(reviewed_work):
    state, plan = reviewed_work
    _, next_queue, _, _ = _resolve_queue_items(
        state=state,
        config={},
        opts=NextOptions(),
        plan_for_queue=plan,
        target_strict=85.0,
        build_work_queue_fn=build_execution_queue,
    )
    plan_items, plan_queue = _build_queue_items(
        state=state, plan=plan, include_skipped=False, effective_cluster=None,
    )

    expected = ["review::src/widget.py::ownership"]
    assert [item["id"] for item in next_queue["items"]] == expected
    assert [item["id"] for item in plan_queue["items"]] == expected
    assert [item["id"] for item in plan_items] == expected


def test_resolve_allows_the_cluster_shown_by_next(reviewed_work, capsys):
    state, plan = reviewed_work
    access = ResolvePlanAccess(
        plan=plan,
        degraded=False,
        error_kind=None,
        warning_state=DegradedPlanWarningState(),
    )

    assert not _check_queue_order_guard(
        state, ["ownership"], "fixed", plan_access=access,
    )
    assert "Queue order violation" not in capsys.readouterr().out
