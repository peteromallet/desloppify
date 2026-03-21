"""Tests for unified subjective dimension sync in the plan."""

from __future__ import annotations

from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_with_queue(*ids: str) -> dict:
    plan = empty_plan()
    plan["queue_order"] = list(ids)
    return plan


def _state_with_stale_dimensions(*dim_keys: str, score: float = 50.0) -> dict:
    """Build a minimal state with stale subjective dimensions."""
    dim_scores: dict = {}
    assessments: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": score,
            "strict": score,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": False,
                }
            },
        }
        assessments[dim_key] = {
            "score": score,
            "needs_review_refresh": True,
            "refresh_reason": "mechanical_issues_changed",
            "stale_since": "2025-01-01T00:00:00+00:00",
        }
    work_items: dict[str, dict] = {}
    return {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 5,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _state_with_unscored_dimensions(*dim_keys: str) -> dict:
    """Build a minimal state with unscored (placeholder) subjective dimensions."""
    dim_scores: dict = {}
    assessments: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": 0,
            "strict": 0,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": True,
                }
            },
        }
        assessments[dim_key] = {
            "score": 0.0,
            "source": "scan_reset_subjective",
            "placeholder": True,
        }
    work_items: dict[str, dict] = {}
    return {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 1,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _state_with_under_target_dimensions(*dim_keys: str, score: float = 50.0) -> dict:
    """Build a minimal state with under-target (scored, not stale) subjective dimensions."""
    dim_scores: dict = {}
    assessments: dict = {}
    for dim_key in dim_keys:
        dim_scores[dim_key] = {
            "score": score,
            "strict": score,
            "checks": 1,
            "failing": 0,
            "detectors": {
                "subjective_assessment": {
                    "dimension_key": dim_key,
                    "placeholder": False,
                }
            },
        }
        assessments[dim_key] = {
            "score": score,
            "needs_review_refresh": False,
        }
    work_items: dict[str, dict] = {}
    return {
        "work_items": work_items,
        "issues": work_items,
        "scan_count": 5,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _state_with_mixed_dimensions(
    unscored: list[str],
    stale: list[str],
    under_target: list[str] | None = None,
) -> dict:
    """Build a state with unscored, stale, and optionally under-target dimensions."""
    state = _state_with_unscored_dimensions(*unscored)
    stale_state = _state_with_stale_dimensions(*stale)
    state["dimension_scores"].update(stale_state["dimension_scores"])
    state["subjective_assessments"].update(stale_state["subjective_assessments"])
    if under_target:
        ut_state = _state_with_under_target_dimensions(*under_target)
        state["dimension_scores"].update(ut_state["dimension_scores"])
        state["subjective_assessments"].update(ut_state["subjective_assessments"])
    return state


# ---------------------------------------------------------------------------
# Unscored dimension sync
# ---------------------------------------------------------------------------

def test_unscored_injected_at_back():
    """Unscored IDs are appended after existing items."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    state = _state_with_unscored_dimensions("design_coherence", "error_consistency")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 2
    # Existing item keeps its position; unscored dims appended at back
    assert plan["queue_order"][0] == "some_issue::file.py::abc123"
    assert plan["queue_order"][1].startswith("subjective::")
    assert plan["queue_order"][2].startswith("subjective::")


def test_unscored_injection_unconditional():
    """Unscored dims inject even when objective items exist in queue."""
    plan = _plan_with_queue(
        "some_issue::file.py::abc123",
        "another::file.py::def456",
    )
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 1
    assert plan["queue_order"][-1] == "subjective::design_coherence"
    assert len(plan["queue_order"]) == 3  # 2 existing + 1 unscored


def test_unscored_pruned_after_review():
    """Once a dimension is scored, it is removed from the queue."""
    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
        "some_issue::file.py::abc123",
    )
    # Only error_consistency is still unscored; design_coherence was scored
    state = _state_with_unscored_dimensions("error_consistency")

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::design_coherence" in result.pruned
    assert "subjective::error_consistency" in plan["queue_order"]
    assert "subjective::design_coherence" not in plan["queue_order"]


def test_stale_sync_does_not_prune_unscored_ids():
    """Stale sync must not remove IDs that are still unscored."""
    plan = _plan_with_queue(
        "subjective::design_coherence",  # unscored
        "subjective::error_consistency",  # stale
    )
    state = _state_with_mixed_dimensions(
        unscored=["design_coherence"],
        stale=["error_consistency"],
    )

    result = sync_subjective_dimensions(plan, state)
    # design_coherence is unscored (not stale), but stale sync should NOT prune it
    assert "subjective::design_coherence" not in result.pruned
    assert "subjective::design_coherence" in plan["queue_order"]
    assert "subjective::error_consistency" in plan["queue_order"]


def test_unscored_sync_does_not_prune_stale_ids():
    """Unscored sync must not remove IDs that are stale."""
    plan = _plan_with_queue(
        "subjective::design_coherence",  # unscored
        "subjective::error_consistency",  # stale
    )
    state = _state_with_mixed_dimensions(
        unscored=["design_coherence"],
        stale=["error_consistency"],
    )

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::error_consistency" not in result.pruned
    assert "subjective::error_consistency" in plan["queue_order"]


def test_unscored_no_injection_when_no_dimension_scores():
    plan = _plan_with_queue()
    work_items: dict[str, dict] = {}
    state = {"work_items": work_items, "issues": work_items, "scan_count": 1}

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == []
    assert result.pruned == []


def test_unscored_no_duplicates():
    """Already-present unscored IDs are not duplicated."""
    plan = _plan_with_queue("subjective::design_coherence")
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == []
    assert plan["queue_order"].count("subjective::design_coherence") == 1


def test_unscored_sync_resurfaces_skipped_subjective_ids():
    """Unscored subjective IDs are forcibly resurfaced even if previously skipped."""
    plan = _plan_with_queue()
    plan["skipped"] = {"subjective::design_coherence": {"kind": "permanent"}}
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == ["subjective::design_coherence"]
    assert plan["queue_order"] == ["subjective::design_coherence"]
    assert "subjective::design_coherence" not in plan["skipped"]


def test_unscored_sync_repairs_skipped_overlap():
    """If overlap exists, sync removes skip entry and keeps exactly one queue entry."""
    plan = _plan_with_queue("subjective::design_coherence")
    plan["skipped"] = {"subjective::design_coherence": {"kind": "permanent"}}
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == []
    assert result.pruned == []
    assert plan["queue_order"] == ["subjective::design_coherence"]
    assert "subjective::design_coherence" not in plan["skipped"]


# ---------------------------------------------------------------------------
# Injection: empty queue + stale dimensions
# ---------------------------------------------------------------------------

def test_injects_when_queue_empty():
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    result = sync_subjective_dimensions(plan, state)
    assert len(result.injected) == 2
    assert "subjective::design_coherence" in plan["queue_order"]
    assert "subjective::error_consistency" in plan["queue_order"]
    assert result.changes == 2


def test_stale_always_injected_with_objective_backlog():
    plan = _plan_with_queue("some_issue::file.py::abc123")
    state = _state_with_stale_dimensions("design_coherence")
    # Add an actual open objective issue to state (source of truth)
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


def test_stale_ids_not_evicted_when_objective_backlog_exists():
    """Stale IDs remain in queue_order ahead of objective work."""
    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
        "some_issue::file.py::abc123",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)
    assert result.pruned == []
    assert result.injected == []
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "subjective::error_consistency",
        "some_issue::file.py::abc123",
    ]


def test_stale_not_deferred_even_mid_cycle():
    """Stale IDs remain present even when the cycle is mid-flight."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 50.0}
    state = _state_with_stale_dimensions("design_coherence")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    r1 = sync_subjective_dimensions(plan, state)
    assert r1.injected == ["subjective::design_coherence"]
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "some_issue::file.py::abc123",
    ]


def test_stale_positioned_before_objective() -> None:
    plan = _plan_with_queue(
        "workflow::communicate-score",
        "triage::observe",
        "some_issue::file.py::abc123",
    )
    state = _state_with_stale_dimensions("design_coherence")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    sync_subjective_dimensions(plan, state)

    assert plan["queue_order"] == [
        "workflow::communicate-score",
        "triage::observe",
        "subjective::design_coherence",
        "some_issue::file.py::abc123",
    ]


def test_stale_repositioned_when_behind_objective() -> None:
    plan = _plan_with_queue(
        "some_issue::file.py::abc123",
        "subjective::design_coherence",
    )
    state = _state_with_stale_dimensions("design_coherence")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)

    assert result.injected == []
    assert result.pruned == []
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "some_issue::file.py::abc123",
    ]


def test_no_injection_when_no_stale_or_under_target_dimensions():
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence", score=100.0)
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == []
    assert plan["queue_order"] == []


def test_no_injection_when_no_dimension_scores():
    plan = _plan_with_queue()
    state = {"issues": {}, "scan_count": 5}

    result = sync_subjective_dimensions(plan, state)
    assert result.injected == []
    assert result.pruned == []


# ---------------------------------------------------------------------------
# Cleanup: prune resolved stale IDs
# ---------------------------------------------------------------------------

def test_prunes_resolved_dimension_ids():
    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    # Only design_coherence is still stale; error_consistency was refreshed
    state = _state_with_stale_dimensions("design_coherence")

    result = sync_subjective_dimensions(plan, state)
    assert result.pruned == ["subjective::error_consistency"]
    assert plan["queue_order"] == ["subjective::design_coherence"]


def test_prune_does_not_touch_real_issue_ids():
    plan = _plan_with_queue(
        "structural::file.py::abc123",
        "subjective::design_coherence",
    )
    # design_coherence is no longer stale
    state = {"issues": {}, "scan_count": 5, "dimension_scores": {}}

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::design_coherence" in result.pruned
    assert plan["queue_order"] == ["structural::file.py::abc123"]


# ---------------------------------------------------------------------------
# Full lifecycle: inject → refresh → prune → re-inject
# ---------------------------------------------------------------------------

def test_full_lifecycle():
    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 50.0}
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    # 1. Mid-cycle objective backlog does not block stale dims.
    r1 = sync_subjective_dimensions(plan, state)
    assert len(r1.injected) == 2
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "subjective::error_consistency",
        "some_issue::file.py::abc123",
    ]

    # 2. One dimension refreshes: it now follows under-target deferral rules.
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False

    r2 = sync_subjective_dimensions(plan, state)
    assert r2.pruned == ["subjective::design_coherence"]
    assert "subjective::design_coherence" not in plan["queue_order"]
    assert "subjective::error_consistency" in plan["queue_order"]

    # 3. Raising both above target clears subjective entries but leaves objective work.
    state["subjective_assessments"]["error_consistency"]["needs_review_refresh"] = False
    for key in ("design_coherence", "error_consistency"):
        state["dimension_scores"][key]["score"] = 100.0
        state["dimension_scores"][key]["strict"] = 100.0
        state["subjective_assessments"][key]["score"] = 100.0

    r3 = sync_subjective_dimensions(plan, state)
    assert r3.pruned == ["subjective::error_consistency"]
    assert plan["queue_order"] == ["some_issue::file.py::abc123"]
    assert r3.injected == []

    # 4. A new mechanical change makes one dimension stale again.
    state["dimension_scores"]["design_coherence"]["score"] = 50.0
    state["dimension_scores"]["design_coherence"]["strict"] = 50.0
    state["subjective_assessments"]["design_coherence"]["score"] = 50.0
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = True

    r4 = sync_subjective_dimensions(plan, state)
    assert r4.injected == ["subjective::design_coherence"]
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "some_issue::file.py::abc123",
    ]


# ---------------------------------------------------------------------------
# Reconcile must not supersede synthetic IDs
# ---------------------------------------------------------------------------

def test_reconcile_ignores_synthetic_ids():
    """Reconciliation must not treat subjective::* IDs as dead issues."""
    plan = _plan_with_queue("subjective::design_coherence")
    state = _state_with_stale_dimensions("design_coherence")

    result = reconcile_plan_after_scan(plan, state)
    assert result.superseded == []
    assert "subjective::design_coherence" in plan["queue_order"]
    assert "subjective::design_coherence" not in plan.get("superseded", {})


# ---------------------------------------------------------------------------
# Injection: only subjective items in queue (relaxed condition)
# ---------------------------------------------------------------------------

def test_injection_when_only_subjective_in_queue():
    """New stale dims are injected when only subjective IDs remain in queue."""
    plan = _plan_with_queue("subjective::design_coherence")
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::error_consistency" in result.injected
    assert "subjective::design_coherence" not in result.injected  # already there
    assert set(plan["queue_order"]) == {
        "subjective::design_coherence",
        "subjective::error_consistency",
    }


# ---------------------------------------------------------------------------
# Auto-clustering of stale subjective dimensions
# ---------------------------------------------------------------------------

def test_stale_cluster_created():
    """When >=2 stale dims exist, auto_cluster_issues creates a cluster."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_issues

    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    changes = auto_cluster_issues(plan, state)
    assert changes >= 1
    assert "auto/stale-review" in plan["clusters"]

    cluster = plan["clusters"]["auto/stale-review"]
    assert cluster["auto"] is True
    assert cluster["cluster_key"] == "subjective::stale"
    assert set(cluster["issue_ids"]) == {
        "subjective::design_coherence",
        "subjective::error_consistency",
    }
    assert "Re-review 2 stale" in cluster["description"]
    assert "desloppify review --prepare --dimensions" in cluster["action"]
    assert "design_coherence" in cluster["action"]
    assert "error_consistency" in cluster["action"]
    assert "--force-review-rerun" not in cluster["action"]


def test_stale_cluster_deleted_when_fresh():
    """When all dims are refreshed, the stale cluster is deleted."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_issues

    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    # Create the cluster
    auto_cluster_issues(plan, state)
    assert "auto/stale-review" in plan["clusters"]

    # Now remove subjective IDs from queue (simulating refresh + prune)
    plan["queue_order"] = []

    auto_cluster_issues(plan, state)
    assert "auto/stale-review" not in plan["clusters"]


def test_stale_cluster_updated():
    """When the stale set changes, the cluster membership updates."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_issues

    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    auto_cluster_issues(plan, state)
    assert set(plan["clusters"]["auto/stale-review"]["issue_ids"]) == {
        "subjective::design_coherence",
        "subjective::error_consistency",
    }

    # A third dimension becomes stale — must also appear in state
    plan["queue_order"].append("subjective::convention_drift")
    state2 = _state_with_stale_dimensions(
        "design_coherence", "error_consistency", "convention_drift",
    )
    changes = auto_cluster_issues(plan, state2)
    assert changes >= 1
    assert "subjective::convention_drift" in plan["clusters"]["auto/stale-review"]["issue_ids"]
    assert "Re-review 3 stale" in plan["clusters"]["auto/stale-review"]["description"]


def test_single_stale_dim_no_cluster():
    """Only 1 stale dim → no cluster created (below _MIN_CLUSTER_SIZE)."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_issues

    plan = _plan_with_queue("subjective::design_coherence")
    state = _state_with_stale_dimensions("design_coherence")

    auto_cluster_issues(plan, state)
    assert "auto/stale-review" not in plan["clusters"]


# ---------------------------------------------------------------------------
# Category preservation: under_target kept when not evicting
# ---------------------------------------------------------------------------

def test_under_target_preserved_when_no_backlog():
    """Under-target IDs are preserved when no objective backlog exists."""
    plan = _plan_with_queue(
        "subjective::design_coherence",   # unscored
        "subjective::naming_quality",     # under_target
    )
    state = _state_with_mixed_dimensions(
        unscored=["design_coherence"],
        stale=[],
        under_target=["naming_quality"],
    )

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" not in result.pruned
    assert "subjective::naming_quality" in plan["queue_order"]
    assert "subjective::design_coherence" in plan["queue_order"]


def test_under_target_evicted_mid_cycle_with_objective_backlog():
    """Mid-cycle with objective backlog, under_target IDs are evicted."""
    plan = _plan_with_queue(
        "subjective::naming_quality",     # under_target
        "some_issue::file.py::abc123",    # objective (makes it mid-cycle)
    )
    plan["plan_start_scores"] = {"strict": 50.0}  # mark as mid-cycle
    state = _state_with_mixed_dimensions(
        unscored=[],
        stale=[],
        under_target=["naming_quality"],
    )
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    result = sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" in result.pruned
    assert "subjective::naming_quality" not in plan["queue_order"]


# ---------------------------------------------------------------------------
# Regression: full evict → clear backlog → re-injection cycle
# ---------------------------------------------------------------------------

def test_under_target_reinjected_after_objective_backlog_clears():
    """Under-target IDs evicted mid-cycle must reappear when objective backlog clears."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 50.0}
    state = _state_with_mixed_dimensions(
        unscored=[],
        stale=[],
        under_target=["naming_quality", "error_handling"],
    )
    state["work_items"]["some_issue::file.py::abc123"] = {
        "id": "some_issue::file.py::abc123",
        "status": "open",
        "detector": "smells",
    }

    # Step 1: objective backlog → under_target not injected
    r1 = sync_subjective_dimensions(plan, state)
    assert r1.injected == []
    assert "subjective::naming_quality" not in plan["queue_order"]

    # Step 2: objective backlog clears
    state["work_items"]["some_issue::file.py::abc123"]["status"] = "done"

    # Step 3: under_target IDs injected
    r2 = sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" in r2.injected
    assert "subjective::error_handling" in r2.injected
    assert "subjective::naming_quality" in plan["queue_order"]
    assert "subjective::error_handling" in plan["queue_order"]

    # Step 4: idempotent — no double-injection
    r3 = sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" not in r3.pruned
    assert "subjective::naming_quality" in plan["queue_order"]


def test_escalation_mid_cycle_reinserts_evicted_ids():
    """After 3 deferred scans mid-cycle, escalation force-promotes previously-evicted IDs."""
    plan = _plan_with_queue("some_issue::file.py::abc123")
    plan["plan_start_scores"] = {"strict": 50.0}  # mid-cycle
    state = _state_with_under_target_dimensions("naming_quality")
    state["work_items"] = {
        "some_issue::file.py::abc123": {
            "id": "some_issue::file.py::abc123",
            "status": "open",
            "detector": "smells",
        },
    }
    state["scan_count"] = 1
    state["last_scan"] = "2026-03-01T00:00:00+00:00"

    # Scan 1: evicted, defer_count=1
    sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" not in plan["queue_order"]
    assert plan["subjective_defer_meta"]["defer_count"] == 1

    # Scan 2: still evicted, defer_count=2
    state["scan_count"] = 2
    state["last_scan"] = "2026-03-02T00:00:00+00:00"
    sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" not in plan["queue_order"]
    assert plan["subjective_defer_meta"]["defer_count"] == 2

    # Scan 3: escalation — naming_quality force-promoted ahead of objective work
    state["scan_count"] = 3
    state["last_scan"] = "2026-03-03T00:00:00+00:00"
    sync_subjective_dimensions(plan, state)
    assert "subjective::naming_quality" in plan["queue_order"]
    objective_idx = plan["queue_order"].index("some_issue::file.py::abc123")
    subjective_idx = plan["queue_order"].index("subjective::naming_quality")
    assert subjective_idx < objective_idx
    assert plan["subjective_defer_meta"]["force_visible_ids"] == ["subjective::naming_quality"]
