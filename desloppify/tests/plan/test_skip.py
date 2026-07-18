"""Tests for plan skip/unskip operations."""

from __future__ import annotations

from desloppify.engine._plan.operations.cluster import (
    add_to_cluster,
    create_cluster,
    remove_from_cluster,
)
from desloppify.engine._plan.operations.lifecycle import purge_ids
from desloppify.engine._plan.operations.meta import append_log_entry
from desloppify.engine._plan.operations.queue import move_items
from desloppify.engine._plan.operations.skip import (
    resurface_stale_skips,
    skip_items,
    unskip_items,
)
from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import (
    empty_plan,
    ensure_plan_defaults,
    validate_plan,
)

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
# skip_items
# ---------------------------------------------------------------------------

def test_skip_temporary():
    plan = _plan_with_queue("a", "b", "c")
    count = skip_items(plan, ["b"], kind="temporary")
    assert count == 1
    assert "b" in plan["skipped"]
    assert plan["skipped"]["b"]["kind"] == "temporary"


def test_skip_permanent():
    plan = _plan_with_queue("a", "b")
    count = skip_items(
        plan, ["a"],
        kind="permanent",
        note="acceptable risk",
        attestation="I have actually reviewed and am not gaming",
    )
    assert count == 1
    assert plan["skipped"]["a"]["kind"] == "permanent"
    assert plan["skipped"]["a"]["note"] == "acceptable risk"
    assert plan["skipped"]["a"]["attestation"] is not None


def test_skip_false_positive():
    plan = _plan_with_queue("a")
    count = skip_items(
        plan, ["a"],
        kind="false_positive",
        attestation="I have actually reviewed and am not gaming",
    )
    assert count == 1
    assert plan["skipped"]["a"]["kind"] == "false_positive"


def test_skip_removes_from_queue_order():
    plan = _plan_with_queue("a", "b", "c")
    skip_items(plan, ["b"], kind="temporary")
    assert "b" not in plan["queue_order"]
    assert plan["queue_order"] == ["a", "c"]


def test_skip_with_reason():
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="temporary", reason="waiting on PR #45")
    assert plan["skipped"]["a"]["reason"] == "waiting on PR #45"


def test_skip_with_review_after():
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="temporary", review_after=5, scan_count=10)
    entry = plan["skipped"]["a"]
    assert entry["review_after"] == 5
    assert entry["skipped_at_scan"] == 10


def test_skip_clears_focus_when_focused_cluster_has_no_queue_members():
    """Skipping the last actionable member should leave focus mode."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])
    plan["active_cluster"] = "my-cluster"

    count = skip_items(plan, ["a"], kind="permanent", note="done", attestation="attest")

    assert count == 1
    assert plan["skipped"]["a"]["kind"] == "permanent"
    assert plan["clusters"]["my-cluster"]["issue_ids"] == ["a"]
    assert plan["active_cluster"] is None


# ---------------------------------------------------------------------------
# unskip_items
# ---------------------------------------------------------------------------

def test_unskip_temporary():
    plan = _plan_with_queue("a", "b", "c")
    skip_items(plan, ["b"], kind="temporary")
    count, need_reopen, protected = unskip_items(plan, ["b"])
    assert count == 1
    assert need_reopen == ["b"]  # temporary skips now set state to deferred, so need reopen
    assert protected == []
    assert "b" in plan["queue_order"]
    assert "b" not in plan["skipped"]


def test_unskip_permanent_with_note_is_protected():
    """Permanent skips with notes are protected by default."""
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="permanent", note="test", attestation="test attest")
    count, need_reopen, protected = unskip_items(plan, ["a"])
    assert count == 0
    assert need_reopen == []
    assert protected == ["a"]
    assert "a" not in plan["queue_order"]
    assert "a" in plan["skipped"]


def test_unskip_permanent_with_note_force():
    """With include_protected=True, permanent skips with notes are unskipped."""
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="permanent", note="test", attestation="test attest")
    count, need_reopen, protected = unskip_items(plan, ["a"], include_protected=True)
    assert count == 1
    assert need_reopen == ["a"]
    assert protected == []
    assert "a" in plan["queue_order"]


def test_unskip_permanent_without_note_not_protected():
    """Permanent skips without notes are NOT protected (no judgment to preserve)."""
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="permanent")
    count, need_reopen, protected = unskip_items(plan, ["a"])
    assert count == 1
    assert need_reopen == ["a"]
    assert protected == []
    assert "a" in plan["queue_order"]


def test_unskip_false_positive_with_note_is_protected():
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="false_positive", note="not a real issue", attestation="test attest")
    count, need_reopen, protected = unskip_items(plan, ["a"])
    assert count == 0
    assert protected == ["a"]


def test_unskip_false_positive_without_note_returns_reopen_ids():
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="false_positive", attestation="test attest")
    count, need_reopen, protected = unskip_items(plan, ["a"])
    assert count == 1
    assert need_reopen == ["a"]
    assert protected == []


def test_unskip_nonexistent():
    plan = _plan_with_queue("a")
    count, need_reopen, protected = unskip_items(plan, ["zzz"])
    assert count == 0
    assert need_reopen == []
    assert protected == []


# ---------------------------------------------------------------------------
# resurface_stale_skips
# ---------------------------------------------------------------------------

def test_resurface_stale_skips():
    plan = _plan_with_queue()
    skip_items(plan, ["a", "b"], kind="temporary", review_after=3, scan_count=5)
    skip_items(plan, ["c"], kind="temporary", review_after=10, scan_count=5)

    # At scan 8 (5+3): a and b should resurface, c should not
    resurfaced = resurface_stale_skips(plan, 8)
    assert set(resurfaced) == {"a", "b"}
    assert "a" in plan["queue_order"]
    assert "b" in plan["queue_order"]
    assert "c" in plan["skipped"]


def test_resurface_no_review_after_stays():
    plan = _plan_with_queue()
    skip_items(plan, ["a"], kind="temporary")  # review_after=None
    resurfaced = resurface_stale_skips(plan, 100)
    assert resurfaced == []
    assert "a" in plan["skipped"]


def test_resurface_permanent_never_resurfaces():
    plan = _plan_with_queue()
    skip_items(plan, ["a"], kind="permanent", note="ok", attestation="attest", scan_count=5)
    resurfaced = resurface_stale_skips(plan, 100)
    assert resurfaced == []
    assert "a" in plan["skipped"]


# ---------------------------------------------------------------------------
# purge_ids cleans skipped
# ---------------------------------------------------------------------------

def test_move_clears_skipped():
    plan = _plan_with_queue("a", "b", "c")
    skip_items(plan, ["b"], kind="temporary")
    assert "b" in plan["skipped"]
    assert "b" not in plan["queue_order"]

    move_items(plan, ["b"], "top")
    assert "b" not in plan["skipped"]
    assert plan["queue_order"][0] == "b"


def test_purge_ids_cleans_skipped():
    plan = _plan_with_queue("a")
    skip_items(plan, ["b"], kind="temporary")
    assert "b" in plan["skipped"]
    purged = purge_ids(plan, ["b"])
    assert purged == 1
    assert "b" not in plan["skipped"]


# ---------------------------------------------------------------------------
# Migration: deferred → skipped
# ---------------------------------------------------------------------------

def test_migration_deferred_to_skipped():
    plan = empty_plan()
    plan["deferred"] = ["x", "y"]
    plan["skipped"] = {}
    ensure_plan_defaults(plan)
    assert plan["deferred"] == []
    assert "x" in plan["skipped"]
    assert "y" in plan["skipped"]
    assert plan["skipped"]["x"]["kind"] == "temporary"
    assert plan["skipped"]["y"]["kind"] == "temporary"


def test_migration_deferred_does_not_overwrite_existing():
    plan = empty_plan()
    plan["deferred"] = ["x"]
    plan["skipped"] = {"x": {"issue_id": "x", "kind": "permanent", "note": "existing"}}
    ensure_plan_defaults(plan)
    # x was already in skipped, should keep existing entry
    assert plan["skipped"]["x"]["kind"] == "permanent"
    assert plan["deferred"] == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_validate_no_overlap_queue_skipped():
    plan = empty_plan()
    plan["queue_order"] = ["a"]
    plan["skipped"] = {"a": {"issue_id": "a", "kind": "temporary"}}
    try:
        validate_plan(plan)
        raise AssertionError("Should have raised ValueError")
    except ValueError as exc:
        assert "queue_order and skipped" in str(exc)


def test_validate_invalid_skip_kind():
    plan = empty_plan()
    plan["skipped"] = {"a": {"issue_id": "a", "kind": "invalid_kind"}}
    try:
        validate_plan(plan)
        raise AssertionError("Should have raised ValueError")
    except ValueError as exc:
        assert "invalid_kind" in str(exc)


def test_validate_skip_entry_missing_kind():
    plan = empty_plan()
    plan["skipped"] = {"a": {"issue_id": "a"}}
    try:
        validate_plan(plan)
        raise AssertionError("Should have raised ValueError")
    except ValueError as exc:
        assert "missing required key 'kind'" in str(exc)


# ---------------------------------------------------------------------------
# Reconcile: superseded items in skipped
# ---------------------------------------------------------------------------

def test_reconcile_supersedes_skipped_items():
    plan = _plan_with_queue()
    skip_items(plan, ["gone"], kind="temporary")
    # State where "gone" no longer exists
    state = _state_with_issues("alive")

    result = reconcile_plan_after_scan(plan, state)
    assert "gone" in result.superseded
    assert "gone" not in plan["skipped"]
    assert "gone" in plan["superseded"]


def test_reconcile_resurfaced():
    plan = _plan_with_queue()
    skip_items(plan, ["a"], kind="temporary", review_after=2, scan_count=3)
    state = _state_with_issues("a")
    state["scan_count"] = 5  # 3+2 = 5, should resurface

    result = reconcile_plan_after_scan(plan, state)
    assert "a" in result.resurfaced
    assert "a" in plan["queue_order"]
    assert "a" not in plan["skipped"]


# ---------------------------------------------------------------------------
# Full roundtrip
# ---------------------------------------------------------------------------

def test_skip_and_unskip_roundtrip():
    plan = _plan_with_queue("a", "b", "c")

    # Skip temporary
    skip_items(plan, ["a"], kind="temporary", reason="later")
    assert "a" not in plan["queue_order"]
    assert plan["skipped"]["a"]["kind"] == "temporary"

    # Skip permanent
    skip_items(plan, ["b"], kind="permanent", note="won't fix", attestation="attest")
    assert "b" not in plan["queue_order"]
    assert plan["skipped"]["b"]["kind"] == "permanent"

    # Skip false positive
    skip_items(plan, ["c"], kind="false_positive", attestation="attest")
    assert plan["queue_order"] == []
    assert len(plan["skipped"]) == 3

    # Unskip all — b is protected (permanent with note), c is not (fp without note)
    count, need_reopen, protected = unskip_items(plan, ["a", "b", "c"])
    assert count == 2  # a (temporary) + c (fp without note)
    assert set(need_reopen) == {"a", "c"}  # temporary skips now need reopen too (deferred→open)
    assert protected == ["b"]
    assert "a" in plan["queue_order"]
    assert "b" not in plan["queue_order"]  # protected
    assert "c" in plan["queue_order"]
    assert "b" in plan["skipped"]  # stayed

    # Force unskip to get b too
    count2, need_reopen2, protected2 = unskip_items(plan, ["b"], include_protected=True)
    assert count2 == 1
    assert need_reopen2 == ["b"]
    assert protected2 == []
    assert "b" in plan["queue_order"]
    assert plan["skipped"] == {}


# ---------------------------------------------------------------------------
# purge_ids clears override cluster ref
# ---------------------------------------------------------------------------

def test_purge_ids_clears_override_cluster_ref():
    """purge_ids should clear the cluster field from overrides."""
    plan = _plan_with_queue("a", "b")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])

    assert plan["overrides"]["a"]["cluster"] == "my-cluster"

    purged = purge_ids(plan, ["a"])
    assert purged == 1
    # Override still exists (notes kept for history) but cluster cleared
    assert plan["overrides"]["a"]["cluster"] is None


def test_purge_ids_clears_focus_when_active_cluster_becomes_empty():
    """purge_ids should leave focus mode when the focused cluster empties."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])
    plan["active_cluster"] = "my-cluster"

    purged = purge_ids(plan, ["a"])

    assert purged == 1
    assert plan["clusters"]["my-cluster"]["issue_ids"] == []
    assert plan["active_cluster"] is None


def test_purge_ids_keeps_resolved_member_out_of_historical_cluster():
    """A later normalization must not replay a resolved cluster member."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])
    append_log_entry(
        plan,
        "cluster_add",
        issue_ids=["a"],
        cluster_name="my-cluster",
    )

    assert purge_ids(plan, ["a"]) == 1
    ensure_plan_defaults(plan)

    assert plan["clusters"]["my-cluster"]["issue_ids"] == []
    assert plan["execution_log"][-1]["action"] == "cluster_remove"
    assert plan["execution_log"][-1]["actor"] == "system"


def test_cluster_remove_survives_normalization_before_its_log_is_appended():
    """A cluster remove command must not rehydrate its member before save."""
    plan = _plan_with_queue("a")
    ensure_plan_defaults(plan)
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["a"])
    append_log_entry(
        plan,
        "cluster_add",
        issue_ids=["a"],
        cluster_name="my-cluster",
    )

    assert remove_from_cluster(plan, "my-cluster", ["a"]) == 1
    append_log_entry(
        plan,
        "cluster_remove",
        issue_ids=["a"],
        cluster_name="my-cluster",
    )
    ensure_plan_defaults(plan)

    assert plan["clusters"]["my-cluster"]["issue_ids"] == []


# ---------------------------------------------------------------------------
# append_log_entry
# ---------------------------------------------------------------------------

def test_append_log_entry_basic():
    plan = empty_plan()
    append_log_entry(plan, "done", issue_ids=["a", "b"], actor="user", note="test note")
    log = plan["execution_log"]
    assert len(log) == 1
    entry = log[0]
    assert entry["action"] == "done"
    assert entry["issue_ids"] == ["a", "b"]
    assert entry["actor"] == "user"
    assert entry["note"] == "test note"
    assert "timestamp" in entry


def test_append_log_entry_caps_at_default(monkeypatch):
    import desloppify.engine._plan.operations.meta as ops_meta_mod

    cap = 500
    monkeypatch.setattr(ops_meta_mod, "_get_log_cap", lambda: cap)

    plan = empty_plan()
    for i in range(cap + 10):
        append_log_entry(plan, "test", issue_ids=[str(i)], actor="user")

    log = plan["execution_log"]
    assert len(log) == cap
    # Oldest entries should have been dropped
    assert log[0]["issue_ids"] == ["10"]
    assert log[-1]["issue_ids"] == [str(cap + 9)]


def test_append_log_entry_uncapped(monkeypatch):
    import desloppify.engine._plan.operations.meta as ops_meta_mod

    monkeypatch.setattr(ops_meta_mod, "_get_log_cap", lambda: 0)

    plan = empty_plan()
    total = 600
    for i in range(total):
        append_log_entry(plan, "test", issue_ids=[str(i)], actor="user")

    assert len(plan["execution_log"]) == total


def test_append_log_entry_custom_cap(monkeypatch):
    import desloppify.engine._plan.operations.meta as ops_meta_mod

    monkeypatch.setattr(ops_meta_mod, "_get_log_cap", lambda: 50)

    plan = empty_plan()
    for i in range(60):
        append_log_entry(plan, "test", issue_ids=[str(i)], actor="user")

    assert len(plan["execution_log"]) == 50
    assert plan["execution_log"][0]["issue_ids"] == ["10"]


def test_append_log_entry_with_cluster_and_detail():
    plan = empty_plan()
    append_log_entry(
        plan,
        "cluster_done",
        issue_ids=["a"],
        cluster_name="auto/unused",
        actor="agent",
        detail={"method": "bulk"},
    )
    entry = plan["execution_log"][0]
    assert entry["cluster_name"] == "auto/unused"
    assert entry["detail"] == {"method": "bulk"}
    assert entry["actor"] == "agent"
