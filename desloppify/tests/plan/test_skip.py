"""Tests for plan skip/unskip operations."""

from __future__ import annotations

from desloppify.engine._plan.operations import (
    move_items,
    purge_ids,
    skip_items,
    unskip_items,
    resurface_stale_skips,
)
from desloppify.engine._plan.reconcile import reconcile_plan_after_scan
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


def _state_with_findings(*ids: str, status: str = "open") -> dict:
    findings = {}
    for fid in ids:
        findings[fid] = {
            "id": fid,
            "status": status,
            "detector": "test",
            "file": "test.py",
            "tier": 1,
            "confidence": "high",
            "summary": f"Finding {fid}",
        }
    return {"findings": findings, "scan_count": 5}


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


# ---------------------------------------------------------------------------
# unskip_items
# ---------------------------------------------------------------------------

def test_unskip_temporary():
    plan = _plan_with_queue("a", "b", "c")
    skip_items(plan, ["b"], kind="temporary")
    count, need_reopen = unskip_items(plan, ["b"])
    assert count == 1
    assert need_reopen == []
    assert "b" in plan["queue_order"]
    assert "b" not in plan["skipped"]


def test_unskip_permanent_returns_reopen_ids():
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="permanent", note="test", attestation="test attest")
    count, need_reopen = unskip_items(plan, ["a"])
    assert count == 1
    assert need_reopen == ["a"]
    assert "a" in plan["queue_order"]


def test_unskip_false_positive_returns_reopen_ids():
    plan = _plan_with_queue("a")
    skip_items(plan, ["a"], kind="false_positive", attestation="test attest")
    count, need_reopen = unskip_items(plan, ["a"])
    assert count == 1
    assert need_reopen == ["a"]


def test_unskip_nonexistent():
    plan = _plan_with_queue("a")
    count, need_reopen = unskip_items(plan, ["zzz"])
    assert count == 0
    assert need_reopen == []


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
    plan["skipped"] = {"x": {"finding_id": "x", "kind": "permanent", "note": "existing"}}
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
    plan["skipped"] = {"a": {"finding_id": "a", "kind": "temporary"}}
    try:
        validate_plan(plan)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "queue_order and skipped" in str(exc)


def test_validate_invalid_skip_kind():
    plan = empty_plan()
    plan["skipped"] = {"a": {"finding_id": "a", "kind": "invalid_kind"}}
    try:
        validate_plan(plan)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "invalid_kind" in str(exc)


# ---------------------------------------------------------------------------
# Reconcile: superseded items in skipped
# ---------------------------------------------------------------------------

def test_reconcile_supersedes_skipped_items():
    plan = _plan_with_queue()
    skip_items(plan, ["gone"], kind="temporary")
    # State where "gone" no longer exists
    state = _state_with_findings("alive")

    result = reconcile_plan_after_scan(plan, state)
    assert "gone" in result.superseded
    assert "gone" not in plan["skipped"]
    assert "gone" in plan["superseded"]


def test_reconcile_resurfaced():
    plan = _plan_with_queue()
    skip_items(plan, ["a"], kind="temporary", review_after=2, scan_count=3)
    state = _state_with_findings("a")
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

    # Unskip all
    count, need_reopen = unskip_items(plan, ["a", "b", "c"])
    assert count == 3
    assert set(need_reopen) == {"b", "c"}
    assert plan["queue_order"] == ["a", "b", "c"]
    assert plan["skipped"] == {}


