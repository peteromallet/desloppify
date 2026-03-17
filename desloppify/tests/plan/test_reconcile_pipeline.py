"""Direct tests for the shared reconcile pipeline and queue ownership rules.

Covers the gate matrix from centralize-postflight-pipeline.md:
- Boundary detection (fresh, mid-cycle, queue-clear)
- Phase isolation (promoted vs unpromoted clusters)
- Phantom resurrection / stuck queue guards
- Second reconcile is no-op (idempotency)
- Sentinel helper encapsulation
- workflow_injected_ids aggregation
"""

from __future__ import annotations

from desloppify.engine._plan.auto_cluster import auto_cluster_issues
from desloppify.engine._plan.constants import (
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_CREATE_PLAN_ID,
)
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync import live_planned_queue_empty, reconcile_plan
from desloppify.engine._plan.sync.workflow import clear_communicate_score_sentinel, clear_score_communicated_sentinel
from desloppify.engine._work_queue.snapshot import (
    PHASE_ASSESSMENT_POSTFLIGHT,
    PHASE_EXECUTE,
    PHASE_REVIEW_POSTFLIGHT,
    PHASE_TRIAGE_POSTFLIGHT,
    PHASE_WORKFLOW_POSTFLIGHT,
    PHASE_SCAN,
    build_queue_snapshot,
)


def _issue(issue_id: str, detector: str = "unused") -> dict:
    return {
        "id": issue_id,
        "detector": detector,
        "status": "open",
        "file": "src/app.py",
        "tier": 1,
        "confidence": "high",
        "summary": issue_id,
        "detail": {},
    }


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------


def test_live_planned_queue_empty_uses_queue_order_only() -> None:
    """Overrides/clusters in plan do NOT expand the live queue."""
    plan = empty_plan()
    plan["clusters"] = {
        "manual/review": {
            "name": "manual/review",
            "issue_ids": ["unused::a"],
            "execution_status": "active",
        }
    }
    plan["overrides"] = {
        "unused::a": {
            "issue_id": "unused::a",
            "cluster": "manual/review",
        }
    }

    assert live_planned_queue_empty(plan) is True


def test_live_planned_queue_not_empty_with_substantive_item() -> None:
    plan = empty_plan()
    plan["queue_order"] = ["unused::a"]

    assert live_planned_queue_empty(plan) is False


def test_live_planned_queue_empty_ignores_synthetic_items() -> None:
    plan = empty_plan()
    plan["queue_order"] = [
        "workflow::communicate-score",
        "subjective::naming",
        "triage::stage-1",
    ]

    assert live_planned_queue_empty(plan) is True


def test_live_planned_queue_empty_ignores_skipped_items() -> None:
    plan = empty_plan()
    plan["queue_order"] = ["unused::a"]
    plan["skipped"] = {"unused::a": {"reason": "manual"}}

    assert live_planned_queue_empty(plan) is True


def test_reconcile_plan_noops_when_live_queue_not_empty() -> None:
    """Mid-cycle: pipeline is a no-op, no gates fire."""
    state = {"issues": {"unused::a": _issue("unused::a")}}
    plan = empty_plan()
    plan["queue_order"] = ["unused::a"]
    plan["plan_start_scores"] = {"strict": 80.0}

    result = reconcile_plan(plan, state, target_strict=95.0)

    assert result.dirty is False
    assert result.workflow_injected_ids == []
    assert plan["queue_order"] == ["unused::a"]


def test_reconcile_plan_second_call_is_noop() -> None:
    """Idempotency: calling reconcile_plan twice at the same boundary
    produces no additional mutations."""
    state = {"issues": {}}
    plan = empty_plan()

    reconcile_plan(plan, state, target_strict=95.0)
    queue_after_first = list(plan.get("queue_order", []))
    log_after_first = list(plan.get("log", []))

    result2 = reconcile_plan(plan, state, target_strict=95.0)

    assert plan.get("queue_order", []) == queue_after_first
    # Log may have lifecycle entries but should not grow on second call
    assert len(plan.get("log", [])) == len(log_after_first)
    # Second result should show no new dirty changes beyond lifecycle
    # (lifecycle is always computed but should match, so not changed)
    assert result2.auto_cluster_changes == 0
    assert result2.workflow_injected_ids == []


def test_reconcile_plan_holds_workflow_until_current_scan_subjective_review_completes() -> None:
    """Postflight review must run before communicate-score/create-plan."""
    state = {
        "issues": {"unused::a": _issue("unused::a")},
        "scan_count": 19,
        "dimension_scores": {
            "Naming quality": {
                "score": 82.0,
                "strict": 82.0,
                "failing": 0,
                "checks": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            }
        },
        "subjective_assessments": {
            "naming_quality": {"score": 82.0, "placeholder": False}
        },
    }
    plan = empty_plan()
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 19}

    result = reconcile_plan(plan, state, target_strict=95.0)

    assert "subjective::naming_quality" in plan["queue_order"]
    assert WORKFLOW_COMMUNICATE_SCORE_ID not in plan["queue_order"]
    assert WORKFLOW_CREATE_PLAN_ID not in plan["queue_order"]
    assert result.workflow_injected_ids == []

    plan["queue_order"] = [
        issue_id
        for issue_id in plan["queue_order"]
        if issue_id != "subjective::naming_quality"
    ]
    plan["refresh_state"]["subjective_review_completed_at_scan_count"] = 19

    result = reconcile_plan(plan, state, target_strict=95.0)

    assert WORKFLOW_COMMUNICATE_SCORE_ID in plan["queue_order"]
    assert WORKFLOW_CREATE_PLAN_ID in plan["queue_order"]
    assert result.workflow_injected_ids == [
        WORKFLOW_COMMUNICATE_SCORE_ID,
        WORKFLOW_CREATE_PLAN_ID,
    ]


# ---------------------------------------------------------------------------
# Mid-cycle auto-clustering guard
# ---------------------------------------------------------------------------


def test_auto_cluster_issues_is_noop_mid_cycle() -> None:
    state = {
        "issues": {
            "unused::a": _issue("unused::a"),
            "unused::b": _issue("unused::b"),
        }
    }
    plan = empty_plan()
    plan["queue_order"] = ["unused::a"]
    plan["plan_start_scores"] = {"strict": 80.0}

    changes = auto_cluster_issues(plan, state)

    assert changes == 0
    assert plan["clusters"] == {}


# ---------------------------------------------------------------------------
# Phase isolation: promoted vs unpromoted clusters
# ---------------------------------------------------------------------------


def test_queue_snapshot_executes_review_items_promoted_into_active_cluster() -> None:
    """Active cluster with items in queue_order → EXECUTE phase."""
    state = {
        "issues": {
            "review::a": _issue("review::a", detector="review"),
        }
    }
    plan = empty_plan()
    plan["queue_order"] = ["review::a"]
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["epic_triage_meta"] = {
        "triaged_ids": ["review::a"],
        "issue_snapshot_hash": "stable",
    }
    plan["clusters"] = {
        "epic/review": {
            "name": "epic/review",
            "issue_ids": ["review::a"],
            "execution_status": "active",
        }
    }

    snapshot = build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == PHASE_EXECUTE
    assert [item["id"] for item in snapshot.execution_items] == ["review::a"]


def test_queue_snapshot_keeps_unpromoted_review_cluster_in_postflight() -> None:
    """Review cluster (execution_status: review) → postflight, not execute."""
    state = {
        "issues": {
            "review::a": _issue("review::a", detector="review"),
        }
    }
    plan = empty_plan()
    plan["epic_triage_meta"] = {
        "triaged_ids": ["review::a"],
        "issue_snapshot_hash": "stable",
    }
    plan["refresh_state"] = {"postflight_scan_completed_at_scan_count": 1}
    plan["clusters"] = {
        "manual/review": {
            "name": "manual/review",
            "issue_ids": ["review::a"],
            "execution_status": "review",
        }
    }

    snapshot = build_queue_snapshot(state, plan=plan)

    assert live_planned_queue_empty(plan) is True
    assert snapshot.phase == PHASE_REVIEW_POSTFLIGHT
    assert [item["id"] for item in snapshot.execution_items] == ["review::a"]


def test_phase_isolation_mixed_objective_and_unpromoted_review() -> None:
    """Objective work in queue + unpromoted review findings → only objective
    items in execution, review stays postflight."""
    state = {
        "issues": {
            "unused::obj": _issue("unused::obj"),
            "review::rev": _issue("review::rev", detector="review"),
        }
    }
    plan = empty_plan()
    plan["queue_order"] = ["unused::obj"]
    plan["plan_start_scores"] = {"strict": 80.0}
    plan["epic_triage_meta"] = {
        "triaged_ids": ["review::rev"],
        "issue_snapshot_hash": "stable",
    }
    plan["clusters"] = {
        "manual/review": {
            "name": "manual/review",
            "issue_ids": ["review::rev"],
            "execution_status": "review",
        }
    }

    snapshot = build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == PHASE_EXECUTE
    execution_ids = [item["id"] for item in snapshot.execution_items]
    assert "unused::obj" in execution_ids
    assert "review::rev" not in execution_ids


def test_postflight_phase_stays_exclusive_when_new_execute_items_exist() -> None:
    """Fresh execute work discovered during postflight stays backlog-only until postflight ends."""
    state = {
        "issues": {
            "unused::obj": _issue("unused::obj"),
        },
        "dimension_scores": {
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
        },
        "subjective_assessments": {
            "naming_quality": {"score": 70.0, "needs_review_refresh": True},
        },
    }
    plan = empty_plan()
    plan["queue_order"] = [
        "unused::obj",
        "workflow::communicate-score",
        "triage::observe",
    ]
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "lifecycle_phase": "review",
    }
    plan["plan_start_scores"] = {"strict": 70.0, "overall": 70.0}

    snapshot = build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == PHASE_ASSESSMENT_POSTFLIGHT
    assert [item["id"] for item in snapshot.execution_items] == ["subjective::naming_quality"]
    assert "unused::obj" in [item["id"] for item in snapshot.backlog_items]


def test_postflight_execute_items_reappear_after_postflight_drains() -> None:
    """Once postflight items are done, queued execute work becomes live again."""
    state = {
        "issues": {
            "unused::obj": _issue("unused::obj"),
        },
    }
    plan = empty_plan()
    plan["queue_order"] = ["unused::obj"]
    plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "lifecycle_phase": "workflow",
    }

    snapshot = build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == PHASE_EXECUTE
    assert [item["id"] for item in snapshot.execution_items] == ["unused::obj"]


def test_sticky_postflight_advances_through_remaining_subphases() -> None:
    """Sticky postflight respects the fixed ordered sequence while active."""
    state = {"issues": {}}

    workflow_plan = empty_plan()
    workflow_plan["queue_order"] = ["workflow::communicate-score", "triage::observe"]
    workflow_plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "lifecycle_phase": "workflow",
    }
    workflow_snapshot = build_queue_snapshot(state, plan=workflow_plan)
    assert workflow_snapshot.phase == PHASE_WORKFLOW_POSTFLIGHT

    triage_plan = empty_plan()
    triage_plan["queue_order"] = ["triage::observe"]
    triage_plan["refresh_state"] = {
        "postflight_scan_completed_at_scan_count": 5,
        "lifecycle_phase": "triage",
    }
    triage_snapshot = build_queue_snapshot(state, plan=triage_plan)
    assert triage_snapshot.phase == PHASE_TRIAGE_POSTFLIGHT


# ---------------------------------------------------------------------------
# Phantom resurrection guard
# ---------------------------------------------------------------------------


def test_phantom_resurrection_guard_overrides_not_in_queue() -> None:
    """Items in overrides/clusters but NOT in queue_order must NOT be treated
    as live queue work."""
    plan = empty_plan()
    plan["queue_order"] = []  # explicitly empty
    plan["overrides"] = {
        "unused::ghost": {
            "issue_id": "unused::ghost",
            "cluster": "manual/ghost",
        }
    }
    plan["clusters"] = {
        "manual/ghost": {
            "name": "manual/ghost",
            "issue_ids": ["unused::ghost"],
            "execution_status": "active",
        }
    }

    assert live_planned_queue_empty(plan) is True

    state = {"issues": {"unused::ghost": _issue("unused::ghost")}}
    snapshot = build_queue_snapshot(state, plan=plan)

    # Phase should NOT be EXECUTE — queue is empty
    assert snapshot.phase != PHASE_EXECUTE or not any(
        item["id"] == "unused::ghost" for item in snapshot.execution_items
        if not item.get("kind") == "cluster"
    )


# ---------------------------------------------------------------------------
# Stuck queue guard
# ---------------------------------------------------------------------------


def test_stuck_queue_guard_removed_item_stays_gone() -> None:
    """Item removed from queue_order but still in overrides/clusters is NOT
    resurrected into the live queue."""
    plan = empty_plan()
    plan["queue_order"] = ["unused::kept"]
    plan["overrides"] = {
        "unused::removed": {
            "issue_id": "unused::removed",
            "cluster": "manual/old",
        }
    }
    plan["clusters"] = {
        "manual/old": {
            "name": "manual/old",
            "issue_ids": ["unused::removed"],
            "execution_status": "active",
        }
    }

    assert live_planned_queue_empty(plan) is False

    state = {
        "issues": {
            "unused::kept": _issue("unused::kept"),
            "unused::removed": _issue("unused::removed"),
        }
    }
    snapshot = build_queue_snapshot(state, plan=plan)

    execution_ids = {item["id"] for item in snapshot.execution_items}
    assert "unused::kept" in execution_ids
    # The removed item should not reappear in execution
    assert "unused::removed" not in execution_ids


# ---------------------------------------------------------------------------
# Sentinel helper
# ---------------------------------------------------------------------------


def test_clear_score_communicated_sentinel() -> None:
    """Helper removes the sentinel key; missing key is a no-op."""
    plan = empty_plan()
    plan["previous_plan_start_scores"] = {"strict": 80.0}

    clear_score_communicated_sentinel(plan)
    assert "previous_plan_start_scores" not in plan

    # Second call is a no-op (no KeyError)
    clear_score_communicated_sentinel(plan)
    assert "previous_plan_start_scores" not in plan


def test_clear_communicate_score_sentinel() -> None:
    """Helper removes the resolved-this-cycle sentinel; missing key is a no-op."""
    plan = empty_plan()
    plan["communicate_score_resolved_this_cycle"] = True

    clear_communicate_score_sentinel(plan)
    assert "communicate_score_resolved_this_cycle" not in plan

    clear_communicate_score_sentinel(plan)
    assert "communicate_score_resolved_this_cycle" not in plan


def test_sentinel_blocks_communicate_score_reinjection() -> None:
    """When the sentinel is set, communicate-score does not re-inject."""
    from desloppify.engine._plan.sync.workflow import sync_communicate_score_needed

    plan = empty_plan()
    plan["previous_plan_start_scores"] = {"strict": 80.0}
    state: dict = {"issues": {}}

    result = sync_communicate_score_needed(plan, state)
    assert not result.changes

    # After clearing sentinel, gate may fire
    clear_score_communicated_sentinel(plan)
    assert "previous_plan_start_scores" not in plan


# ---------------------------------------------------------------------------
# workflow_injected_ids aggregation
# ---------------------------------------------------------------------------


def test_workflow_injected_ids_aggregates_both_gates() -> None:
    from desloppify.engine._plan.constants import QueueSyncResult
    from desloppify.engine._plan.sync.pipeline import ReconcileResult

    result = ReconcileResult(
        communicate_score=QueueSyncResult(
            injected=[WORKFLOW_COMMUNICATE_SCORE_ID],
        ),
        create_plan=QueueSyncResult(
            injected=[WORKFLOW_CREATE_PLAN_ID],
        ),
    )

    ids = result.workflow_injected_ids
    assert WORKFLOW_COMMUNICATE_SCORE_ID in ids
    assert WORKFLOW_CREATE_PLAN_ID in ids
    assert len(ids) == 2


def test_workflow_injected_ids_empty_when_no_gates_fire() -> None:
    from desloppify.engine._plan.sync.pipeline import ReconcileResult

    result = ReconcileResult()
    assert result.workflow_injected_ids == []


# ---------------------------------------------------------------------------
# Lifecycle does not persist when phase unchanged
# ---------------------------------------------------------------------------


def test_lifecycle_does_not_persist_when_unchanged() -> None:
    """If the resolved phase matches the current lifecycle_phase value,
    lifecycle_phase_changed should be False."""
    state = {"issues": {}}
    plan = empty_plan()

    # First call sets lifecycle
    result1 = reconcile_plan(plan, state, target_strict=95.0)
    assert result1.lifecycle_phase_changed is True

    # Second call at same boundary — phase unchanged
    result2 = reconcile_plan(plan, state, target_strict=95.0)
    assert result2.lifecycle_phase == result1.lifecycle_phase
    assert result2.lifecycle_phase_changed is False


# ---------------------------------------------------------------------------
# Pipeline does not touch scan-specific state
# ---------------------------------------------------------------------------


def test_pipeline_does_not_seed_plan_start_scores() -> None:
    """reconcile_plan never writes plan_start_scores — that's scan-specific."""
    state = {"issues": {}}
    plan = empty_plan()
    assert not plan.get("plan_start_scores")

    reconcile_plan(plan, state, target_strict=95.0)

    # Should still be empty/falsy — pipeline doesn't seed it
    assert not plan.get("plan_start_scores")


def test_pipeline_does_not_mark_postflight_scan_complete() -> None:
    """reconcile_plan never sets postflight_scan_completed_at_scan_count."""
    state = {"issues": {}}
    plan = empty_plan()

    reconcile_plan(plan, state, target_strict=95.0)

    refresh = plan.get("refresh_state", {})
    assert "postflight_scan_completed_at_scan_count" not in refresh


# ---------------------------------------------------------------------------
# Fresh boundary behavior
# ---------------------------------------------------------------------------


def test_fresh_boundary_empty_state_resolves_scan_phase() -> None:
    """Empty state + no plan_start_scores → fresh boundary → scan phase."""
    state = {"issues": {}}
    plan = empty_plan()

    snapshot = build_queue_snapshot(state, plan=plan)

    assert snapshot.phase == PHASE_SCAN
