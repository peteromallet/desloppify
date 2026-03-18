"""Tests for unified move — clusters, issues, and mixes."""

from __future__ import annotations

from desloppify.app.commands.plan.shared.patterns import resolve_ids_from_patterns
from desloppify.app.commands.plan.reorder_handlers import resolve_target
from desloppify.engine._plan.operations.queue import move_items
from desloppify.engine._plan.schema import empty_plan

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
        parts = fid.split("::")
        detector = parts[0] if len(parts) > 1 else "test"
        issues[fid] = {
            "id": fid,
            "status": status,
            "detector": detector,
            "file": "test.py",
            "tier": 1,
            "confidence": "high",
            "summary": f"Issue {fid}",
        }
    return {"issues": issues, "scan_count": 5}


# ---------------------------------------------------------------------------
# resolve_ids_from_patterns — cluster-name fallback
# ---------------------------------------------------------------------------

def test_resolve_cluster_name_to_member_ids():
    """Pattern 'my-cluster' expands to cluster members."""
    plan = _plan_with_queue("a", "b", "c")
    plan["clusters"] = {
        "my-cluster": {"issue_ids": ["a", "b"]},
    }
    state = _state_with_issues("a", "b", "c")

    result = resolve_ids_from_patterns(state, ["my-cluster"], plan=plan)
    assert result == ["a", "b"]


def test_resolve_cluster_name_with_only_step_refs_returns_empty():
    """Step refs are traceability metadata, not membership — cluster resolves empty."""
    plan = _plan_with_queue("a", "b", "c")
    plan["clusters"] = {
        "my-cluster": {
            "action_steps": [
                {"title": "Refs", "issue_refs": ["a", "b"]},
                {"title": "Deduped refs", "issue_refs": ["b", " ", "c"]},
            ]
        },
    }
    state = _state_with_issues("a", "b", "c")

    result = resolve_ids_from_patterns(state, ["my-cluster"], plan=plan)
    assert result == []


def test_resolve_mix_of_cluster_and_issue():
    """Cluster name + issue pattern resolve together."""
    plan = _plan_with_queue("a", "b", "c")
    plan["clusters"] = {
        "my-cluster": {"issue_ids": ["a"]},
    }
    state = _state_with_issues("a", "b", "c")

    result = resolve_ids_from_patterns(state, ["my-cluster", "c"], plan=plan)
    # "my-cluster" → ["a"], "c" → exact match on issue ID "c"
    assert "a" in result
    assert "c" in result
    assert len(result) == 2


def test_resolve_cluster_deduplicates():
    """Issue in both a cluster and a pattern isn't doubled."""
    plan = _plan_with_queue("a", "b", "c")
    plan["clusters"] = {
        "my-cluster": {"issue_ids": ["a", "b"]},
    }
    state = _state_with_issues("a", "b", "c")

    # "a" matches as a issue ID, "my-cluster" expands to [a, b]
    result = resolve_ids_from_patterns(state, ["a", "my-cluster"], plan=plan)
    # "a" from direct match, "b" from cluster (no dup of "a")
    assert result == ["a", "b"]


def test_issue_pattern_priority_over_cluster_name():
    """Detector match wins over same-named cluster."""
    plan = _plan_with_queue("review::file.py::naming", "other::x")
    plan["clusters"] = {
        "review": {"issue_ids": ["other::x"]},
    }
    # "review" detector matches the issue
    state = _state_with_issues("review::file.py::naming", "other::x")

    result = resolve_ids_from_patterns(state, ["review"], plan=plan)
    # Should match the detector "review", not the cluster named "review"
    assert "review::file.py::naming" in result
    # "other::x" should NOT be included (cluster fallback not triggered)
    assert "other::x" not in result


# ---------------------------------------------------------------------------
# resolve_target — cluster name as before/after target
# ---------------------------------------------------------------------------

def test_before_cluster_target():
    """`before my-cluster` resolves to first member in queue order."""
    plan = _plan_with_queue("x", "a", "b", "y")
    plan["clusters"] = {
        "my-cluster": {"issue_ids": ["a", "b"]},
    }

    resolved = resolve_target(plan, "my-cluster", "before")
    assert resolved == "a"


def test_after_cluster_target():
    """`after my-cluster` resolves to last member in queue order."""
    plan = _plan_with_queue("x", "a", "b", "y")
    plan["clusters"] = {
        "my-cluster": {"issue_ids": ["a", "b"]},
    }

    resolved = resolve_target(plan, "my-cluster", "after")
    assert resolved == "b"


def testresolve_target_non_cluster_passthrough():
    """Non-cluster target is returned unchanged."""
    plan = _plan_with_queue("a", "b")
    plan["clusters"] = {}

    assert resolve_target(plan, "b", "before") == "b"
    assert resolve_target(plan, None, "before") is None


def testresolve_target_empty_cluster():
    """Empty cluster target is returned unchanged."""
    plan = _plan_with_queue("a", "b")
    plan["clusters"] = {"empty": {"issue_ids": []}}

    assert resolve_target(plan, "empty", "before") == "empty"


def testresolve_target_with_only_step_refs_falls_back_to_cluster_name():
    """Step refs are not membership — empty cluster falls back to cluster name."""
    plan = _plan_with_queue("x", "a", "b", "y")
    plan["clusters"] = {
        "steps-only": {
            "action_steps": [{"title": "Tracked refs", "issue_refs": ["a", "b"]}],
        }
    }

    assert resolve_target(plan, "steps-only", "before") == "steps-only"
    assert resolve_target(plan, "steps-only", "after") == "steps-only"


# ---------------------------------------------------------------------------
# Multi-cluster move — collects all members, moves as one batch
# ---------------------------------------------------------------------------

def test_multi_cluster_move():
    """Moving 2 cluster names moves all members as one batch."""
    plan = _plan_with_queue("a", "b", "c", "d", "e")
    plan["clusters"] = {
        "c1": {"issue_ids": ["a", "b"]},
        "c2": {"issue_ids": ["d", "e"]},
    }

    # Collect all member IDs from both clusters
    seen: set[str] = set()
    all_ids: list[str] = []
    for name in ["c1", "c2"]:
        for fid in plan["clusters"][name].get("issue_ids", []):
            if fid not in seen:
                seen.add(fid)
                all_ids.append(fid)

    assert all_ids == ["a", "b", "d", "e"]

    # Move to bottom
    count = move_items(plan, all_ids, "bottom")
    assert count == 4
    # "c" should be first (only non-moved item), then the moved items
    assert plan["queue_order"] == ["c", "a", "b", "d", "e"]
