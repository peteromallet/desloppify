"""Explicit queue ownership must agree between ranking and review visibility."""

from __future__ import annotations

from copy import deepcopy

import pytest

from desloppify.engine._plan.policy.subjective import compute_subjective_visibility
from desloppify.engine._work_queue.snapshot import build_queue_snapshot

ISSUE_ID = "structural::src/owner.py"


def _state() -> dict:
    return {
        "issues": {
            ISSUE_ID: {
                "id": ISSUE_ID,
                "detector": "structural",
                "status": "open",
                "file": "src/owner.py",
                "confidence": "medium",
                "detail": {},
            },
        },
    }


def test_explicit_evidence_repair_counts_as_visible_planned_backlog():
    state = _state()
    plan = {"queue_order": [ISSUE_ID]}
    snapshot = build_queue_snapshot(state, plan=plan)
    assert snapshot.planned_objective_count == 1
    policy = compute_subjective_visibility(state, plan=plan)
    assert policy.objective_count == snapshot.planned_objective_count
    assert policy.backlog_blocks_rerun


@pytest.mark.parametrize("ownership", ["none", "cluster", "override", "synthetic"])
def test_evidence_only_repair_requires_explicit_queue_ownership(ownership):
    state = _state()
    plan = {"queue_order": []}
    if ownership == "cluster":
        plan["clusters"] = {"repair": {"issue_ids": [ISSUE_ID], "status": "active"}}
    elif ownership == "override":
        plan["overrides"] = {ISSUE_ID: {"cluster": "repair"}}
    elif ownership == "synthetic":
        plan["queue_order"] = ["subjective::logic_clarity"]
    assert compute_subjective_visibility(state, plan=plan).objective_count == 0


@pytest.mark.parametrize(
    "excluded", ["skipped", "suppressed", "fixed", "wontfix", "scope"]
)
def test_explicit_queue_does_not_bypass_other_eligibility_guards(excluded):
    state = _state()
    plan = {"queue_order": [ISSUE_ID]}
    if excluded == "skipped":
        plan["skipped"] = {ISSUE_ID: {"kind": "temporary"}}
    elif excluded == "suppressed":
        state["issues"][ISSUE_ID]["suppressed"] = True
    elif excluded in {"fixed", "wontfix"}:
        state["issues"][ISSUE_ID]["status"] = excluded
    else:
        state["scan_path"] = "elsewhere"
    assert compute_subjective_visibility(state, plan=plan).objective_count == 0


def test_queued_repair_defers_stale_review_without_clearing_assessment():
    state = _state()
    state["dimension_scores"] = {
        "Logic clarity": {
            "score": 70.0,
            "strict": 70.0,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": "logic_clarity",
                    "placeholder": False,
                }
            },
        },
    }
    state["subjective_assessments"] = {
        "logic_clarity": {
            "score": 70.0,
            "needs_review_refresh": True,
            "refresh_reason": "review_issue_fixed",
            "stale_since": "2026-01-02T00:00:00+00:00",
        },
    }
    before = deepcopy(state)
    plan = {"queue_order": [ISSUE_ID]}
    policy = compute_subjective_visibility(state, plan=plan)
    assert "subjective::logic_clarity" in policy.stale_ids
    assert not policy.should_inject_to_plan("subjective::logic_clarity")
    assert state == before
    state["issues"][ISSUE_ID]["status"] = "fixed"
    assert compute_subjective_visibility(state, plan=plan).should_inject_to_plan(
        "subjective::logic_clarity"
    )


def test_unplanned_medium_evidence_and_high_confidence_keep_existing_policy():
    state = _state()
    assert compute_subjective_visibility(state, plan=None).objective_count == 0
    state["issues"][ISSUE_ID]["confidence"] = "high"
    assert compute_subjective_visibility(state, plan=None).objective_count == 1
    assert (
        compute_subjective_visibility(
            state, plan={"queue_order": [ISSUE_ID]}
        ).objective_count
        == 1
    )
