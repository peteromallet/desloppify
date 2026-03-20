"""Tests for stale-dimension queue ordering and cycle-completion injections."""

from __future__ import annotations

from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions
from desloppify.tests.plan.test_stale_dimensions import (
    _plan_with_queue,
    _state_with_stale_dimensions,
    _state_with_unscored_dimensions,
)


def test_unscored_appends_after_existing():
    """Unscored dims append to back, never reorder existing items."""
    plan = _plan_with_queue("issue_a", "issue_b")
    plan["promoted_ids"] = ["issue_a"]
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 1
    assert plan["queue_order"][0] == "issue_a"
    assert plan["queue_order"][1] == "issue_b"
    assert plan["queue_order"][2] == "subjective::design_coherence"


def test_unscored_multiple_append_to_back():
    """Multiple unscored dims all append to back."""
    plan = _plan_with_queue("issue_a", "issue_b", "issue_c")
    state = _state_with_unscored_dimensions("design_coherence", "error_consistency")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 2
    # Existing items keep their positions
    assert plan["queue_order"][0] == "issue_a"
    assert plan["queue_order"][1] == "issue_b"
    assert plan["queue_order"][2] == "issue_c"
    # Unscored dims appended at back
    assert all(
        fid.startswith("subjective::")
        for fid in plan["queue_order"][3:5]
    )


# ---------------------------------------------------------------------------
# Post-cycle injection: cycle_just_completed overrides objective gate
# ---------------------------------------------------------------------------

def test_cycle_completed_injects_stale_despite_objective_backlog():
    """After a completed cycle, stale dims inject even with new objective issues."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    # Without cycle_just_completed: no injection (existing behavior)
    result_normal = sync_subjective_dimensions(plan, state)
    assert result_normal.injected == []

    # With cycle_just_completed: inject at back (never reorder existing queue)
    plan2 = _plan_with_queue("some_issue::file.py::abc123")
    result_cycle = sync_subjective_dimensions(plan2, state, cycle_just_completed=True)
    assert len(result_cycle.injected) == 2
    # Existing item keeps position; stale dims appended at back
    assert plan2["queue_order"][0] == "some_issue::file.py::abc123"
    assert plan2["queue_order"][1].startswith("subjective::")
    assert plan2["queue_order"][2].startswith("subjective::")


def test_cycle_completed_injects_stale_with_plan_start_scores_preserved():
    """Force-rescan can inject stale dims while preserved scores keep mid-cycle semantics."""
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

    result = sync_subjective_dimensions(plan, state, cycle_just_completed=True)

    assert result.injected == ["subjective::design_coherence"]
    assert plan["queue_order"] == [
        "some_issue::file.py::abc123",
        "subjective::design_coherence",
    ]


def test_cycle_completed_with_preserved_scores_still_skips_unscored():
    """Force-rescan remains rescan-and-continue: placeholder reviews stay out."""
    plan = _plan_with_queue("issue_a")
    plan["plan_start_scores"] = {
        "strict": 80.0,
        "overall": 82.0,
        "objective": 84.0,
        "verified": 78.0,
    }
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state, cycle_just_completed=True)

    assert result.injected == []
    assert plan["queue_order"] == ["issue_a"]


def test_cycle_completed_appends_to_back():
    """Post-cycle stale injection appends to back, preserving existing order."""
    plan = _plan_with_queue("issue_a", "issue_b")
    state = _state_with_stale_dimensions("design_coherence")
    state["work_items"]["issue_a"] = {
        "id": "issue_a", "status": "open", "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state, cycle_just_completed=True)
    assert len(result.injected) == 1
    assert plan["queue_order"][0] == "issue_a"
    assert plan["queue_order"][1] == "issue_b"
    assert plan["queue_order"][2] == "subjective::design_coherence"


def test_cycle_completed_injects_under_target_dims():
    """After a completed cycle, under-target (non-stale) dims are also injected."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    # Dimension is below target but NOT stale (no needs_review_refresh)
    state = _state_with_stale_dimensions("design_coherence")
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    # Without cycle_just_completed: no injection (under-target gated by backlog)
    result_normal = sync_subjective_dimensions(plan, state)
    assert result_normal.injected == []

    # With cycle_just_completed: under-target dim injected at back
    plan2 = _plan_with_queue("some_issue::file.py::abc123")
    result_cycle = sync_subjective_dimensions(plan2, state, cycle_just_completed=True)
    assert len(result_cycle.injected) == 1
    assert plan2["queue_order"][0] == "some_issue::file.py::abc123"
    assert plan2["queue_order"][1] == "subjective::design_coherence"


def test_under_target_injected_when_no_objective_backlog():
    """Under-target dims inject when queue has no objective items (same as stale)."""
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence")
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::design_coherence" in result.injected


def test_cycle_completed_no_stale_dims_no_injection():
    """cycle_just_completed has no effect when no stale dims exist."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    work_items: dict[str, dict] = {}
    state = {"work_items": work_items, "issues": work_items, "scan_count": 5}

    result = sync_subjective_dimensions(plan, state, cycle_just_completed=True)
    assert result.injected == []
    assert plan["queue_order"] == ["some_issue::file.py::abc123"]


def test_cycle_completed_no_objective_appends_to_back():
    """When cycle completed but no objective backlog, stale dims still go to back."""
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state, cycle_just_completed=True)
    assert len(result.injected) == 1
    assert plan["queue_order"] == ["subjective::design_coherence"]


def test_plan_reset_does_not_trigger_cycle_completed():
    """After plan reset, stale dims should NOT be front-loaded.

    reset_plan() sets plan_start_scores to {"reset": True} so that
    _cycle_just_completed = not plan.get("plan_start_scores") is False.
    The next scan seeds real scores over the sentinel.
    """
    from desloppify.engine._plan.operations.lifecycle import reset_plan

    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 80.0, "overall": 80.0}
    reset_plan(plan)

    # Sentinel should be set
    assert plan["plan_start_scores"] == {"reset": True}
    # Truthiness check — this is what scan_workflow uses
    assert plan.get("plan_start_scores")  # truthy, so cycle_just_completed=False


def test_triage_appends_to_back():
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
    assert result.injected  # non-empty list of injected stage IDs
    # Existing items keep their positions
    assert plan["queue_order"][0] == "issue_a"
    assert plan["queue_order"][1] == "issue_b"
    # Triage stages appended at back
    assert plan["queue_order"][2] == "triage::observe"
    assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)
