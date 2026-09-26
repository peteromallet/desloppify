"""Planning-mode objectives must not block the triage needed to plan them."""

from copy import deepcopy

import pytest

from desloppify.engine._plan.policy.subjective import compute_subjective_visibility
from desloppify.engine._plan.sync.triage_start_policy import decide_triage_start
from desloppify.engine._work_queue.snapshot import build_queue_snapshot


def _pending_plan():
    issue_id = "smells::src/example.py::nested"
    plan = {
        "queue_order": ["workflow::create-plan", issue_id],
        "plan_start_scores": {"strict": 80.0},
        "refresh_state": {"lifecycle_phase": "plan"},
        "epic_triage_meta": {},
    }
    state = {
        "issues": {
            issue_id: {
                "id": issue_id,
                "detector": "smells",
                "status": "open",
                "file": "src/example.py",
                "tier": 3,
                "confidence": "high",
                "summary": "Nested logic needs simplification",
                "detail": {},
            },
        },
        "dimension_scores": {},
        "subjective_assessments": {},
    }
    return plan, state


def test_postflight_workflow_can_start_triage_with_queued_objectives():
    plan, state = _pending_plan()
    policy = compute_subjective_visibility(state, plan=plan)
    snapshot = build_queue_snapshot(state, plan=plan)

    assert policy.objective_count == 1
    assert snapshot.phase == "workflow"
    assert snapshot.objective_execution_count == 0
    assert [item["id"] for item in snapshot.execution_items] == ["workflow::create-plan"]
    decision = decide_triage_start(plan, state, policy=policy, explicit_start=True)
    assert decision.action == "inject"


@pytest.mark.parametrize("phase", ["execute", None])
def test_execution_objectives_still_block_triage(phase):
    plan, state = _pending_plan()
    if phase is None:
        plan.pop("refresh_state")
    else:
        plan["refresh_state"]["lifecycle_phase"] = phase
    policy = compute_subjective_visibility(state, plan=plan)

    decision = decide_triage_start(plan, state, policy=policy, explicit_start=True)

    assert decision.action == "defer"
    assert decision.reason == "objective_backlog_mid_cycle"


def test_postflight_does_not_bypass_unconfirmed_stage_records():
    plan, state = _pending_plan()
    plan["epic_triage_meta"]["triage_stages"] = {
        "observe": {"report": "Recorded but not yet confirmed"},
    }
    original = deepcopy(plan)
    decision = decide_triage_start(
        plan, state, policy=compute_subjective_visibility(state, plan=plan),
        explicit_start=True,
    )

    assert decision.action == "defer"
    assert decision.reason == "unfinished_triage_stage_records"
    assert plan == original
