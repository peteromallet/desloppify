"""Tests for apply_completion clearing stale triage state (#263)."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from desloppify.app.commands.plan.triage.helpers import (
    apply_completion,
    undispositioned_triage_issue_ids,
)
from desloppify.engine._plan.constants import (
    TRIAGE_STAGE_IDS,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
)
from desloppify.engine._plan.policy.stale import is_triage_stale
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_REVIEW_POSTFLIGHT,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._work_queue.snapshot import build_queue_snapshot


def _state_with_review_issues(*ids: str) -> dict:
    issues = {}
    for fid in ids:
        issues[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review issue {fid}",
            "confidence": "medium",
            "tier": 2,
            "detail": {"dimension": "abstraction_fitness"},
        }
    return {
        "issues": issues,
        "scan_count": 5,
        "last_scan": "2026-01-01T00:00:00+00:00",
        "dimension_scores": {},
    }


def _plan_with_triage_and_workflow(*review_ids: str) -> dict:
    """Build a plan with triage stages, workflow items, and review IDs in queue."""
    plan = empty_plan()
    plan["queue_order"] = [
        *TRIAGE_STAGE_IDS,
        WORKFLOW_SCORE_CHECKPOINT_ID,
        WORKFLOW_CREATE_PLAN_ID,
        *review_ids,
    ]
    plan["epic_triage_meta"] = {
        "triage_recommended": True,
        "triage_stages": {
            "observe": {"confirmed_at": "2026-01-01T00:00:00+00:00"},
            "reflect": {"confirmed_at": "2026-01-01T00:00:00+00:00"},
            "organize": {"confirmed_at": "2026-01-01T00:00:00+00:00"},
            "enrich": {"confirmed_at": "2026-01-01T00:00:00+00:00"},
            "sense-check": {"confirmed_at": "2026-01-01T00:00:00+00:00"},
        },
        "stage_refresh_required": True,
        "stage_snapshot_hash": "old_hash",
    }
    return plan


def _make_services(state: dict) -> SimpleNamespace:
    """Build a minimal TriageServices-compatible mock."""
    saved_plans: list[dict] = []

    def command_runtime(_args):
        return SimpleNamespace(state=state)

    def save_plan(plan):
        saved_plans.append(dict(plan))

    def append_log_entry(plan, action, **kw):
        pass

    return SimpleNamespace(
        command_runtime=command_runtime,
        save_plan=save_plan,
        append_log_entry=append_log_entry,
        _saved_plans=saved_plans,
    )


class TestApplyCompletionClearsTriageState:
    """Verify apply_completion properly clears all triage-related flags (#263)."""

    def test_purges_workflow_ids(self):
        """Workflow items pointing to triage should be purged on completion."""
        state = _state_with_review_issues("r1", "r2")
        plan = _plan_with_triage_and_workflow("r1", "r2")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        order = plan["queue_order"]
        assert WORKFLOW_SCORE_CHECKPOINT_ID not in order
        assert WORKFLOW_CREATE_PLAN_ID not in order
        for sid in TRIAGE_STAGE_IDS:
            assert sid not in order
        # Review items should remain
        assert "r1" in order
        assert "r2" in order

    def test_clears_triage_recommended(self):
        """triage_recommended flag must be cleared on completion."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        meta = plan["epic_triage_meta"]
        assert "triage_recommended" not in meta

    def test_clears_stage_refresh_required(self):
        """stage_refresh_required flag must be cleared on completion."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        meta = plan["epic_triage_meta"]
        assert "stage_refresh_required" not in meta
        assert "stage_snapshot_hash" not in meta

    def test_triaged_ids_match_open_review_ids(self):
        """After completion, triaged_ids must contain all open review IDs."""
        state = _state_with_review_issues("r1", "r2", "r3")
        plan = _plan_with_triage_and_workflow("r1", "r2", "r3")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        triaged = set(plan["epic_triage_meta"]["triaged_ids"])
        assert triaged == {"r1", "r2", "r3"}

    def test_not_stale_after_completion(self):
        """is_triage_stale must return False immediately after completion."""
        state = _state_with_review_issues("r1", "r2")
        plan = _plan_with_triage_and_workflow("r1", "r2")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        assert not is_triage_stale(plan, state)

    def test_completion_uses_frozen_active_triage_issue_ids(self):
        """Completion should record the frozen triage set, not a drifted live state snapshot."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        plan["epic_triage_meta"]["active_triage_issue_ids"] = ["r1", "r2", "r3"]
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        assert set(plan["epic_triage_meta"]["triaged_ids"]) == {"r1", "r2", "r3"}

    def test_completion_clears_active_triage_tracking(self):
        """Successful completion must clear frozen active triage recovery metadata."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        plan["epic_triage_meta"]["active_triage_issue_ids"] = ["r1"]
        plan["epic_triage_meta"]["undispositioned_issue_ids"] = ["r1"]
        plan["epic_triage_meta"]["undispositioned_issue_count"] = 1
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        meta = plan["epic_triage_meta"]
        assert "active_triage_issue_ids" not in meta
        assert "undispositioned_issue_ids" not in meta
        assert "undispositioned_issue_count" not in meta

    def test_undispositioned_ignores_frozen_ids_that_are_no_longer_open(self):
        """Frozen triage IDs that vanished from state should not block recovery."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        plan["epic_triage_meta"]["active_triage_issue_ids"] = ["r1", "r2", "r3"]

        assert undispositioned_triage_issue_ids(plan, state) == ["r1"]

    def test_triage_stages_cleared(self):
        """triage_stages dict must be empty after completion."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        assert plan["epic_triage_meta"]["triage_stages"] == {}

    def test_last_triage_archived(self):
        """Completed stages should be archived in last_triage."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        last = plan["epic_triage_meta"]["last_triage"]
        assert "completed_at" in last
        assert "stages" in last
        assert "observe" in last["stages"]

    def test_completion_restores_postflight_scan_marker_for_current_scan(self):
        """Completing triage should not bounce the queue back to workflow::run-scan."""
        state = _state_with_review_issues("r1", "r2")
        state["issues"]["smells::test.py::duplicate_constant"] = {
            "status": "open",
            "detector": "smells",
            "file": "test.py",
            "summary": "Mechanical smell must remain backlog work",
            "confidence": "high",
            "tier": 1,
        }
        plan = _plan_with_triage_and_workflow("r1", "r2")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        assert plan["refresh_state"]["postflight_scan_completed_at_scan_count"] == 5
        snapshot = build_queue_snapshot(state, plan=plan)
        assert snapshot.phase == LIFECYCLE_PHASE_REVIEW_POSTFLIGHT
        assert [item["id"] for item in snapshot.execution_items] == ["r1", "r2"]
        assert [item["id"] for item in snapshot.backlog_items] == [
            "smells::test.py::duplicate_constant"
        ]

    def test_completion_does_not_forge_scan_marker_without_scan_history(self):
        """Plans loaded without a scan should still require an actual scan."""
        state = _state_with_review_issues("r1")
        state.pop("last_scan", None)
        plan = _plan_with_triage_and_workflow("r1")
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(args, plan, "Test strategy", services=services)

        assert "postflight_scan_completed_at_scan_count" not in plan.get("refresh_state", {})

    def test_confirm_existing_rewrites_strategy_summary_to_explicit_reuse_message(self, capsys):
        """Confirm-existing completion should not leave the stale prior strategy summary in place."""
        state = _state_with_review_issues("r1")
        plan = _plan_with_triage_and_workflow("r1")
        plan["epic_triage_meta"]["strategy_summary"] = "Legacy sequencing summary from an older triage run."
        services = _make_services(state)
        args = argparse.Namespace()

        apply_completion(
            args,
            plan,
            "same",
            services=services,
            completion_mode="confirm_existing",
            completion_note="Existing enriched manual clusters still cover [r1].",
        )

        meta = plan["epic_triage_meta"]
        assert meta["trigger"] == "confirm_existing"
        assert meta["last_completion_mode"] == "confirm_existing"
        assert meta["last_completion_note"] == "Existing enriched manual clusters still cover [r1]."
        assert meta["strategy_summary"].startswith(
            "Reused the existing enriched cluster plan after re-review"
        )
        assert "did not materialize" in capsys.readouterr().out

        last = meta["last_triage"]
        assert last["completion_mode"] == "confirm_existing"
        assert last["reused_existing_plan"] is True
        assert last["completion_note"] == "Existing enriched manual clusters still cover [r1]."
        assert last["previous_strategy_summary"] == "Legacy sequencing summary from an older triage run."
        assert last["strategy"] == meta["strategy_summary"]
