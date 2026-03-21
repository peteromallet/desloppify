"""Subjective auto-cluster lifecycle and regression tests."""

from __future__ import annotations

from desloppify.engine._plan.auto_cluster import (
    _repair_ghost_cluster_refs,
    auto_cluster_issues,
)
from desloppify.engine._plan.schema import empty_plan, ensure_plan_defaults


def _issue(
    fid: str,
    detector: str = "unused",
    tier: int = 1,
    file: str = "test.py",
    detail: dict | None = None,
) -> dict:
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": "high",
        "summary": f"Issue {fid}",
        "status": "open",
        "detail": detail or {},
    }


def _state_with(*issues: dict) -> dict:
    fmap = {}
    for f in issues:
        fmap[f["id"]] = f
    return {"issues": fmap, "scan_count": 5}


def test_narrative_actions_no_clusters_unchanged():
    """Without clusters, actions remain unchanged."""
    from desloppify.intelligence.narrative.action_engine import _annotate_with_clusters

    actions = [
        {"detector": "unused", "count": 5, "command": "original-cmd",
         "description": "original desc", "type": "auto_fix", "impact": 3.0},
    ]
    _annotate_with_clusters(actions, None)
    assert actions[0]["command"] == "original-cmd"
    assert actions[0]["description"] == "original desc"


# ---------------------------------------------------------------------------
# Initial review (unscored) cluster
# ---------------------------------------------------------------------------

def _unscored_state(*dim_keys: str) -> dict:
    """Build a state with unscored (placeholder) subjective dimensions."""
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
    return {
        "issues": {},
        "scan_count": 1,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def _stale_state(*dim_keys: str, score: float = 50.0) -> dict:
    """Build a state with stale (previously scored) subjective dimensions."""
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
    return {
        "issues": {},
        "scan_count": 5,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def test_initial_review_cluster_created():
    """Unscored dims are grouped into auto/initial-review."""
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::design_coherence",
        "subjective::error_consistency",
    ]
    state = _unscored_state("design_coherence", "error_consistency")

    changes = auto_cluster_issues(plan, state)
    assert changes >= 1
    assert "auto/initial-review" in plan["clusters"]

    cluster = plan["clusters"]["auto/initial-review"]
    assert cluster["auto"] is True
    assert cluster["cluster_key"] == "subjective::unscored"
    assert set(cluster["issue_ids"]) == {
        "subjective::design_coherence",
        "subjective::error_consistency",
    }
    assert "Initial review" in cluster["description"]
    assert "2 unscored" in cluster["description"]
    assert "desloppify review --prepare --dimensions" in cluster["action"]


def test_single_unscored_dim_creates_cluster():
    """Even 1 unscored dim creates an initial-review cluster (min size 1)."""
    plan = empty_plan()
    plan["queue_order"] = ["subjective::design_coherence"]
    state = _unscored_state("design_coherence")

    changes = auto_cluster_issues(plan, state)
    assert changes >= 1
    assert "auto/initial-review" in plan["clusters"]
    assert len(plan["clusters"]["auto/initial-review"]["issue_ids"]) == 1


def test_stale_and_unscored_separate_clusters():
    """Unscored and stale dims create two disjoint clusters."""
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::design_coherence",   # unscored
        "subjective::error_consistency",   # stale
        "subjective::convention_drift",    # stale
    ]
    # Mixed state: design_coherence is unscored, the other two are stale
    state = _unscored_state("design_coherence")
    stale = _stale_state("error_consistency", "convention_drift")
    state["dimension_scores"].update(stale["dimension_scores"])
    state["subjective_assessments"].update(stale["subjective_assessments"])

    changes = auto_cluster_issues(plan, state)
    assert changes >= 2

    # Initial review cluster
    assert "auto/initial-review" in plan["clusters"]
    initial = plan["clusters"]["auto/initial-review"]
    assert initial["issue_ids"] == ["subjective::design_coherence"]

    # Stale review cluster
    assert "auto/stale-review" in plan["clusters"]
    stale_cluster = plan["clusters"]["auto/stale-review"]
    assert set(stale_cluster["issue_ids"]) == {
        "subjective::error_consistency",
        "subjective::convention_drift",
    }

    # Disjoint
    initial_set = set(initial["issue_ids"])
    stale_set = set(stale_cluster["issue_ids"])
    assert initial_set.isdisjoint(stale_set)


# ---------------------------------------------------------------------------
# _repair_ghost_cluster_refs
# ---------------------------------------------------------------------------

def test_repair_ghost_cluster_refs():
    """Overrides pointing to non-existent clusters should be cleared."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    # Create an override pointing to a cluster that doesn't exist
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "cluster": "deleted-cluster",
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    # Create an override pointing to an existing cluster
    plan["clusters"]["real-cluster"] = {
        "name": "real-cluster",
        "issue_ids": ["b"],
        "auto": False,
        "cluster_key": "",
        "action": None,
        "user_modified": False,
    }
    plan["overrides"]["b"] = {
        "issue_id": "b",
        "cluster": "real-cluster",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    from desloppify.engine._state.schema import utc_now
    repaired = _repair_ghost_cluster_refs(plan, utc_now())

    assert repaired == 1
    assert plan["overrides"]["a"]["cluster"] is None
    assert plan["overrides"]["b"]["cluster"] == "real-cluster"


def test_repair_ghost_cluster_refs_no_ghosts():
    """No repairs when all cluster refs are valid."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    plan["clusters"]["my-cluster"] = {
        "name": "my-cluster",
        "issue_ids": ["a"],
        "auto": False,
        "cluster_key": "",
        "action": None,
        "user_modified": False,
    }
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "cluster": "my-cluster",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    from desloppify.engine._state.schema import utc_now
    repaired = _repair_ghost_cluster_refs(plan, utc_now())
    assert repaired == 0


def test_auto_cluster_runs_repair():
    """auto_cluster_issues should repair ghost refs as part of its run."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    # Add a ghost override
    plan["overrides"]["ghost"] = {
        "issue_id": "ghost",
        "cluster": "nonexistent",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    state = _state_with()  # empty state
    changes = auto_cluster_issues(plan, state)

    # The ghost ref should have been repaired
    assert plan["overrides"]["ghost"]["cluster"] is None
    assert changes >= 1


# ---------------------------------------------------------------------------
# Under-target regression tests (#186)
# ---------------------------------------------------------------------------

def _under_target_state(*dim_keys: str, score: float = 70.0) -> dict:
    """Build a state with scored, current (NOT stale), below-target dimensions.

    These dimensions have a real score, no placeholder flag, and no
    needs_review_refresh — they are simply below the target threshold.
    """
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
            # No placeholder, no needs_review_refresh → current but below target
        }
    return {
        "issues": {},
        "scan_count": 5,
        "dimension_scores": dim_scores,
        "subjective_assessments": assessments,
    }


def test_stale_cluster_uses_actual_stale_ids():
    """Under-target (not stale) IDs must NOT appear in auto/stale-review."""
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::design_coherence",    # under-target (current, below target)
        "subjective::error_consistency",   # under-target
        "subjective::convention_drift",    # actually stale
        "subjective::naming_quality",      # actually stale
    ]

    # Build mixed state: two under-target + two stale
    ut = _under_target_state("design_coherence", "error_consistency", score=70.0)
    stale = _stale_state("convention_drift", "naming_quality", score=50.0)
    state = {
        "issues": {},
        "scan_count": 5,
        "dimension_scores": {
            **ut["dimension_scores"],
            **stale["dimension_scores"],
        },
        "subjective_assessments": {
            **ut["subjective_assessments"],
            **stale["subjective_assessments"],
        },
    }

    auto_cluster_issues(plan, state)

    # Stale cluster should only contain the actually-stale dimensions
    assert "auto/stale-review" in plan["clusters"]
    stale_cluster = plan["clusters"]["auto/stale-review"]
    stale_members = set(stale_cluster["issue_ids"])
    assert stale_members == {
        "subjective::convention_drift",
        "subjective::naming_quality",
    }
    # Under-target IDs must NOT be in the stale cluster
    assert "subjective::design_coherence" not in stale_members
    assert "subjective::error_consistency" not in stale_members


def test_under_target_not_evicted_by_auto_cluster():
    """auto_cluster_sync no longer evicts under-target IDs — sync_stale owns that."""
    from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions

    plan = empty_plan()
    ut = _under_target_state("design_coherence", "error_consistency", score=70.0)

    # Step 1: sync_stale injects when no objective backlog
    state_no_obj = {**ut, "issues": {}}
    sync_subjective_dimensions(plan, state_no_obj)

    order = plan["queue_order"]
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order

    # Step 2: objective issues reappear — auto_cluster should NOT evict
    state_with_obj = {
        **ut,
        "issues": {
            "u1": _issue("u1", "unused"),
            "u2": _issue("u2", "unused"),
        },
    }
    auto_cluster_issues(plan, state_with_obj)

    order = plan["queue_order"]
    # Under-target IDs remain — sync_stale is the authority on eviction
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order


def test_stale_ids_not_evicted_by_auto_cluster():
    """Stale IDs survive both auto-cluster and sync when objective backlog exists."""
    from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions

    plan = empty_plan()
    stale_state = _stale_state("design_coherence", "error_consistency", score=50.0)
    plan["queue_order"] = [
        "subjective::design_coherence",
        "subjective::error_consistency",
    ]

    # Step 1: no objective items -> stale IDs remain present
    state_no_obj = {**stale_state, "issues": {}}
    auto_cluster_issues(plan, state_no_obj)
    order = plan["queue_order"]
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order

    # Step 2: objective issues reappear -> auto_cluster should NOT evict
    state_with_obj = {
        **stale_state,
        "issues": {
            "u1": _issue("u1", "unused"),
            "u2": _issue("u2", "unused"),
        },
    }
    auto_cluster_issues(plan, state_with_obj)
    order = plan["queue_order"]
    # IDs remain after auto_cluster — it no longer evicts
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order

    # sync_stale also preserves them and keeps them ahead of objective work
    result = sync_subjective_dimensions(plan, state_with_obj)
    order = plan["queue_order"]
    assert order[:2] == [
        "subjective::design_coherence",
        "subjective::error_consistency",
    ]
    assert "u1" in order
    assert "u2" in order
    assert result.pruned == []


def test_under_target_lifecycle_with_sync_stale():
    """Full lifecycle: under-target reviews defer only mid-cycle, then reappear."""
    from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions

    plan = empty_plan()
    ut = _under_target_state("design_coherence", "error_consistency", score=70.0)

    # Phase 1: sync_stale injects, auto_cluster creates cluster
    state_empty = {**ut, "issues": {}}
    sync_subjective_dimensions(plan, state_empty)

    order = plan["queue_order"]
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order

    auto_cluster_issues(plan, state_empty)
    assert "auto/under-target-review" in plan["clusters"]

    # Phase 2: objective issues appear mid-cycle — sync_stale evicts them
    plan["plan_start_scores"] = {"strict": 70.0}
    state_obj = {
        **ut,
        "issues": {
            "u1": _issue("u1", "unused"),
            "u2": _issue("u2", "unused"),
        },
    }
    sync_subjective_dimensions(plan, state_obj)
    order = plan["queue_order"]
    assert "subjective::design_coherence" not in order
    assert "subjective::error_consistency" not in order

    # Phase 3: objective resolved again — sync_stale re-injects
    state_empty2 = {**ut, "issues": {}}
    sync_subjective_dimensions(plan, state_empty2)
    order = plan["queue_order"]
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order
