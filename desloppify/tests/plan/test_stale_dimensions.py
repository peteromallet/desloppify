"""Tests for stale and unscored subjective dimension sync in the plan."""

from __future__ import annotations

from desloppify.engine._plan.reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.stale_dimensions import (
    sync_stale_dimensions,
    sync_unscored_dimensions,
)


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
            "issues": 0,
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
            "refresh_reason": "mechanical_findings_changed",
            "stale_since": "2025-01-01T00:00:00+00:00",
        }
    return {
        "findings": {},
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
            "issues": 0,
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
    return {
        "findings": {},
        "scan_count": 1,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _state_with_mixed_dimensions(
    unscored: list[str],
    stale: list[str],
) -> dict:
    """Build a state with both unscored and stale dimensions."""
    state = _state_with_unscored_dimensions(*unscored)
    stale_state = _state_with_stale_dimensions(*stale)
    state["dimension_scores"].update(stale_state["dimension_scores"])
    state["subjective_assessments"].update(stale_state["subjective_assessments"])
    return state


# ---------------------------------------------------------------------------
# Unscored dimension sync
# ---------------------------------------------------------------------------

def test_unscored_injected_at_front():
    """Unscored IDs are prepended before existing items."""
    plan = _plan_with_queue("some_finding::file.py::abc123")
    state = _state_with_unscored_dimensions("design_coherence", "error_consistency")

    result = sync_unscored_dimensions(plan, state)
    assert len(result.injected) == 2
    # Unscored dims should be at the front, before the real finding
    assert plan["queue_order"][-1] == "some_finding::file.py::abc123"
    assert plan["queue_order"][0].startswith("subjective::")
    assert plan["queue_order"][1].startswith("subjective::")


def test_unscored_injection_unconditional():
    """Unscored dims inject even when objective items exist in queue."""
    plan = _plan_with_queue(
        "some_finding::file.py::abc123",
        "another::file.py::def456",
    )
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_unscored_dimensions(plan, state)
    assert len(result.injected) == 1
    assert plan["queue_order"][0] == "subjective::design_coherence"
    assert len(plan["queue_order"]) == 3  # 1 unscored + 2 existing


def test_unscored_pruned_after_review():
    """Once a dimension is scored, it is removed from the queue."""
    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
        "some_finding::file.py::abc123",
    )
    # Only error_consistency is still unscored; design_coherence was scored
    state = _state_with_unscored_dimensions("error_consistency")

    result = sync_unscored_dimensions(plan, state)
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

    result = sync_stale_dimensions(plan, state)
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

    result = sync_unscored_dimensions(plan, state)
    assert "subjective::error_consistency" not in result.pruned
    assert "subjective::error_consistency" in plan["queue_order"]


def test_unscored_no_injection_when_no_dimension_scores():
    plan = _plan_with_queue()
    state = {"findings": {}, "scan_count": 1}

    result = sync_unscored_dimensions(plan, state)
    assert result.injected == []
    assert result.pruned == []


def test_unscored_no_duplicates():
    """Already-present unscored IDs are not duplicated."""
    plan = _plan_with_queue("subjective::design_coherence")
    state = _state_with_unscored_dimensions("design_coherence")

    result = sync_unscored_dimensions(plan, state)
    assert result.injected == []
    assert plan["queue_order"].count("subjective::design_coherence") == 1


# ---------------------------------------------------------------------------
# Injection: empty queue + stale dimensions
# ---------------------------------------------------------------------------

def test_injects_when_queue_empty():
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    result = sync_stale_dimensions(plan, state)
    assert len(result.injected) == 2
    assert "subjective::design_coherence" in plan["queue_order"]
    assert "subjective::error_consistency" in plan["queue_order"]
    assert result.changes == 2


def test_no_injection_when_queue_has_real_items():
    plan = _plan_with_queue("some_finding::file.py::abc123")
    state = _state_with_stale_dimensions("design_coherence")

    result = sync_stale_dimensions(plan, state)
    assert result.injected == []
    assert "subjective::design_coherence" not in plan["queue_order"]


def test_no_injection_when_no_stale_dimensions():
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence")
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False

    result = sync_stale_dimensions(plan, state)
    assert result.injected == []
    assert plan["queue_order"] == []


def test_no_injection_when_no_dimension_scores():
    plan = _plan_with_queue()
    state = {"findings": {}, "scan_count": 5}

    result = sync_stale_dimensions(plan, state)
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

    result = sync_stale_dimensions(plan, state)
    assert result.pruned == ["subjective::error_consistency"]
    assert plan["queue_order"] == ["subjective::design_coherence"]


def test_prune_does_not_touch_real_finding_ids():
    plan = _plan_with_queue(
        "structural::file.py::abc123",
        "subjective::design_coherence",
    )
    # design_coherence is no longer stale
    state = {"findings": {}, "scan_count": 5, "dimension_scores": {}}

    result = sync_stale_dimensions(plan, state)
    assert "subjective::design_coherence" in result.pruned
    assert plan["queue_order"] == ["structural::file.py::abc123"]


# ---------------------------------------------------------------------------
# Full lifecycle: inject → refresh → prune → re-inject
# ---------------------------------------------------------------------------

def test_full_lifecycle():
    plan = _plan_with_queue()
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    # 1. Empty queue, stale dims → inject both
    r1 = sync_stale_dimensions(plan, state)
    assert len(r1.injected) == 2
    assert plan["queue_order"] == [
        "subjective::design_coherence",
        "subjective::error_consistency",
    ]

    # 2. User refreshes design_coherence (no longer stale)
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = False

    r2 = sync_stale_dimensions(plan, state)
    assert r2.pruned == ["subjective::design_coherence"]
    # error_consistency still there — queue not empty, so no new injection
    assert plan["queue_order"] == ["subjective::error_consistency"]
    assert r2.injected == []

    # 3. User refreshes error_consistency too → queue empties, nothing stale
    state["subjective_assessments"]["error_consistency"]["needs_review_refresh"] = False

    r3 = sync_stale_dimensions(plan, state)
    assert r3.pruned == ["subjective::error_consistency"]
    assert plan["queue_order"] == []
    assert r3.injected == []

    # 4. New mechanical change makes design_coherence stale again
    state["subjective_assessments"]["design_coherence"]["needs_review_refresh"] = True

    r4 = sync_stale_dimensions(plan, state)
    assert r4.injected == ["subjective::design_coherence"]
    assert plan["queue_order"] == ["subjective::design_coherence"]


# ---------------------------------------------------------------------------
# Reconcile must not supersede synthetic IDs
# ---------------------------------------------------------------------------

def test_reconcile_ignores_synthetic_ids():
    """Reconciliation must not treat subjective::* IDs as dead findings."""
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

    result = sync_stale_dimensions(plan, state)
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
    """When >=2 stale dims exist, auto_cluster_findings creates a cluster."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_findings

    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    changes = auto_cluster_findings(plan, state)
    assert changes >= 1
    assert "auto/stale-review" in plan["clusters"]

    cluster = plan["clusters"]["auto/stale-review"]
    assert cluster["auto"] is True
    assert cluster["cluster_key"] == "subjective::stale"
    assert set(cluster["finding_ids"]) == {
        "subjective::design_coherence",
        "subjective::error_consistency",
    }
    assert "Re-review 2 stale" in cluster["description"]
    assert "desloppify review --prepare --dimensions" in cluster["action"]
    assert "design_coherence" in cluster["action"]
    assert "error_consistency" in cluster["action"]


def test_stale_cluster_deleted_when_fresh():
    """When all dims are refreshed, the stale cluster is deleted."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_findings

    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    # Create the cluster
    auto_cluster_findings(plan, state)
    assert "auto/stale-review" in plan["clusters"]

    # Now remove subjective IDs from queue (simulating refresh + prune)
    plan["queue_order"] = []

    auto_cluster_findings(plan, state)
    assert "auto/stale-review" not in plan["clusters"]


def test_stale_cluster_updated():
    """When the stale set changes, the cluster membership updates."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_findings

    plan = _plan_with_queue(
        "subjective::design_coherence",
        "subjective::error_consistency",
    )
    state = _state_with_stale_dimensions("design_coherence", "error_consistency")

    auto_cluster_findings(plan, state)
    assert set(plan["clusters"]["auto/stale-review"]["finding_ids"]) == {
        "subjective::design_coherence",
        "subjective::error_consistency",
    }

    # A third dimension becomes stale
    plan["queue_order"].append("subjective::convention_drift")
    changes = auto_cluster_findings(plan, state)
    assert changes >= 1
    assert "subjective::convention_drift" in plan["clusters"]["auto/stale-review"]["finding_ids"]
    assert "Re-review 3 stale" in plan["clusters"]["auto/stale-review"]["description"]


def test_single_stale_dim_no_cluster():
    """Only 1 stale dim → no cluster created (below _MIN_CLUSTER_SIZE)."""
    from desloppify.engine._plan.auto_cluster import auto_cluster_findings

    plan = _plan_with_queue("subjective::design_coherence")
    state = _state_with_stale_dimensions("design_coherence")

    auto_cluster_findings(plan, state)
    assert "auto/stale-review" not in plan["clusters"]
