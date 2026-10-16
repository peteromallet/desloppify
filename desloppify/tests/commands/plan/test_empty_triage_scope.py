"""An explicitly empty triage run must not expand into completed history."""

from copy import deepcopy

import pytest

from desloppify.app.commands.plan.triage.stages.helpers import (
    active_triage_issue_scope,
    scoped_manual_clusters_with_issues,
    unclustered_review_issues,
    unenriched_clusters,
)
from desloppify.app.commands.plan.triage.validation.organize_policy import (
    _clusters_enriched_or_error,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.schema import empty_state


def fixture(scope=()):
    plan = empty_plan()
    state = empty_state()
    if scope is not None:
        plan["epic_triage_meta"]["active_triage_issue_ids"] = list(scope)
    old = make_issue(
        "review",
        "src/past.py",
        "completed",
        tier=4,
        confidence="high",
        summary="Past defect",
        detail={},
    )
    old["status"] = "fixed"
    state["work_items"][old["id"]] = old
    plan["clusters"]["past"] = {
        "name": "past",
        "auto": False,
        "issue_ids": [old["id"]],
        "execution_status": "done",
        "description": "Completed historical work",
        "action_steps": [],
    }
    return plan, state, old


def test_explicit_empty_scope_is_distinct_from_missing_scope():
    plan, state, old = fixture()
    assert active_triage_issue_scope(plan, state) == set()
    assert active_triage_issue_scope(plan) == set()
    plan["epic_triage_meta"].pop("active_triage_issue_ids")
    assert active_triage_issue_scope(plan, state) is None


@pytest.mark.parametrize("value", [None, "bad", {"bad": "scope"}, [None], [""]])
def test_malformed_scope_keeps_legacy_validation(value):
    plan, state, old = fixture()
    plan["epic_triage_meta"]["active_triage_issue_ids"] = value
    assert active_triage_issue_scope(plan, state) is None
    assert [name for name, _ in unenriched_clusters(plan, state)] == ["past"]


def test_explicit_empty_scope_does_not_reenrich_completed_history():
    plan, state, old = fixture()
    before = deepcopy(plan["clusters"])
    assert scoped_manual_clusters_with_issues(plan, state) == []
    assert unenriched_clusters(plan, state) == []
    assert _clusters_enriched_or_error(plan, state)
    assert plan["clusters"] == before


def test_active_strategy_workflow_still_requires_enrichment_in_empty_review_scope():
    plan, state, old = fixture()
    plan["clusters"]["current"] = {
        "name": "current",
        "auto": False,
        "issue_ids": ["strategy::synthetic-audit"],
        "execution_status": "active",
        "description": "Current workflow",
        "action_steps": [],
    }
    assert scoped_manual_clusters_with_issues(plan, state) == ["current"]
    assert [name for name, _ in unenriched_clusters(plan, state)] == ["current"]
    assert not _clusters_enriched_or_error(plan, state)
    plan["clusters"]["current"]["action_steps"] = [{"title": "Verify synthetic audit"}]
    assert _clusters_enriched_or_error(plan, state)


def test_missing_scope_keeps_legacy_history_validation():
    plan, state, old = fixture(None)
    assert [name for name, _ in unenriched_clusters(plan, state)] == ["past"]


def test_nonempty_frozen_scope_keeps_open_review_enrichment_requirement():
    plan, state, old = fixture([old_id := "review::src/live.py::defect"])
    live = make_issue(
        "review",
        "src/live.py",
        "defect",
        tier=4,
        confidence="high",
        summary="Live defect",
        detail={},
    )
    assert live["id"] == old_id
    state["work_items"][old_id] = live
    plan["clusters"]["live"] = {
        "name": "live",
        "auto": False,
        "issue_ids": [old_id],
        "execution_status": "active",
        "description": "Live work",
        "action_steps": [],
    }
    assert active_triage_issue_scope(plan, state) == {old_id}
    assert [name for name, _ in unenriched_clusters(plan, state)] == ["live"]


def test_resolved_nonempty_scope_remains_empty_without_expanding_unrelated_work():
    plan, state, old = fixture()
    plan["epic_triage_meta"]["active_triage_issue_ids"] = [old["id"]]
    plan["clusters"]["other"] = {
        "name": "other",
        "auto": False,
        "issue_ids": ["strategy::other"],
        "execution_status": "active",
        "description": "Other work",
        "action_steps": [],
    }
    assert active_triage_issue_scope(plan, state) == set()
    assert unenriched_clusters(plan, state) == []


def test_new_open_review_is_not_bypassed_by_prior_empty_scope():
    plan, state, old = fixture()
    new = make_issue(
        "review",
        "src/new.py",
        "defect",
        tier=4,
        confidence="high",
        summary="New defect",
        detail={},
    )
    state["work_items"][new["id"]] = new
    assert active_triage_issue_scope(plan, state) == {new["id"]}
    assert unclustered_review_issues(plan, state) == [new["id"]]
    plan["clusters"]["new"] = {
        "name": "new",
        "auto": False,
        "issue_ids": [new["id"]],
        "execution_status": "active",
        "description": "New work",
        "action_steps": [],
    }
    assert [name for name, _ in unenriched_clusters(plan, state)] == ["new"]


def test_reopened_review_in_completed_cluster_still_requires_enrichment():
    plan, state, old = fixture()
    old["status"] = "open"
    plan["epic_triage_meta"]["active_triage_issue_ids"] = [old["id"]]
    assert [name for name, _ in unenriched_clusters(plan, state)] == ["past"]
