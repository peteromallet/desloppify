"""Tests for plan reconciliation — supersede, prune, cluster desync fix."""

from __future__ import annotations

from copy import deepcopy

import pytest

from desloppify.engine._plan.operations.cluster import add_to_cluster, create_cluster
from desloppify.engine._plan.operations.skip import skip_items
from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import empty_plan, ensure_plan_defaults
from desloppify.engine._state.merge_issues import upsert_issues

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


def test_reconcile_supersedes_resolved_action_references():
    """Resolved IDs should not linger as queue/promoted/cluster work."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)
    plan["promoted_ids"] = ["a", "b"]
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a", "b"])

    state = _state_with_issues("b")
    state["issues"]["a"] = {
        "id": "a",
        "status": "fixed",
        "detector": "test",
        "file": "test.py",
        "tier": 1,
        "confidence": "high",
        "summary": "Issue a",
    }

    result = reconcile_plan_after_scan(plan, state)

    assert "a" in result.superseded
    assert "a" not in plan["queue_order"]
    assert "a" not in plan["promoted_ids"]
    assert "a" not in plan["clusters"]["my-cluster"]["issue_ids"]
    assert "b" in plan["queue_order"]
    assert "b" in plan["promoted_ids"]


@pytest.mark.parametrize("kind,status", [("false_positive", "false_positive"), ("permanent", "wontfix")])
@pytest.mark.parametrize("cluster_status", ["active", "review", "deferred", "done"])
@pytest.mark.parametrize("auto", [False, True])
def test_repeated_scans_preserve_durable_skips(kind, status, cluster_status, auto):
    """Resolved cluster references must not erase deliberate dispositions."""
    plan = _plan_with_queue("a", "b")
    create_cluster(plan, "reviewed")
    add_to_cluster(plan, "reviewed", ["a", "b"])
    cluster = plan["clusters"]["reviewed"]
    cluster.update(auto=auto, execution_status=cluster_status)
    cluster["action_steps"] = [{"title": "Review remaining work", "issue_refs": ["a", "b"]}]
    skip_items(plan, ["a"], kind=kind, note="Maintained evidence", attestation="Reviewed")
    expected_skip = deepcopy(plan["skipped"]["a"])
    plan["promoted_ids"] = ["a", "b"]
    state = _state_with_issues("a", "b")
    incoming = deepcopy(state["issues"]["a"])
    state["issues"]["a"]["status"] = status

    for scan in (6, 7, 8):
        issues = state.get("work_items") or state["issues"]
        upsert_issues(issues, [deepcopy(incoming)], [], f"2026-10-10T22:0{scan}:00+00:00", lang="php")
        state["scan_count"] = scan
        reconcile_plan_after_scan(plan, state)

        assert state["work_items"]["a"]["status"] == status
        assert plan["skipped"]["a"] == expected_skip
        assert "a" not in plan["superseded"]
        assert "a" not in plan["queue_order"]
        assert "a" not in plan["promoted_ids"]
        assert cluster["issue_ids"] == ["b"]
        assert cluster["action_steps"][0]["issue_refs"] == ["b"]
        assert plan["overrides"]["a"]["cluster"] is None
        assert cluster["execution_status"] == cluster_status


@pytest.mark.parametrize("kind,status", [("false_positive", "false_positive"), ("permanent", "wontfix")])
def test_reaccepted_durable_skip_recovers_from_superseded_tombstone(kind, status):
    """An ordinary re-skip survives a tombstone left by an earlier scan."""
    plan = _plan_with_queue("a", "b")
    create_cluster(plan, "reviewed")
    add_to_cluster(plan, "reviewed", ["a", "b"])
    plan["superseded"]["a"] = {
        "original_id": "a", "status": "superseded",
        "superseded_at": "2026-10-10T21:00:00+00:00",
    }
    skip_items(plan, ["a"], kind=kind, note="Revalidated evidence", attestation="Reviewed")
    expected_skip = deepcopy(plan["skipped"]["a"])
    state = _state_with_issues("a", "b")
    incoming = deepcopy(state["issues"]["a"])
    state["issues"]["a"]["status"] = status

    for scan in (6, 7):
        issues = state.get("work_items") or state["issues"]
        upsert_issues(issues, [deepcopy(incoming)], [], f"2026-10-10T22:0{scan}:00+00:00", lang="php")
        state["scan_count"] = scan
        reconcile_plan_after_scan(plan, state)

        assert state["work_items"]["a"]["status"] == status
        assert plan["skipped"]["a"] == expected_skip
        assert "a" not in plan["superseded"]
        assert plan["clusters"]["reviewed"]["issue_ids"] == ["b"]


@pytest.mark.parametrize("kind", ["false_positive", "permanent"])
def test_durable_skip_of_missing_issue_still_supersedes(kind):
    plan = _plan_with_queue("gone")
    skip_items(plan, ["gone"], kind=kind, note="Reviewed", attestation="Reviewed")
    plan["superseded"]["gone"] = {
        "original_id": "gone", "status": "superseded",
        "superseded_at": "2026-10-10T21:00:00+00:00",
    }

    reconcile_plan_after_scan(plan, _state_with_issues())

    assert "gone" not in plan["skipped"]
    assert "gone" in plan["superseded"]


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
