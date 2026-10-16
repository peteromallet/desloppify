"""Workflow-only triage quality validates current work without rewriting history."""

from copy import deepcopy
from pathlib import Path

import pytest

from desloppify.app.commands.plan.triage.confirmations.enrich import (
    _collect_enrich_level_confirmation_checks,
)
from desloppify.app.commands.plan.triage.stages.sense_check import (
    SenseCheckStageDeps,
    _sense_check_evidence_failures,
    _sense_check_quality_problems,
)
from desloppify.app.commands.plan.triage.validation.enrich_quality import (
    evaluate_enrich_quality,
)


def plan_fixture(scope=()):
    plan = {
        "epic_triage_meta": {},
        "clusters": {
            "past": {
                "auto": False,
                "issue_ids": ["review::past"],
                "execution_status": "done",
                "action_steps": [{"title": "Historical completed step"}],
            },
            "current": {
                "auto": False,
                "issue_ids": ["strategy::current"],
                "execution_status": "active",
                "action_steps": [
                    {
                        "title": "Verify current evidence",
                        "detail": "Verify the current workflow evidence and preserve all completed historical work without manufacturing new source requirements.",
                        "issue_refs": ["strategy::current"],
                        "effort": "small",
                    }
                ],
            },
        },
    }
    if scope is not None:
        plan["epic_triage_meta"]["active_triage_issue_ids"] = list(scope)
    return plan


def quality(plan, ids=None):
    return evaluate_enrich_quality(
        plan,
        Path.cwd(),
        phase_label="sense-check",
        bad_paths_severity="failure",
        missing_effort_severity="failure",
        include_missing_issue_refs=True,
        include_vague_detail=True,
        stale_issue_refs_severity=None,
        triage_issue_ids=ids,
    )


@pytest.mark.parametrize("entry", ["quality", "confirmation", "sense-check"])
def test_empty_scope_quality_ignores_completed_history(entry):
    plan = plan_fixture()
    before = deepcopy(plan)
    if entry == "quality":
        assert quality(plan).failures == []
    elif entry == "confirmation":
        assert (
            _collect_enrich_level_confirmation_checks(
                plan,
                include_stale_issue_ref_warning=True,
            ).failures
            == []
        )
    else:
        assert (
            _sense_check_quality_problems(
                plan,
                {"work_items": {}},
                deps=SenseCheckStageDeps(get_project_root=Path.cwd),
            )
            == []
        )
    assert plan == before


def test_empty_scope_keeps_active_missing_detail_failure():
    plan = plan_fixture()
    plan["clusters"]["current"]["action_steps"] = [{"title": "Missing detail"}]
    issue = quality(plan).failure("underspecified")
    assert issue is not None
    assert issue.rows == [("current", 1, 1)]


@pytest.mark.parametrize("scope", [None, "malformed", [""], [None]])
def test_legacy_or_malformed_scope_keeps_history_validation(scope):
    plan = plan_fixture(None)
    if scope is not None:
        plan["epic_triage_meta"]["active_triage_issue_ids"] = scope
    issue = quality(plan).failure("underspecified")
    assert issue is not None
    assert issue.rows == [("past", 1, 1)]


def test_nonempty_scope_retains_matching_completed_reopened_cluster():
    plan = plan_fixture(["review::past"])
    issue = quality(plan, {"review::past"}).failure("underspecified")
    assert issue is not None
    assert issue.rows == [("past", 1, 1)]


def test_nonempty_scope_excludes_other_work_but_checks_current():
    plan = plan_fixture(["strategy::current"])
    assert quality(plan, {"strategy::current"}).failures == []
    plan["clusters"]["current"]["action_steps"][0].pop("detail")
    assert quality(plan, {"strategy::current"}).failure("vague_detail") is not None


def test_sense_evidence_only_requires_current_workflow_cluster():
    plan = plan_fixture()
    for index in range(10):
        plan["clusters"][f"past-{index}"] = deepcopy(plan["clusters"]["past"])
    report = "Verified current content, structure, and value. The current cluster retains concrete steps and references and needs no source change."
    blocking, advisory = _sense_check_evidence_failures(
        report,
        plan=plan,
        state={"work_items": {}},
    )
    assert blocking == []
    assert advisory == []


def test_sense_evidence_still_requires_active_workflow_reference():
    plan = plan_fixture()
    blocking, advisory = _sense_check_evidence_failures(
        "Verified unrelated work without describing an execution target.",
        plan=plan,
        state={"work_items": {}},
    )
    assert blocking or advisory


def test_historical_name_cannot_substitute_for_current_sense_evidence():
    plan = plan_fixture()
    blocking, _ = _sense_check_evidence_failures(
        "Verified past completed work; no new execution target is described.",
        plan=plan,
        state={"work_items": {}},
    )
    assert [failure.code for failure in blocking] == ["no_cluster_mention"]


def test_new_live_review_under_prior_empty_scope_still_blocks_quality():
    from desloppify.engine._state.filtering import make_issue

    plan = plan_fixture()
    live = make_issue(
        "review",
        "src/live.py",
        "defect",
        tier=4,
        confidence="high",
        summary="Live defect",
        detail={},
    )
    plan["clusters"]["live"] = {
        "auto": False,
        "issue_ids": [live["id"]],
        "execution_status": "active",
        "action_steps": [{"title": "Missing live defect detail"}],
    }
    problems = _sense_check_quality_problems(
        plan,
        {"work_items": {live["id"]: live}},
        deps=SenseCheckStageDeps(get_project_root=Path.cwd),
    )
    assert any(message.startswith("1 step(s) still lack") for message in problems)


def test_exhausted_nonempty_scope_without_state_retains_prior_history_check():
    # Callers currently collapse a computed-empty live scope to None. The quality
    # API has no state, so it cannot distinguish this from the frozen raw scope.
    plan = plan_fixture(["review::past"])
    issue = quality(plan, None).failure("underspecified")
    assert issue is not None
    assert issue.rows == [("past", 1, 1)]
