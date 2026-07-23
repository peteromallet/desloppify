"""Tests for queue order guard in resolve command."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

from desloppify.engine._plan.persistence import save_plan
from desloppify.engine._plan.schema import empty_plan, ensure_plan_defaults

# ---------------------------------------------------------------------------
# Lazy import helper — avoids the circular import in resolve/render
# ---------------------------------------------------------------------------

def _import_guard():
    """Import _check_queue_order_guard, patching away the render dependency."""
    import desloppify.app.commands.resolve.cmd as cmd_mod
    return cmd_mod._check_queue_order_guard


def _get_guard_fn():
    """Return the guard function, handling circular import gracefully."""
    try:
        return _import_guard()
    except ImportError:
        # Fall back: patch the problematic render import chain
        import sys
        stub = MagicMock()
        modules_to_stub = [
            "desloppify.app.commands.helpers.score_update",
            "desloppify.app.commands.scan.helpers",
        ]
        saved = {}
        for mod_name in modules_to_stub:
            if mod_name in sys.modules:
                saved[mod_name] = sys.modules[mod_name]
            sys.modules[mod_name] = stub

        # Force reimport
        import desloppify.app.commands.resolve.cmd as cmd_mod
        importlib.reload(cmd_mod)
        fn = cmd_mod._check_queue_order_guard

        # Restore
        for mod_name in modules_to_stub:
            if mod_name in saved:
                sys.modules[mod_name] = saved[mod_name]
            else:
                sys.modules.pop(mod_name, None)
        return fn


_check_queue_order_guard = _get_guard_fn()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_with_issues(*ids: str) -> dict:
    work_items = {}
    for fid in ids:
        work_items[fid] = {
            "id": fid,
            "status": "open",
            "detector": "unused",
            "file": "test.py",
            "tier": 1,
            "confidence": "high",
            "summary": f"Issue {fid}",
        }
    return {"work_items": work_items, "issues": work_items, "scan_count": 5}


def _setup_plan(tmp_path, monkeypatch, queue_order: list[str], clusters: dict | None = None):
    """Create and save a plan with given queue order, monkeypatch PLAN_FILE."""
    import desloppify.engine._plan.persistence as persist_mod

    plan_file = tmp_path / "plan.json"
    plan = empty_plan()
    ensure_plan_defaults(plan)
    plan["queue_order"] = queue_order
    if clusters:
        plan["clusters"] = clusters
    save_plan(plan, plan_file)
    monkeypatch.setattr(persist_mod, "PLAN_FILE", plan_file)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_guard_blocks_out_of_order(tmp_path, monkeypatch, capsys):
    """Resolving item #2 when item #1 is next should be blocked."""
    state = _state_with_issues("a", "b", "c")
    _setup_plan(tmp_path, monkeypatch, ["a", "b", "c"])

    blocked = _check_queue_order_guard(state, ["b"], "fixed")
    assert blocked is True

    captured = capsys.readouterr()
    assert "b" in captured.out
    assert "plan order" in captured.out.lower() or "Queue order" in captured.out


def test_guard_allows_front_item(tmp_path, monkeypatch):
    """Resolving the front item should be allowed."""
    state = _state_with_issues("a", "b")
    _setup_plan(tmp_path, monkeypatch, ["a", "b"])

    blocked = _check_queue_order_guard(state, ["a"], "fixed")
    assert blocked is False


def test_guard_allows_non_fixed_status(tmp_path, monkeypatch):
    """Non-fixed statuses (wontfix, open) bypass the guard."""
    state = _state_with_issues("a", "b")
    _setup_plan(tmp_path, monkeypatch, ["a", "b"])

    blocked = _check_queue_order_guard(state, ["b"], "wontfix")
    assert blocked is False


def test_guard_allows_cluster_member(tmp_path, monkeypatch):
    """If the front item is a cluster, its members should be allowed."""
    state = _state_with_issues("a", "b", "c")
    _setup_plan(
        tmp_path, monkeypatch,
        ["a", "b", "c"],
        clusters={
            "auto/unused": {
                "name": "auto/unused",
                "auto": True,
                "cluster_key": "auto::unused",
                "issue_ids": ["a", "b"],
                "description": "Fix 2 unused",
                "action": "desloppify autofix unused --dry-run",
                "user_modified": False,
            },
        },
    )

    # "a" and "b" are in the cluster that should be at the front
    blocked_a = _check_queue_order_guard(state, ["a"], "fixed")
    assert blocked_a is False

    blocked_b = _check_queue_order_guard(state, ["b"], "fixed")
    assert blocked_b is False


def test_guard_blocks_item_behind_cluster(tmp_path, monkeypatch, capsys):
    """Item behind a cluster should be blocked."""
    state = _state_with_issues("a", "b", "c")
    _setup_plan(
        tmp_path, monkeypatch,
        ["a", "b", "c"],
        clusters={
            "auto/unused": {
                "name": "auto/unused",
                "auto": True,
                "cluster_key": "auto::unused",
                "issue_ids": ["a", "b"],
                "description": "Fix 2 unused",
                "action": "desloppify autofix unused --dry-run",
                "user_modified": False,
            },
        },
    )

    # "c" is behind the cluster
    blocked = _check_queue_order_guard(state, ["c"], "fixed")
    assert blocked is True


def test_guard_no_plan(tmp_path, monkeypatch):
    """No living plan → no blocking."""
    import desloppify.engine._plan.persistence as persist_mod

    plan_file = tmp_path / "nonexistent.json"
    monkeypatch.setattr(persist_mod, "PLAN_FILE", plan_file)

    state = _state_with_issues("a")
    blocked = _check_queue_order_guard(state, ["a"], "fixed")
    assert blocked is False


def test_guard_empty_queue(tmp_path, monkeypatch):
    """Empty queue order → no blocking."""
    state = _state_with_issues("a")
    _setup_plan(tmp_path, monkeypatch, [])

    blocked = _check_queue_order_guard(state, ["a"], "fixed")
    assert blocked is False


def test_guard_prints_reorganize_commands(tmp_path, monkeypatch, capsys):
    """Blocked output should show plan reorder/skip/next commands."""
    state = _state_with_issues("a", "b")
    _setup_plan(tmp_path, monkeypatch, ["a", "b"])

    _check_queue_order_guard(state, ["b"], "fixed")
    captured = capsys.readouterr()
    assert "plan reorder" in captured.out
    assert "plan skip" in captured.out
    assert "next" in captured.out


# ---------------------------------------------------------------------------
# Stale issue ID tests (issue #182)
# ---------------------------------------------------------------------------

def test_guard_skips_stale_ids_in_queue_order(tmp_path, monkeypatch):
    """Stale IDs at the front of queue_order should not block live items."""
    # "stale" is in queue_order but NOT in state issues at all
    state = _state_with_issues("b", "c")
    _setup_plan(tmp_path, monkeypatch, ["stale", "b", "c"])

    # "b" should be treated as the effective front since "stale" is gone
    blocked = _check_queue_order_guard(state, ["b"], "fixed")
    assert blocked is False


def test_guard_skips_resolved_ids_in_queue_order(tmp_path, monkeypatch):
    """Resolved (non-open) IDs at the front of queue_order should not block."""
    state = _state_with_issues("a", "b")
    # Mark "a" as fixed — it's still in state but no longer open
    state["work_items"]["a"]["status"] = "fixed"
    _setup_plan(tmp_path, monkeypatch, ["a", "b"])

    # "b" should be next since "a" is resolved
    blocked = _check_queue_order_guard(state, ["b"], "fixed")
    assert blocked is False


def test_guard_cluster_with_stale_members(tmp_path, monkeypatch):
    """Cluster with stale members should not cause false queue-order violation."""
    # "a" is alive, "stale_member" is not in state
    state = _state_with_issues("a", "c")
    _setup_plan(
        tmp_path, monkeypatch,
        ["a", "stale_member", "c"],
        clusters={
            "auto/unused": {
                "name": "auto/unused",
                "auto": True,
                "cluster_key": "auto::unused",
                "issue_ids": ["a", "stale_member"],
                "description": "Fix 2 unused",
                "action": "desloppify autofix unused --dry-run",
                "user_modified": False,
            },
        },
    )

    # Resolving the cluster should not be blocked by its stale member
    blocked = _check_queue_order_guard(state, ["auto/unused"], "fixed")
    assert blocked is False


def test_guard_ignores_cluster_with_only_auto_resolved_members(
    tmp_path, monkeypatch
):
    state = _state_with_issues("front", "a", "b")
    state["work_items"]["a"]["status"] = "auto_resolved"
    state["work_items"]["b"]["status"] = "auto_resolved"
    _setup_plan(
        tmp_path,
        monkeypatch,
        ["front", "a", "b"],
        clusters={
            "resolved-cluster": {
                "name": "resolved-cluster",
                "issue_ids": ["a", "b"],
            }
        },
    )

    assert (
        _check_queue_order_guard(
            state,
            ["resolved-cluster"],
            "fixed",
        )
        is False
    )


def test_guard_all_resolved_ids_stale(tmp_path, monkeypatch):
    """If all resolved IDs are stale, guard should not block."""
    state = _state_with_issues("a")
    _setup_plan(tmp_path, monkeypatch, ["stale_1", "stale_2", "a"])

    # Trying to resolve only stale IDs → nothing to block
    blocked = _check_queue_order_guard(state, ["stale_1"], "fixed")
    assert blocked is False


def test_guard_allows_objective_when_triage_pending_and_stale_cluster_exists(
    tmp_path, monkeypatch,
):
    """Triage-pending state must not surface stale cluster ahead of objective work."""
    state = {
        "issues": {
            "smells::src/a.py::x": {
                "id": "smells::src/a.py::x",
                "status": "open",
                "detector": "smells",
                "file": "src/a.py",
                "tier": 3,
                "confidence": "high",
                "summary": "x",
            },
        },
        "scan_count": 5,
        "dimension_scores": {
            "Naming quality": {
                "score": 70.0,
                "strict": 70.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "naming_quality"},
                },
            },
            "Error consistency": {
                "score": 72.0,
                "strict": 72.0,
                "failing": 1,
                "detectors": {
                    "subjective_assessment": {"dimension_key": "error_consistency"},
                },
            },
        },
        "subjective_assessments": {
            "naming_quality": {
                "score": 70.0,
                "needs_review_refresh": True,
                "stale_since": "2026-01-01T00:00:00+00:00",
            },
            "error_consistency": {
                "score": 72.0,
                "needs_review_refresh": True,
                "stale_since": "2026-01-01T00:00:00+00:00",
            },
        },
    }
    _setup_plan(
        tmp_path,
        monkeypatch,
        [
            "triage::observe",
            "subjective::naming_quality",
            "subjective::error_consistency",
            "smells::src/a.py::x",
        ],
        clusters={
            "auto/stale-review": {
                "name": "auto/stale-review",
                "auto": True,
                "cluster_key": "subjective::stale",
                "issue_ids": [
                    "subjective::naming_quality",
                    "subjective::error_consistency",
                ],
                "description": "Re-review stale dimensions",
                "action": "desloppify review --prepare --dimensions naming_quality,error_consistency",
                "user_modified": False,
            },
        },
    )

    blocked = _check_queue_order_guard(state, ["smells::src/a.py::x"], "fixed")
    assert blocked is False


def test_guard_allows_front_planned_review_ids_even_if_synthetic_items_render_first(
    tmp_path, monkeypatch,
):
    state = {
        "issues": {
            "review::a": {
                "id": "review::a",
                "status": "open",
                "detector": "review",
                "file": "a.py",
                "tier": 1,
                "confidence": "high",
                "summary": "Review issue a",
            },
            "review::b": {
                "id": "review::b",
                "status": "open",
                "detector": "review",
                "file": "b.py",
                "tier": 1,
                "confidence": "high",
                "summary": "Review issue b",
            },
        },
        "scan_count": 5,
    }
    _setup_plan(tmp_path, monkeypatch, ["review::a", "review::b", "subjective::naming"])

    import desloppify.app.commands.resolve.queue_guard as queue_guard_mod

    monkeypatch.setattr(
        queue_guard_mod,
        "build_work_queue",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "subjective::abstraction_fitness", "kind": "subjective_dimension"},
                {"id": "review::a", "kind": "issue"},
                {"id": "review::b", "kind": "issue"},
            ]
        },
    )

    blocked = _check_queue_order_guard(state, ["review::a", "review::b"], "fixed")
    assert blocked is False
