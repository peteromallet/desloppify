"""Only canonical false-positive reopen cycles are excluded from freshness."""

import argparse
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from desloppify.app.commands.scan import workflow
from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.merge import MergeScanOptions, merge_scan
from desloppify.engine._state.schema import empty_state


def orphan(file="src/cli.py"):
    return make_issue(
        "orphaned",
        file,
        "no_importers",
        tier=3,
        confidence="high",
        summary="No static importers",
        detail={},
    )


@pytest.fixture
def run_app_merge(monkeypatch, tmp_path):
    state = empty_state()
    state["last_scan"] = "2026-01-01T10:00:00+00:00"
    state["scan_count"] = 10
    state["subjective_assessments"] = {
        "design_coherence": {
            "score": 90,
            "source": "holistic",
            "assessed_at": "2026-01-01T11:00:00+00:00",
        }
    }
    issue = orphan()
    issue.update(status="false_positive", resolved_at="2026-01-01T09:00:00+00:00")
    state["work_items"][issue["id"]] = issue
    plan = empty_plan()
    plan["skipped"][issue["id"]] = {
        "issue_id": issue["id"],
        "kind": "false_positive",
        "note": "Executable has dynamic callers",
        "attestation": "Reviewed fixture",
        "created_at": "2026-01-01T09:00:00+00:00",
        "review_after": None,
        "skipped_at_scan": 1,
    }
    state_path = tmp_path / "state.json"
    runtime = workflow.ScanRuntime(
        args=argparse.Namespace(force_resolve=True),
        state_path=state_path,
        state=state,
        path=tmp_path,
        config={},
        lang=SimpleNamespace(name="python", zone_map=None),
        lang_label="Python",
        profile="full",
        effective_include_slow=True,
        zone_overrides=None,
    )
    monkeypatch.setattr(workflow, "rel", lambda path: ".")
    monkeypatch.setattr(workflow, "get_exclusions", lambda: ())
    monkeypatch.setattr(workflow, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(workflow, "_persist_scan_coverage", lambda *args: None)
    monkeypatch.setattr(workflow, "mark_stale_holistic", lambda *args: None)
    monkeypatch.setattr(workflow, "save_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        workflow,
        "_reconcile_plan_post_scan",
        lambda rt: reconcile_plan_after_scan(plan, rt.state),
    )

    def run(current):
        (tmp_path / "plan.json").write_text(json.dumps(plan))
        return workflow.merge_scan_results(
            runtime, deepcopy(current), {"orphaned": 10}, None
        )

    return state, plan, deepcopy(issue), run


def test_active_canonical_false_positive_stays_fresh_and_reopen_count_retained(
    run_app_merge,
):
    state, plan, current, run = run_app_merge
    for count in (1, 2):
        result = run([current])
        assert result.diff["reopened"] == 1
        assert state["work_items"][current["id"]]["status"] == "false_positive"
        assert state["work_items"][current["id"]]["reopen_count"] == count
        assert not state["subjective_assessments"]["design_coherence"].get(
            "needs_review_refresh"
        )


def test_direct_merge_without_app_policy_keeps_reopening_semantics(run_app_merge):
    state, plan, current, run = run_app_merge
    result = merge_scan(state, [current], MergeScanOptions(potentials={"orphaned": 10}))
    assert result["reopened"] == 1
    assert state["work_items"][current["id"]]["status"] == "open"
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_new_issue_same_detector_stales_even_with_canonical_false_positive(
    run_app_merge,
):
    state, plan, current, run = run_app_merge
    new = orphan("src/unreachable.py")
    run([current, new])
    assert state["work_items"][current["id"]]["status"] == "false_positive"
    assert state["work_items"][new["id"]]["status"] == "open"
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


@pytest.mark.parametrize(
    "kind", [None, "permanent", "temporary", "triage_observe_auto"]
)
def test_removed_changed_or_expired_skip_does_not_protect(run_app_merge, kind):
    state, plan, current, run = run_app_merge
    if kind is None:
        plan["skipped"].clear()
    else:
        plan["skipped"][current["id"]].update(
            kind=kind, review_after=1, skipped_at_scan=1
        )
    run([current])
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]
    if kind == "temporary":
        assert current["id"] not in plan["skipped"]
        assert state["work_items"][current["id"]]["status"] == "open"


def test_superseded_false_positive_skip_does_not_protect(run_app_merge):
    state, plan, current, run = run_app_merge
    plan["superseded"][current["id"]] = {
        "original_id": current["id"],
        "status": "superseded",
        "superseded_at": "2026-01-01T09:00:00+00:00",
        "candidates": [],
    }
    run([current])
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_existing_refresh_reason_survives_canonical_reappearance(run_app_merge):
    state, plan, current, run = run_app_merge
    assessment = state["subjective_assessments"]["design_coherence"]
    assessment.update(
        needs_review_refresh=True,
        refresh_reason="review_issue_fixed",
        stale_since="2026-01-01T09:00:00+00:00",
    )
    before = deepcopy(assessment)
    run([current])
    assert assessment == before


def test_first_absence_verification_stales_despite_canonical_skip(run_app_merge):
    state, plan, current, run = run_app_merge
    run([])
    assert state["work_items"][current["id"]]["resolution_attestation"]["scan_verified"]
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_absence_after_same_second_reappearance_still_adds_evidence(run_app_merge):
    state, plan, current, run = run_app_merge
    issue = state["work_items"][current["id"]]
    issue["resolution_attestation"] = {
        "scan_verified": True,
        "scan_verified_at": "2026-01-01T10:00:00+00:00",
        "scan_verification_text": "Absent from detector output in latest scan",
    }
    run([current])
    # A raw false-positive reopen clears the old attestation as before.
    assert not issue.get("resolution_attestation", {}).get("scan_verified")
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )
    run([])
    assert issue["resolution_attestation"]["scan_verified"]
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]


def test_explicit_false_positive_does_not_expire_like_temporary_skip(run_app_merge):
    state, plan, current, run = run_app_merge
    plan["skipped"][current["id"]].update(review_after=1, skipped_at_scan=1)
    run([current])
    assert current["id"] in plan["skipped"]
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )


def test_raw_reopen_is_still_present_before_canonical_reconciliation(
    run_app_merge, monkeypatch
):
    state, plan, current, run = run_app_merge
    saved = []
    monkeypatch.setattr(
        workflow,
        "save_state",
        lambda state, *args, **kwargs: saved.append(deepcopy(state)),
    )
    run([current])
    assert saved[0]["work_items"][current["id"]]["status"] == "open"
    assert saved[0]["work_items"][current["id"]]["reopen_count"] == 1
    assert state["work_items"][current["id"]]["status"] == "false_positive"
    assert not state["subjective_assessments"]["design_coherence"].get(
        "needs_review_refresh"
    )


def test_plan_read_failure_defaults_to_original_freshness_semantics(
    run_app_merge, monkeypatch
):
    from desloppify.app.commands.scan import plan_reconcile

    state, plan, current, run = run_app_merge

    def failed_load(path):
        raise ValueError("Synthetic unreadable plan")

    monkeypatch.setattr(plan_reconcile, "load_plan", failed_load)
    run([current])
    assert state["subjective_assessments"]["design_coherence"]["needs_review_refresh"]
