"""Tests for subjective queue ordering across cycle boundaries."""

from __future__ import annotations

from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions
from desloppify.tests.plan.test_stale_dimensions import (
    _plan_with_queue,
    _state_with_stale_dimensions,
    _state_with_unscored_dimensions,
)


def test_unscored_appends_after_existing() -> None:
    """Unscored dims append to back, never reorder existing items."""
    plan = _plan_with_queue("issue_a", "issue_b")
    plan["promoted_ids"] = ["issue_a"]
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 1
    assert plan["queue_order"] == [
        "issue_a",
        "issue_b",
        "subjective::design_coherence",
    ]


def test_unscored_multiple_append_to_back() -> None:
    """Multiple unscored dims all append to back."""
    plan = _plan_with_queue("issue_a", "issue_b", "issue_c")
    state = _state_with_unscored_dimensions("design_coherence", "error_consistency")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 2
    assert plan["queue_order"][:3] == ["issue_a", "issue_b", "issue_c"]
    assert all(fid.startswith("subjective::") for fid in plan["queue_order"][3:5])


def test_stale_injects_despite_objective_backlog() -> None:
    """Stale dims are non-deferrable and move ahead of objective items."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)

    assert result.injected == [
        "subjective::design_coherence",
        "subjective::error_consistency",
    ]
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "subjective::error_consistency",
        "some_issue::file.py::abc123",
    ]


def test_stale_injection_ignores_preserved_plan_start_scores() -> None:
    """Mid-cycle state does not block stale subjective work."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {
        "strict": 80.0,
        "overall": 82.0,
        "objective": 84.0,
        "verified": 78.0,
    }
    state = _state_with_stale_dimensions("design_coherence")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)

    assert result.injected == ["subjective::design_coherence"]
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "some_issue::file.py::abc123",
    ]


def test_unscored_still_skipped_mid_cycle_with_preserved_scores() -> None:
    """Placeholder reviews remain cycle-boundary-only."""
    plan = _plan_with_queue("issue_a")
    plan["plan_start_scores"] = {
        "strict": 80.0,
        "overall": 82.0,
        "objective": 84.0,
        "verified": 78.0,
    }
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)

    assert result.injected == []
    assert plan["queue_order"] == ["issue_a"]


def test_stale_promotes_ahead_of_existing_objective_items() -> None:
    """Stale reviews belong before objective work, not appended behind it."""
    plan = _plan_with_queue("issue_a", "issue_b")
    state = _state_with_stale_dimensions("design_coherence")
    state["work_items"]["issue_a"] = {
        "id": "issue_a",
        "status": "open",
        "detector": "smells",
    }
    state["work_items"]["issue_b"] = {
        "id": "issue_b",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)

    assert len(result.injected) == 1
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "issue_a",
        "issue_b",
    ]


def test_under_target_still_defers_mid_cycle() -> None:
    """Under-target reviews keep the old mid-cycle deferral behavior."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 80.0}
    state = _state_with_stale_dimensions("design_coherence")
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)

    assert result.injected == []
    assert plan["queue_order"] == ["some_issue::file.py::abc123"]


def test_no_subjective_dims_no_injection() -> None:
    """No subjective state means no queue changes."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    work_items: dict[str, dict] = {}
    state = {"work_items": work_items, "issues": work_items, "scan_count": 5}

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == []
    assert plan["queue_order"] == ["some_issue::file.py::abc123"]


def test_plan_reset_sentinel_is_not_mid_cycle() -> None:
    """Lifecycle reset sentinel should not count as an active cycle."""
    from desloppify.engine._plan.operations.lifecycle import reset_plan
    from desloppify.engine._plan.sync.context import is_mid_cycle

    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 80.0, "overall": 80.0}
    reset_plan(plan)

    assert plan["plan_start_scores"] == {"reset": True}
    assert is_mid_cycle(plan) is False


def test_triage_appends_to_back() -> None:
    """Triage stage IDs append to back, never reorder existing items."""
    from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS
    from desloppify.engine._plan.sync.triage import sync_triage_needed

    plan = _plan_with_queue("issue_a", "issue_b")
    plan["epic_triage_meta"] = {"issue_snapshot_hash": "old_hash"}
    work_items = {
        "review::file.py::abc": {"status": "open", "detector": "review"},
    }
    state = {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 5,
    }

    result = sync_triage_needed(plan, state)
    assert result.injected
    assert plan["queue_order"][0] == "issue_a"
    assert plan["queue_order"][1] == "issue_b"
    assert plan["queue_order"][2] == "triage::strategize"
    assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)
