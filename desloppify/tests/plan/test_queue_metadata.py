"""Tests for queue metadata: auto_queue, deferred status, and explain."""

from __future__ import annotations

import pytest

from desloppify.base.registry import DETECTORS
from desloppify.engine._plan.cluster_semantics import (
    EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
    EXECUTION_POLICY_PLANNED_ONLY,
    EXECUTION_STATUS_ACTIVE,
    EXECUTION_STATUS_DEFERRED,
    EXECUTION_STATUS_REVIEW,
    VALID_EXECUTION_STATUSES,
    cluster_is_active,
    infer_cluster_execution_policy,
    infer_cluster_execution_status,
    normalize_cluster_semantics,
)
from desloppify.engine._plan.auto_cluster_sync_issue import (
    _auto_cluster_execution_status,
)
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_REVIEW_INITIAL,
    LIFECYCLE_PHASE_SCAN,
    LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT,
    LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT,
)
from desloppify.engine._work_queue.policy import (
    explain_queue,
)


# ── auto_queue registry tests ──────────────────────────────────────


def test_unused_has_auto_queue() -> None:
    assert DETECTORS["unused"].auto_queue is True


def test_logs_has_auto_queue() -> None:
    assert DETECTORS["logs"].auto_queue is True


def test_smells_not_auto_queued() -> None:
    """smells has needs_judgment=True which prevents auto-clustering,
    so auto_queue is False even though action_type is auto_fix."""
    assert DETECTORS["smells"].auto_queue is False


def test_rust_detectors_not_auto_queued() -> None:
    """Rust detectors should NOT auto-promote — they benefit from triage."""
    for name in ("rust_import_hygiene", "rust_feature_hygiene", "rust_doctest"):
        assert DETECTORS[name].auto_queue is False, f"{name} should not auto-queue"


def test_auto_queue_flows_through_execution_policy() -> None:
    """The auto_queue registry field should flow through infer_cluster_execution_policy,
    not through a separate predicate."""
    from desloppify.engine._plan.cluster_semantics import infer_cluster_execution_policy

    auto_cluster = {"auto": True, "action": ""}
    assert infer_cluster_execution_policy(auto_cluster, detector="unused") == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE
    assert infer_cluster_execution_policy(auto_cluster, detector="logs") == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE
    assert infer_cluster_execution_policy(auto_cluster, detector="smells") == EXECUTION_POLICY_PLANNED_ONLY
    assert infer_cluster_execution_policy(auto_cluster, detector="rust_import_hygiene") == EXECUTION_POLICY_PLANNED_ONLY


# ── Cluster execution policy with auto_queue ───────────────────────


def test_unused_cluster_gets_ephemeral_autopromote() -> None:
    cluster = {"auto": True, "action": "desloppify autofix unused --dry-run"}
    policy = infer_cluster_execution_policy(cluster, detector="unused")
    assert policy == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE


def test_rust_cluster_gets_planned_only_via_registry() -> None:
    """Known detector with auto_queue=False should be PLANNED_ONLY."""
    cluster = {"auto": True, "action": "desloppify autofix crate-imports --dry-run"}
    policy = infer_cluster_execution_policy(cluster, detector="rust_import_hygiene")
    assert policy == EXECUTION_POLICY_PLANNED_ONLY


def test_unknown_detector_falls_through_to_string_sniffing() -> None:
    """Old clusters without detector context should still use string sniffing."""
    cluster = {"auto": True, "action": "desloppify autofix something --dry-run"}
    # No detector → falls through to string sniffing
    policy = infer_cluster_execution_policy(cluster, detector="")
    assert policy == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE


def test_manual_planned_only_not_reclassified() -> None:
    """Manual cluster with explicit planned_only is never reclassified,
    even if it contains unused issues."""
    cluster = {
        "auto": False,
        "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
        "action": "desloppify autofix unused --dry-run",
    }
    policy = infer_cluster_execution_policy(cluster, detector="unused")
    assert policy == EXECUTION_POLICY_PLANNED_ONLY


# ── Cluster execution status ──────────────────────────────────────


def test_auto_cluster_status_unused_is_active() -> None:
    cluster = {"auto": True, "action": "desloppify autofix unused --dry-run"}
    status = _auto_cluster_execution_status(cluster, detector="unused")
    assert status == EXECUTION_STATUS_ACTIVE


def test_auto_cluster_status_rust_is_review() -> None:
    """Rust detectors should get REVIEW, not ACTIVE."""
    cluster = {"auto": True, "action": "desloppify autofix crate-imports --dry-run"}
    status = _auto_cluster_execution_status(cluster, detector="rust_import_hygiene")
    assert status == EXECUTION_STATUS_REVIEW


# ── Deferred execution status ─────────────────────────────────────


def test_deferred_is_valid_execution_status() -> None:
    assert EXECUTION_STATUS_DEFERRED in VALID_EXECUTION_STATUSES


def test_cluster_is_active_false_for_deferred() -> None:
    cluster = {"execution_status": EXECUTION_STATUS_DEFERRED}
    assert cluster_is_active(cluster) is False


def test_infer_deferred_status() -> None:
    cluster = {"execution_status": "deferred"}
    assert infer_cluster_execution_status(cluster) == EXECUTION_STATUS_DEFERRED


# ── Queue eviction ────────────────────────────────────────────────


def test_demoted_cluster_evicted_from_queue_order() -> None:
    """Issue IDs from a demoted auto-cluster should be evicted even after
    sync rewrites the cluster to planned_only/review (the realistic case)."""
    from desloppify.engine._plan.auto_cluster import (
        _evictable_auto_cluster_issue_ids,
    )

    # Realistic post-sync state: Rust cluster was rewritten to review/planned_only
    # by _sync_auto_clusters BEFORE eviction runs.
    plan = {
        "clusters": {
            "auto/rust-imports": {
                "auto": True,
                "issue_ids": ["r1", "r2"],
                "execution_status": EXECUTION_STATUS_REVIEW,
                "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
            },
        },
        "queue_order": ["r1", "r2", "u1"],
    }
    evicted = _evictable_auto_cluster_issue_ids(plan)
    assert evicted == {"r1", "r2"}


def test_active_cluster_not_evicted() -> None:
    from desloppify.engine._plan.auto_cluster import (
        _evictable_auto_cluster_issue_ids,
    )

    plan = {
        "clusters": {
            "auto/unused": {
                "auto": True,
                "issue_ids": ["u1", "u2"],
                "execution_status": EXECUTION_STATUS_ACTIVE,
                "execution_policy": EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
            },
        },
    }
    evicted = _evictable_auto_cluster_issue_ids(plan)
    assert evicted == set()


def test_subjective_cluster_not_evicted() -> None:
    """Subjective review clusters should not be evicted — their lifecycle
    is managed by sync_subjective_dimensions, not by auto-cluster eviction."""
    from desloppify.engine._plan.auto_cluster import (
        _evictable_auto_cluster_issue_ids,
    )

    plan = {
        "clusters": {
            "auto/initial-review": {
                "auto": True,
                "issue_ids": ["subjective::design_coherence"],
                "execution_status": EXECUTION_STATUS_REVIEW,
                "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
            },
        },
    }
    evicted = _evictable_auto_cluster_issue_ids(plan)
    assert evicted == set()


def test_cross_cluster_move_not_evicted() -> None:
    """An issue ID owned by both an active and inactive cluster stays."""
    from desloppify.engine._plan.auto_cluster import (
        _evictable_auto_cluster_issue_ids,
    )

    plan = {
        "clusters": {
            "auto/old": {
                "auto": True,
                "issue_ids": ["shared_id", "old_only"],
                "execution_status": EXECUTION_STATUS_REVIEW,
                "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
            },
            "auto/active": {
                "auto": True,
                "issue_ids": ["shared_id"],
                "execution_status": EXECUTION_STATUS_ACTIVE,
                "execution_policy": EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
            },
        },
    }
    evicted = _evictable_auto_cluster_issue_ids(plan)
    # shared_id is in an active cluster, so only old_only gets evicted.
    assert evicted == {"old_only"}


def test_manual_cluster_member_not_evicted_from_inactive_auto_cluster() -> None:
    from desloppify.engine._plan.auto_cluster import (
        _evictable_auto_cluster_issue_ids,
    )

    plan = {
        "clusters": {
            "auto/exports": {
                "auto": True,
                "issue_ids": ["u1", "u2"],
                "execution_status": EXECUTION_STATUS_REVIEW,
                "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
            },
            "manual/my-task": {
                "auto": False,
                "issue_ids": ["u1"],
                "execution_status": EXECUTION_STATUS_ACTIVE,
            },
        },
    }
    evicted = _evictable_auto_cluster_issue_ids(plan)
    assert evicted == {"u2"}


# ── explain_queue ──────────────────────────────────────────────────


def _make_snapshot(**overrides):
    """Build a minimal QueueSnapshot for testing."""
    from desloppify.engine._work_queue.snapshot import QueueSnapshot

    defaults = {
        "phase": "execute",
        "all_objective_items": (),
        "all_initial_review_items": (),
        "all_postflight_assessment_items": (),
        "all_postflight_review_items": (),
        "all_scan_items": (),
        "all_postflight_workflow_items": (),
        "all_postflight_triage_items": (),
        "execution_items": (),
        "backlog_items": (),
        "objective_in_scope_count": 0,
        "planned_objective_count": 0,
        "objective_execution_count": 0,
        "objective_backlog_count": 0,
        "subjective_initial_count": 0,
        "assessment_postflight_count": 0,
        "subjective_postflight_count": 0,
        "workflow_postflight_count": 0,
        "triage_pending_count": 0,
        "has_unplanned_objective_blockers": False,
    }
    defaults.update(overrides)
    return QueueSnapshot(**defaults)


def test_explain_queue_execute_phase() -> None:
    snapshot = _make_snapshot(
        phase="execute",
        execution_items=({"id": "a"}, {"id": "b"}),
        backlog_items=({"id": "c"},),
        objective_in_scope_count=3,
        objective_backlog_count=1,
    )
    plan = {
        "clusters": {
            "auto/unused": {
                "execution_status": "active",
                "execution_policy": EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
            },
            "auto/naming": {
                "execution_status": "active",
                "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
            },
        },
    }
    text = explain_queue(snapshot, plan)
    assert "Mode: execute" in text
    assert "Auto-queued: 1" in text
    # Should show the persisted cluster name, not the registry detector name.
    assert "auto/unused" in text
    assert "Triage-promoted: 1" in text
    assert "Backlog: 1 objective" in text
    # Cluster counts are plan-wide, labeled explicitly.
    assert "all scopes" in text


def test_explain_shows_only_active_auto_clusters() -> None:
    """If only unused is active, logs should not appear in the explanation."""
    snapshot = _make_snapshot(phase="execute", execution_items=({"id": "a"},))
    plan = {
        "clusters": {
            "auto/unused": {
                "execution_status": "active",
                "execution_policy": EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
            },
            "auto/logs": {
                "execution_status": "review",
                "execution_policy": EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
            },
        },
    }
    text = explain_queue(snapshot, plan)
    assert "auto/unused" in text
    assert "auto/logs" not in text


def test_explain_queue_review_initial_phase() -> None:
    snapshot = _make_snapshot(
        phase=LIFECYCLE_PHASE_REVIEW_INITIAL,
        objective_in_scope_count=10,
    )
    text = explain_queue(snapshot, None)
    assert "Mode: plan" in text
    assert "Reviewing code quality dimensions" in text
    assert "10 objective items" in text


def test_explain_queue_workflow_postflight() -> None:
    snapshot = _make_snapshot(
        phase=LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT,
        planned_objective_count=14,
    )
    text = explain_queue(snapshot, None)
    assert "Mode: plan" in text
    assert "Processing a planning step" in text
    assert "14 work items available after" in text


def test_explain_queue_triage_postflight() -> None:
    snapshot = _make_snapshot(
        phase=LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT,
        planned_objective_count=14,
    )
    text = explain_queue(snapshot, None)
    assert "Mode: plan" in text
    assert "Analyzing and prioritizing issues" in text
    assert "14 work items available after" in text


def test_explain_queue_scan_phase() -> None:
    snapshot = _make_snapshot(phase=LIFECYCLE_PHASE_SCAN)
    text = explain_queue(snapshot, None)
    assert "Mode: plan" in text
    assert "desloppify scan" in text


# ── Stale persisted phase uses item-driven inference ───────────────


def test_markdown_output_includes_explanation() -> None:
    """--format md should include the queue_explanation when present."""
    from desloppify.app.commands.next.output import render_markdown_for_command

    items = [{"kind": "issue", "confidence": "high", "summary": "test", "primary_command": ""}]
    explanation = "  Mode: execute\n  Items in queue: 1"
    md = render_markdown_for_command(items, command="next", queue_explanation=explanation)
    assert "## Queue context" in md
    assert "Mode: execute" in md
    assert "| issue |" in md

    md_no_explain = render_markdown_for_command(items, command="next")
    assert "Queue context" not in md_no_explain


def test_stale_persisted_phase_falls_back() -> None:
    """If persisted phase says execute but no execution items exist,
    the snapshot should infer a different phase from items."""
    from desloppify.engine._work_queue.snapshot import build_queue_snapshot

    state = {
        "work_items": {},
        "dimension_scores": {},
        "scan_path": "/tmp/test",
    }
    plan = {
        "refresh_state": {"lifecycle_phase": "execute"},
        "plan_start_scores": {"strict": 50.0},
    }
    snapshot = build_queue_snapshot(state, plan=plan)
    # No execution items means the snapshot should not stay in execute mode.
    assert snapshot.phase != "execute"


# ── backlog and next share preamble ────────────────────────────────


def test_explain_with_plan_none_still_works() -> None:
    """explain_queue with plan=None should not crash, just omit cluster counts."""
    snapshot = _make_snapshot(
        phase="execute",
        execution_items=({"id": "a"},),
        backlog_items=({"id": "b"}, {"id": "c"}),
        objective_in_scope_count=3,
    )
    text = explain_queue(snapshot, None)
    assert "Mode: execute" in text
    assert "Visible items: 1" in text
    # No auto/triage lines when plan is None.
    assert "Auto-queued" not in text
    assert "Triage-promoted" not in text


def test_backlog_explain_gets_real_plan() -> None:
    """The backlog flow must pass the real plan to explain_queue,
    not the plan_data (which is None for backlog).

    This tests the fix: _write_next_payload receives explain_plan
    separately from plan_data so backlog can show cluster counts.
    """
    snapshot = _make_snapshot(
        phase="execute",
        execution_items=({"id": "a"},),
    )
    plan = {
        "clusters": {
            "auto/unused": {
                "execution_status": "active",
                "execution_policy": EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
            },
        },
    }
    # Simulate backlog: plan_data=None but explain_plan=real plan.
    text = explain_queue(snapshot, plan)
    assert "Auto-queued: 1" in text
    # Contrast: plan_data=None loses cluster info.
    text_no_plan = explain_queue(snapshot, None)
    assert "Auto-queued" not in text_no_plan
