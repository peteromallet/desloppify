"""Ready review work must be executable before its blocked reassessment."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from desloppify.app.commands.resolve.plan_load import (
    DegradedPlanWarningState,
    ResolvePlanAccess,
)
from desloppify.app.commands.resolve.queue_guard import _check_queue_order_guard
from desloppify.app.commands.review import preflight
from desloppify.base.exception_sets import CommandError
from desloppify.base.subjective_dimensions import DISPLAY_NAMES
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync.pipeline import (
    ReconcileResult,
    _resolve_reconcile_display_phase,
)
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.resolution import resolve_issues
from desloppify.engine._state.schema import empty_state
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.models import QueueBuildOptions
from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)


def _case():
    state = empty_state()
    state["dimension_scores"] = {}
    state["scan_count"] = 4
    state["last_scan"] = "2026-01-01T00:00:00Z"
    for key, score in [("naming_quality", 75.0), ("design_coherence", 78.0)]:
        state["subjective_assessments"][key] = {
            "score": score,
            "needs_review_refresh": True,
        }
        state["dimension_scores"][DISPLAY_NAMES[key]] = {
            "score": score,
            "strict": score,
            "failing": 0,
            "checks": 1,
            "detectors": {
                "subjective_assessment": {"dimension_key": key, "placeholder": False}
            },
        }
    a = make_issue(
        "review",
        ".",
        "holistic::naming_quality::command_name",
        tier=2,
        confidence="high",
        summary="Command naming contract",
        detail={"dimension": "naming_quality"},
    )
    b = make_issue(
        "review",
        ".",
        "holistic::naming_quality::client_name",
        tier=2,
        confidence="high",
        summary="Client naming contract",
        detail={"dimension": "naming_quality"},
    )
    strategy = make_issue(
        "strategy",
        ".",
        "structure_cycle",
        tier=2,
        confidence="high",
        summary="Repair the current design loop",
        detail={"dimension": "Design coherence"},
    )
    unrelated = make_issue(
        "unused",
        "src/task.py",
        "old_import",
        tier=1,
        confidence="high",
        summary="Unplanned unrelated import",
        detail={},
    )
    state["work_items"] = {x["id"]: x for x in [a, b, strategy, unrelated]}
    plan = empty_plan()
    plan["plan_start_scores"] = {"strict": 60.0}
    plan["refresh_state"] = {
        "lifecycle_phase": "plan",
        "postflight_scan_completed_at_scan_count": 4,
        "subjective_review_completed_at_scan_count": 3,
    }
    plan["queue_order"] = [
        a["id"],
        b["id"],
        strategy["id"],
        "subjective::design_coherence",
    ]
    plan["epic_triage_meta"]["triaged_ids"] = [a["id"], b["id"]]
    plan["epic_triage_meta"]["last_completed_at"] = "2026-01-01T00:00:00Z"
    plan["clusters"] = {
        "command-contracts": {
            "issue_ids": [a["id"], b["id"]],
            "description": "Repair command boundaries",
            "action_steps": ["Repair and verify the two actual command names."],
        }
    }
    return state, plan, a, b, strategy, unrelated


def _args():
    return SimpleNamespace(
        dimensions=None,
        force_review_rerun=False,
        run_batches=False,
        external_start=False,
    )


def _context(monkeypatch, state, plan):
    ctx = queue_context(state, plan=plan)
    monkeypatch.setattr(preflight, "queue_context", lambda _state: ctx)
    return ctx


def test_ready_cluster_is_executable_while_rerun_remains_blocked(
    monkeypatch, set_project_root, capsys
):
    state, plan, a, b, strategy, unrelated = _case()
    ctx = _context(monkeypatch, state, plan)
    with pytest.raises(CommandError, match="rerun blocked"):
        preflight.review_rerun_preflight(state, _args())
    assert (
        preflight._objective_and_subjective_backlog(
            state, blocking_dims=preflight._scored_dimensions(state)
        )[1]
        == 3
    )
    assert ctx.snapshot.phase == "review"
    items = build_execution_queue(
        state, options=QueueBuildOptions(context=ctx, count=None)
    )["items"]
    assert {x["id"] for x in items} == {a["id"], b["id"], strategy["id"]}
    backlog = build_backlog_queue(
        state, options=QueueBuildOptions(context=ctx, count=None)
    )["items"]
    assert unrelated["id"] in {x["id"] for x in backlog}
    access = ResolvePlanAccess(
        plan=plan,
        degraded=False,
        error_kind=None,
        warning_state=DegradedPlanWarningState(),
    )
    # The second member belongs to the front cluster, although it is not the
    # first exact issue in the raw persisted queue. This exercises real guard
    # selection rather than its first-exact-issue shortcut.
    assert (
        _check_queue_order_guard(state, [b["id"]], "fixed", plan_access=access) is False
    )
    assert "Queue order violation" not in capsys.readouterr().out
    assert (
        _resolve_reconcile_display_phase(
            plan, state, result=ReconcileResult(), policy=None
        )
        == ctx.snapshot.phase
    )


def test_assessment_returns_only_after_each_real_blocker_is_resolved(
    monkeypatch, set_project_root
):
    state, plan, a, b, strategy, unrelated = _case()
    original_scores = {
        key: value["score"] for key, value in state["subjective_assessments"].items()
    }
    for issue in [a, b, strategy]:
        ctx = _context(monkeypatch, state, plan)
        with pytest.raises(CommandError, match="rerun blocked"):
            preflight.review_rerun_preflight(state, _args())
        assert ctx.snapshot.phase == "review"
        assert resolve_issues(
            state,
            issue["id"],
            "fixed",
            note="The synthetic contract was repaired and verified.",
        ) == [issue["id"]]
    ctx = _context(monkeypatch, state, plan)
    assert ctx.snapshot.phase == "assessment"
    assert preflight._objective_and_subjective_backlog(
        state, blocking_dims=preflight._scored_dimensions(state)
    ) == (0, 0)
    preflight.review_rerun_preflight(state, _args())
    assert state["work_items"][unrelated["id"]]["status"] == "open"
    assert original_scores == {
        key: value["score"] for key, value in state["subjective_assessments"].items()
    }
    assert all(
        state["work_items"][x["id"]]["status"] == "fixed" for x in [a, b, strategy]
    )


def test_exact_second_cluster_member_is_not_blocked_by_its_reassessment(
    monkeypatch,
    set_project_root,
    capsys,
):
    state, plan, a, b, strategy, _unrelated = _case()
    ctx = _context(monkeypatch, state, plan)
    with pytest.raises(CommandError, match="rerun blocked"):
        preflight.review_rerun_preflight(state, _args())
    access = ResolvePlanAccess(
        plan=plan,
        degraded=False,
        error_kind=None,
        warning_state=DegradedPlanWarningState(),
    )
    assert (
        _check_queue_order_guard(state, [b["id"]], "fixed", plan_access=access) is False
    )
    assert resolve_issues(
        state, b["id"], "fixed", note="The actual synthetic command was repaired."
    ) == [b["id"]]
    ctx = _context(monkeypatch, state, plan)
    assert {item["id"] for item in ctx.snapshot.execution_items} == {
        a["id"],
        strategy["id"],
    }
    with pytest.raises(CommandError, match="rerun blocked"):
        preflight.review_rerun_preflight(state, _args())
    assert "Queue order violation" not in capsys.readouterr().out


def test_pending_workflow_precedes_ready_blockers_and_blocked_assessment(
    monkeypatch,
    set_project_root,
):
    from desloppify.engine._plan.constants import WORKFLOW_CREATE_PLAN_ID

    state, plan, _a, _b, _strategy, _unrelated = _case()
    plan["queue_order"].insert(0, WORKFLOW_CREATE_PLAN_ID)
    ctx = _context(monkeypatch, state, plan)
    assert ctx.snapshot.phase == "workflow"
    assert [item["id"] for item in ctx.snapshot.execution_items] == [
        WORKFLOW_CREATE_PLAN_ID
    ]
    assert (
        _resolve_reconcile_display_phase(
            plan, state, result=ReconcileResult(), policy=None
        )
        == "workflow"
    )
    with pytest.raises(CommandError, match="rerun blocked"):
        preflight.review_rerun_preflight(state, _args())


def test_pending_triage_keeps_raw_findings_out_of_execution(
    monkeypatch, set_project_root
):
    state, plan, _a, _b, _strategy, _unrelated = _case()
    plan["queue_order"].insert(0, "triage::observe")
    ctx = _context(monkeypatch, state, plan)
    assert ctx.snapshot.all_postflight_review_items == ()
    assert all(item["kind"] != "issue" for item in ctx.snapshot.execution_items)
    # Unready findings retain the existing assessment/triage priority policy.
    assert ctx.snapshot.phase == "assessment"
    assert (
        _resolve_reconcile_display_phase(
            plan, state, result=ReconcileResult(), policy=None
        )
        == "assessment"
    )


def test_required_scan_precedes_ready_review_blockers(monkeypatch, set_project_root):
    from desloppify.engine._plan.constants import WORKFLOW_RUN_SCAN_ID

    state, plan, _a, _b, _strategy, _unrelated = _case()
    plan["queue_order"] = [WORKFLOW_RUN_SCAN_ID]
    plan["refresh_state"] = {"lifecycle_phase": "execute"}
    ctx = _context(monkeypatch, state, plan)
    assert ctx.snapshot.phase == "scan"
    assert [item["id"] for item in ctx.snapshot.execution_items] == [
        WORKFLOW_RUN_SCAN_ID
    ]
    assert (
        _resolve_reconcile_display_phase(
            plan, state, result=ReconcileResult(), policy=None
        )
        == "scan"
    )


def test_initial_review_retains_priority_over_ready_blockers(
    monkeypatch, set_project_root
):
    state, plan, _a, _b, _strategy, _unrelated = _case()
    plan["plan_start_scores"] = {}
    plan["queue_order"].insert(0, "subjective::logic_clarity")
    state["subjective_assessments"]["logic_clarity"] = {"score": 0, "placeholder": True}
    state["dimension_scores"][DISPLAY_NAMES["logic_clarity"]] = {
        "score": 0,
        "strict": 0,
        "failing": 0,
        "checks": 0,
        "detectors": {
            "subjective_assessment": {
                "dimension_key": "logic_clarity",
                "placeholder": True,
            }
        },
    }
    ctx = _context(monkeypatch, state, plan)
    assert ctx.snapshot.phase == "review_initial"
    assert [item["id"] for item in ctx.snapshot.execution_items] == [
        "subjective::logic_clarity"
    ]
    policy = SimpleNamespace(unscored_ids={"subjective::logic_clarity"})
    assert (
        _resolve_reconcile_display_phase(
            plan, state, result=ReconcileResult(), policy=policy
        )
        == "review_initial"
    )


def test_ready_triage_prerequisite_priority_uses_the_shared_phase_contract():
    from desloppify.engine._plan.refresh_lifecycle import derive_display_phase

    assert (
        derive_display_phase(
            has_initial_review=False,
            has_postflight_assessment=True,
            has_workflow=False,
            has_triage=True,
            has_review_postflight=True,
            has_execution=False,
            fresh_boundary=False,
            prefer_scan=False,
            has_reassessment_blockers=True,
        )
        == "triage"
    )
