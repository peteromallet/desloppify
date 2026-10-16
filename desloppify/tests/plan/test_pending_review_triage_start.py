"""Pending imported findings must not block their own classification."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from desloppify.app.commands.plan.triage.lifecycle import ensure_triage_started
from desloppify.engine._plan.constants import TRIAGE_IDS
from desloppify.engine._plan.policy.subjective import compute_subjective_visibility
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync.triage_start_policy import decide_triage_start
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.schema import empty_state


def fixture(detector="review"):
    state = empty_state()
    issue = make_issue(
        detector,
        ".",
        "pending",
        tier=4,
        confidence="high",
        summary="Synthetic review defect",
        detail={"dimension": "design_coherence"},
    )
    state["work_items"][issue["id"]] = issue
    plan = empty_plan()
    plan["queue_order"] = [issue["id"]]
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["epic_triage_meta"]["triaged_ids"] = ["review::src/prior.py::completed"]
    return state, plan, issue


def caller_policy(state, plan):
    """Model callers that count queued review repairs, without altering defaults."""
    baseline = compute_subjective_visibility(state, plan=plan)
    queued = set(plan["queue_order"])
    count = sum(
        issue.get("status") == "open"
        and issue_id in queued
        and not issue.get("suppressed")
        for issue_id, issue in state["work_items"].items()
    )
    return replace(baseline, has_objective_backlog=count > 0, objective_count=count)


def decide(state, plan):
    return decide_triage_start(
        plan, state, policy=caller_policy(state, plan), explicit_start=True
    )


@pytest.mark.parametrize("detector", ["review", "concerns"])
def test_new_untriaged_import_can_start_triage_without_changing_global_visibility(
    detector,
):
    state, plan, issue = fixture(detector)
    baseline = compute_subjective_visibility(state, plan=plan)
    policy = caller_policy(state, plan)
    assert policy.has_objective_backlog and policy.objective_count == 1
    assert decide(state, plan).action == "inject"
    assert compute_subjective_visibility(state, plan=plan) == baseline


def test_actual_entrypoint_injects_stages_without_attestation_override():
    state, plan, issue = fixture()
    saved = []
    services = SimpleNamespace(save_plan=lambda value: saved.append(deepcopy(value)))
    result = ensure_triage_started(
        plan, state=state, services=services, policy=caller_policy(state, plan)
    )
    assert result.status == "started"
    assert set(plan["queue_order"]) & TRIAGE_IDS
    assert plan["epic_triage_meta"]["active_triage_issue_ids"] == [issue["id"]]
    assert saved


def test_existing_queued_mechanical_repair_still_blocks():
    state, plan, issue = fixture()
    repair = make_issue(
        "structural",
        "src/large.py",
        "large",
        tier=3,
        confidence="high",
        summary="Large file",
        detail={},
    )
    state["work_items"][repair["id"]] = repair
    plan["queue_order"].append(repair["id"])
    assert decide(state, plan).reason == "objective_backlog_mid_cycle"


def test_unqueued_mechanical_backlog_does_not_create_a_new_triage_gate():
    state, plan, issue = fixture()
    repair = make_issue(
        "structural",
        "src/backlog.py",
        "large",
        tier=3,
        confidence="high",
        summary="Backlog",
        detail={},
    )
    state["work_items"][repair["id"]] = repair
    assert decide(state, plan).action == "inject"


@pytest.mark.parametrize(
    "ownership", ["triaged", "promoted", "manual_cluster", "modified_auto_cluster"]
)
def test_existing_review_repair_ownership_still_blocks(ownership):
    state, plan, issue = fixture()
    if ownership == "triaged":
        plan["epic_triage_meta"]["triaged_ids"].append(issue["id"])
    elif ownership == "promoted":
        plan["promoted_ids"] = [issue["id"]]
    else:
        plan["clusters"]["repair"] = {
            "name": "repair",
            "issue_ids": [issue["id"]],
            "auto": ownership == "modified_auto_cluster",
            "user_modified": ownership == "modified_auto_cluster",
        }
    assert decide(state, plan).reason == "objective_backlog_mid_cycle"


def test_unmodified_automatic_cluster_does_not_stand_in_for_triage():
    state, plan, issue = fixture()
    plan["clusters"]["auto/review"] = {
        "name": "auto/review",
        "issue_ids": [issue["id"]],
        "auto": True,
        "user_modified": False,
    }
    assert decide(state, plan).action == "inject"


def test_unfinished_stage_records_guard_still_wins():
    state, plan, issue = fixture()
    plan["epic_triage_meta"]["triage_stages"] = {
        "strategize": {"report": "Prior unconfirmed report"}
    }
    assert decide(state, plan).reason == "unfinished_triage_stage_records"


def test_existing_active_stages_remain_active():
    state, plan, issue = fixture()
    plan["queue_order"].append(next(iter(TRIAGE_IDS)))
    assert decide(state, plan).action == "already_active"


def test_decision_does_not_mutate_state_or_plan():
    state, plan, issue = fixture()
    before = (deepcopy(state), deepcopy(plan))
    decide(state, plan)
    assert (state, plan) == before


@pytest.mark.parametrize(
    "ownership", ["triaged", "promoted", "manual_cluster", "modified_auto_cluster"]
)
def test_existing_owned_review_repair_blocks_with_new_pending_findings(ownership):
    state, plan, pending = fixture()
    owned = make_issue(
        "review",
        ".",
        "owned",
        tier=4,
        confidence="high",
        summary="Existing review repair",
        detail={},
    )
    state["work_items"][owned["id"]] = owned
    plan["queue_order"].append(owned["id"])
    if ownership == "triaged":
        plan["epic_triage_meta"]["triaged_ids"].append(owned["id"])
    elif ownership == "promoted":
        plan["promoted_ids"].append(owned["id"])
    else:
        plan["clusters"]["repair"] = {
            "name": "repair",
            "issue_ids": [owned["id"]],
            "auto": ownership == "modified_auto_cluster",
            "user_modified": ownership == "modified_auto_cluster",
        }
    assert decide(state, plan).reason == "objective_backlog_mid_cycle"


def test_suppressed_pending_review_is_not_subtracted_from_supplied_repair_count():
    state, plan, pending = fixture()
    pending["suppressed"] = True
    owned = make_issue(
        "review",
        ".",
        "owned",
        tier=4,
        confidence="high",
        summary="Existing repair",
        detail={},
    )
    state["work_items"][owned["id"]] = owned
    plan["queue_order"].append(owned["id"])
    plan["epic_triage_meta"]["triaged_ids"].append(owned["id"])
    assert caller_policy(state, plan).objective_count == 1
    assert decide(state, plan).reason == "objective_backlog_mid_cycle"


def test_default_public_visibility_behavior_stays_unchanged():
    state, plan, pending = fixture()
    baseline = compute_subjective_visibility(state, plan=plan)
    before = deepcopy(baseline)
    assert decide_triage_start(plan, state, policy=baseline).action == "inject"
    assert compute_subjective_visibility(state, plan=plan) == before
