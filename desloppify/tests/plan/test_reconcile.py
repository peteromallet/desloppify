"""Tests for plan reconciliation — supersede, prune, cluster desync fix."""

from __future__ import annotations

from desloppify.engine._plan.operations.cluster import add_to_cluster, create_cluster
from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import empty_plan, ensure_plan_defaults

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_with_queue(*ids: str) -> dict:
    plan = empty_plan()
    plan["queue_order"] = list(ids)
    return plan


def _state_with_issues(*ids: str, status: str = "open") -> dict:
    issues = {}
    for fid in ids:
        issues[fid] = {
            "id": fid,
            "status": status,
            "detector": "test",
            "file": "test.py",
            "tier": 1,
            "confidence": "high",
            "summary": f"Issue {fid}",
        }
    return {"issues": issues, "scan_count": 5}


# ---------------------------------------------------------------------------
# _supersede_id clears override cluster ref
# ---------------------------------------------------------------------------

def test_supersede_clears_override_cluster_ref():
    """When a issue is superseded, its override cluster ref should be cleared."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)

    # Create a cluster and add issue "a" to it
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])

    # Verify override has cluster ref
    assert plan["overrides"]["a"]["cluster"] == "my-cluster"

    # State where "a" is gone (not present = not alive)
    state = _state_with_issues("b")

    result = reconcile_plan_after_scan(plan, state)
    assert "a" in result.superseded

    # Override cluster ref should be cleared
    override = plan["overrides"].get("a")
    assert override is not None
    assert override.get("cluster") is None


def test_supersede_preserves_note_in_override():
    """Superseding should preserve the note in the override (for history)."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)

    # Add an override with a note
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "note": "important context",
        "cluster": None,
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    state = _state_with_issues()  # "a" is gone
    reconcile_plan_after_scan(plan, state)

    # Superseded entry should have the note
    assert plan["superseded"]["a"]["note"] == "important context"


def test_supersede_removes_from_cluster_issue_ids():
    """Superseded issue should be removed from cluster issue_ids."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)

    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a", "b"])

    # "a" disappears
    state = _state_with_issues("b")
    reconcile_plan_after_scan(plan, state)

    assert "a" not in plan["clusters"]["my-cluster"]["issue_ids"]
    assert "b" in plan["clusters"]["my-cluster"]["issue_ids"]


def test_reconcile_clears_focus_when_focused_cluster_becomes_empty():
    """Reconcile should exit focus mode when the focused cluster loses its last issue."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])
    plan["active_cluster"] = "my-cluster"

    state = _state_with_issues()  # "a" disappeared
    result = reconcile_plan_after_scan(plan, state)

    assert "a" in result.superseded
    assert plan["clusters"]["my-cluster"]["issue_ids"] == []
    assert plan["active_cluster"] is None


# ---------------------------------------------------------------------------
# Reconcile logs execution
# ---------------------------------------------------------------------------

def test_reconcile_logs_execution_entry():
    """Reconciliation should append a log entry when changes are made."""
    plan = _plan_with_queue("gone")
    ensure_plan_defaults(plan)
    state = _state_with_issues("alive")

    result = reconcile_plan_after_scan(plan, state)
    assert result.changes > 0

    log = plan.get("execution_log", [])
    assert len(log) >= 1
    entry = log[-1]
    assert entry["action"] == "reconcile"
    assert entry["actor"] == "system"
    assert "superseded_count" in entry["detail"]


def test_reconcile_no_log_when_no_changes():
    """No log entry when reconciliation makes no changes."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)
    state = _state_with_issues("a")  # "a" still alive

    result = reconcile_plan_after_scan(plan, state)
    assert result.changes == 0

    log = plan.get("execution_log", [])
    reconcile_entries = [e for e in log if e["action"] == "reconcile"]
    assert len(reconcile_entries) == 0


def test_reconcile_prunes_existing_superseded_references():
    """Already-superseded IDs should not linger in queue_order or clusters."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)
    plan["superseded"]["a"] = {
        "original_id": "a",
        "status": "superseded",
        "superseded_at": "2026-01-01T00:00:00+00:00",
    }
    plan["promoted_ids"] = ["a"]
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a", "b"])

    result = reconcile_plan_after_scan(plan, _state_with_issues("b"))

    assert result.changes > 0
    assert "a" not in plan["queue_order"]
    assert "a" not in plan["promoted_ids"]
    assert "a" not in plan["clusters"]["my-cluster"]["issue_ids"]


# ---------------------------------------------------------------------------
# Active clusters completed when all items resolved
# ---------------------------------------------------------------------------

def test_reconcile_marks_active_cluster_done_when_all_items_resolved():
    """An active cluster whose items are all fixed/wontfix should become done."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a", "b"])
    plan["clusters"]["my-cluster"]["execution_status"] = "active"

    # Both items are resolved in state
    state = _state_with_issues("a", "b", status="fixed")

    result = reconcile_plan_after_scan(plan, state)

    assert "my-cluster" in result.clusters_completed
    assert plan["clusters"]["my-cluster"]["execution_status"] == "done"


def test_reconcile_leaves_active_cluster_when_items_still_open():
    """An active cluster with open items should stay active."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a", "b"])
    plan["clusters"]["my-cluster"]["execution_status"] = "active"

    # "a" is fixed but "b" is still open
    state = _state_with_issues("b")
    state["issues"]["a"] = {
        "id": "a", "status": "fixed", "detector": "test",
        "file": "test.py", "tier": 1, "confidence": "high", "summary": "Issue a",
    }

    result = reconcile_plan_after_scan(plan, state)

    assert "my-cluster" not in result.clusters_completed
    assert plan["clusters"]["my-cluster"]["execution_status"] == "active"
