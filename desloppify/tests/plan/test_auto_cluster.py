"""Tests for auto-clustering algorithm."""

from __future__ import annotations

from desloppify.engine._plan.auto_cluster import (
    auto_cluster_findings,
    _cluster_name_from_key,
    _grouping_key,
)
from desloppify.engine._plan.operations import (
    create_cluster,
    add_to_cluster,
    remove_from_cluster,
)
from desloppify.engine._plan.schema import empty_plan, ensure_plan_defaults
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    build_work_queue,
    _collapse_clusters,
)
from desloppify.engine._work_queue.ranking import item_sort_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(fid: str, detector: str = "unused", tier: int = 1,
             file: str = "test.py", detail: dict | None = None) -> dict:
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": "high",
        "summary": f"Finding {fid}",
        "status": "open",
        "detail": detail or {},
    }


def _state_with(*findings: dict) -> dict:
    fmap = {}
    for f in findings:
        fmap[f["id"]] = f
    return {"findings": fmap, "scan_count": 5}


# ---------------------------------------------------------------------------
# Grouping key tests
# ---------------------------------------------------------------------------

def test_grouping_key_auto_fix():
    from desloppify.core.registry import DETECTORS
    f = _finding("a", "unused")
    meta = DETECTORS.get("unused")
    key = _grouping_key(f, meta)
    assert key == "auto::unused"


def test_grouping_key_review():
    from desloppify.core.registry import DETECTORS
    f = _finding("a", "review", detail={"dimension": "abstraction_fitness"})
    meta = DETECTORS.get("review")
    key = _grouping_key(f, meta)
    assert key == "review::abstraction_fitness"


def test_grouping_key_needs_judgment_with_kind():
    from desloppify.core.registry import DETECTORS
    f = _finding("a", "dict_keys", detail={"kind": "phantom_read"})
    meta = DETECTORS.get("dict_keys")
    key = _grouping_key(f, meta)
    assert key == "typed::dict_keys::phantom_read"


def test_grouping_key_structural():
    from desloppify.core.registry import DETECTORS
    f = _finding("a", "structural", file="src/big_file.py")
    meta = DETECTORS.get("structural")
    key = _grouping_key(f, meta)
    assert key == "file::structural::big_file.py"


def test_grouping_key_unknown_detector():
    f = _finding("a", "totally_unknown")
    key = _grouping_key(f, None)
    assert key == "detector::totally_unknown"


# ---------------------------------------------------------------------------
# Cluster name from key
# ---------------------------------------------------------------------------

def test_cluster_name_auto():
    assert _cluster_name_from_key("auto::unused") == "auto/unused"


def test_cluster_name_typed():
    assert _cluster_name_from_key("typed::dict_keys::phantom_read") == "auto/dict_keys-phantom_read"


def test_cluster_name_file():
    assert _cluster_name_from_key("file::structural::big.py") == "auto/structural-big.py"


def test_cluster_name_review():
    assert _cluster_name_from_key("review::abstraction_fitness") == "auto/review-abstraction_fitness"


# ---------------------------------------------------------------------------
# auto_cluster_findings — core behavior
# ---------------------------------------------------------------------------

def test_auto_cluster_creates_cluster_from_findings():
    plan = empty_plan()
    state = _state_with(
        _finding("u1", "unused"),
        _finding("u2", "unused"),
        _finding("u3", "unused"),
    )

    changes = auto_cluster_findings(plan, state)
    assert changes >= 1
    assert "auto/unused" in plan["clusters"]
    cluster = plan["clusters"]["auto/unused"]
    assert cluster["auto"] is True
    assert set(cluster["finding_ids"]) == {"u1", "u2", "u3"}
    assert cluster["action"] is not None  # should have fix command


def test_auto_cluster_skips_singletons():
    plan = empty_plan()
    state = _state_with(
        _finding("u1", "unused"),
        _finding("s1", "security"),  # only one security finding
    )

    auto_cluster_findings(plan, state)
    # unused has only 1 finding too, so neither should be clustered
    assert "auto/unused" not in plan["clusters"]
    assert "auto/security" not in plan["clusters"]


def test_auto_cluster_skips_non_open():
    plan = empty_plan()
    f1 = _finding("u1", "unused")
    f2 = _finding("u2", "unused")
    f2["status"] = "resolved"
    state = _state_with(f1, f2)

    auto_cluster_findings(plan, state)
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_skips_suppressed():
    plan = empty_plan()
    f1 = _finding("u1", "unused")
    f2 = _finding("u2", "unused")
    f2["suppressed"] = True
    state = _state_with(f1, f2)

    auto_cluster_findings(plan, state)
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_skips_manual_cluster_members():
    plan = empty_plan()
    ensure_plan_defaults(plan)
    # Create manual cluster
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["u1"])

    state = _state_with(
        _finding("u1", "unused"),
        _finding("u2", "unused"),
    )

    auto_cluster_findings(plan, state)
    # u1 is in a manual cluster, so only u2 is available — singleton, no auto-cluster
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_replaces_membership_on_rescan():
    plan = empty_plan()
    state = _state_with(
        _finding("u1", "unused"),
        _finding("u2", "unused"),
    )
    auto_cluster_findings(plan, state)
    assert set(plan["clusters"]["auto/unused"]["finding_ids"]) == {"u1", "u2"}

    # Rescan: u2 gone, u3 added
    state2 = _state_with(
        _finding("u1", "unused"),
        _finding("u3", "unused"),
    )
    changes = auto_cluster_findings(plan, state2)
    assert changes >= 1
    assert set(plan["clusters"]["auto/unused"]["finding_ids"]) == {"u1", "u3"}


def test_auto_cluster_user_modified_merges():
    plan = empty_plan()
    state = _state_with(
        _finding("u1", "unused"),
        _finding("u2", "unused"),
    )
    auto_cluster_findings(plan, state)
    # Simulate user removing u2 — sets user_modified
    remove_from_cluster(plan, "auto/unused", ["u2"])
    assert plan["clusters"]["auto/unused"]["user_modified"] is True

    # Rescan: u2 still there, u3 added
    state2 = _state_with(
        _finding("u1", "unused"),
        _finding("u2", "unused"),
        _finding("u3", "unused"),
    )
    auto_cluster_findings(plan, state2)
    # user_modified: merges new findings in, doesn't replace
    ids = set(plan["clusters"]["auto/unused"]["finding_ids"])
    assert "u1" in ids
    assert "u3" in ids  # new finding added


def test_auto_cluster_deletes_stale():
    plan = empty_plan()
    state = _state_with(
        _finding("u1", "unused"),
        _finding("u2", "unused"),
    )
    auto_cluster_findings(plan, state)
    assert "auto/unused" in plan["clusters"]

    # All findings resolved
    state2 = _state_with()
    changes = auto_cluster_findings(plan, state2)
    assert changes >= 1
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_no_tier_on_cluster():
    plan = empty_plan()
    state = _state_with(
        _finding("a", "unused", tier=2),
        _finding("b", "unused", tier=1),
        _finding("c", "unused", tier=3),
    )
    auto_cluster_findings(plan, state)
    # Clusters should not carry a tier field
    assert "tier" not in plan["clusters"]["auto/unused"]


# ---------------------------------------------------------------------------
# Queue collapsing
# ---------------------------------------------------------------------------

def test_collapse_clusters_replaces_members():
    plan = empty_plan()
    plan["clusters"]["auto/unused"] = {
        "name": "auto/unused",
        "auto": True,
        "cluster_key": "auto::unused",
        "finding_ids": ["u1", "u2"],
        "description": "Remove 2 unused findings",
        "action": "desloppify fix unused-imports --dry-run",
        "user_modified": False,
    }

    items = [
        {"id": "u1", "kind": "finding", "effective_tier": 1, "tier": 1,
         "detector": "unused", "confidence": "high", "detail": {}},
        {"id": "u2", "kind": "finding", "effective_tier": 1, "tier": 1,
         "detector": "unused", "confidence": "high", "detail": {}},
        {"id": "other", "kind": "finding", "effective_tier": 2, "tier": 2,
         "detector": "structural", "confidence": "medium", "detail": {}},
    ]

    result = _collapse_clusters(items, plan)
    kinds = {item["kind"] for item in result}
    assert "cluster" in kinds
    cluster_items = [i for i in result if i["kind"] == "cluster"]
    assert len(cluster_items) == 1
    assert cluster_items[0]["id"] == "auto/unused"
    assert cluster_items[0]["member_count"] == 2
    # "other" stays as individual
    non_cluster = [i for i in result if i["kind"] != "cluster"]
    assert len(non_cluster) == 1
    assert non_cluster[0]["id"] == "other"


def test_collapse_clusters_skips_manual():
    plan = empty_plan()
    plan["clusters"]["my-group"] = {
        "name": "my-group",
        "auto": False,
        "finding_ids": ["u1"],
        "description": "manual",
    }

    items = [
        {"id": "u1", "kind": "finding", "effective_tier": 1, "tier": 1,
         "detector": "unused", "confidence": "high", "detail": {}},
    ]

    result = _collapse_clusters(items, plan)
    # Manual clusters should not be collapsed
    assert all(i["kind"] == "finding" for i in result)


def test_cluster_sort_key_before_findings():
    cluster_item = {
        "kind": "cluster", "action_type": "auto_fix",
        "member_count": 5, "id": "auto/unused",
    }
    finding_item = {
        "kind": "finding", "effective_tier": 1, "tier": 1,
        "confidence": "high", "detector": "unused", "detail": {},
        "id": "some-finding",
    }
    assert item_sort_key(cluster_item) < item_sort_key(finding_item)


def test_cluster_sort_auto_fix_before_refactor():
    auto_fix = {
        "kind": "cluster", "action_type": "auto_fix",
        "member_count": 3, "id": "auto/unused",
    }
    refactor = {
        "kind": "cluster", "action_type": "refactor",
        "member_count": 10, "id": "auto/structural",
    }
    assert item_sort_key(auto_fix) < item_sort_key(refactor)


# ---------------------------------------------------------------------------
# create_cluster rejects auto/ prefix
# ---------------------------------------------------------------------------

def test_create_cluster_rejects_auto_prefix():
    plan = empty_plan()
    ensure_plan_defaults(plan)
    try:
        create_cluster(plan, "auto/my-cluster")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "auto/" in str(e)


# ---------------------------------------------------------------------------
# ensure_plan_defaults normalizes new fields
# ---------------------------------------------------------------------------

def test_ensure_plan_defaults_adds_cluster_fields():
    plan = empty_plan()
    plan["clusters"]["test"] = {
        "name": "test",
        "finding_ids": ["a"],
    }
    ensure_plan_defaults(plan)
    cluster = plan["clusters"]["test"]
    assert cluster["auto"] is False
    assert cluster["cluster_key"] == ""
    assert cluster["action"] is None
    assert cluster["user_modified"] is False


# ---------------------------------------------------------------------------
# Integration: build_work_queue with collapse
# ---------------------------------------------------------------------------

def test_build_work_queue_collapses_clusters():
    state = _state_with(
        _finding("u1", "unused", tier=1),
        _finding("u2", "unused", tier=1),
    )
    plan = empty_plan()
    auto_cluster_findings(plan, state)

    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            plan=plan,
            count=10,
            collapse_clusters=True,
        ),
    )
    cluster_items = [i for i in result["items"] if i.get("kind") == "cluster"]
    assert len(cluster_items) == 1
    assert cluster_items[0]["member_count"] == 2


def test_build_work_queue_no_collapse_when_drilling():
    state = _state_with(
        _finding("u1", "unused", tier=1),
        _finding("u2", "unused", tier=1),
    )
    plan = empty_plan()
    auto_cluster_findings(plan, state)

    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            plan=plan,
            count=10,
            cluster="auto/unused",  # drilling into cluster
        ),
    )
    # When drilling, items should be individual findings, not collapsed
    for item in result["items"]:
        assert item.get("kind") != "cluster"


# ---------------------------------------------------------------------------
# _generate_action always returns something
# ---------------------------------------------------------------------------

def test_generate_action_always_returns_something():
    """Every detector/subtype combination must produce a non-None action."""
    from desloppify.core.registry import DETECTORS
    from desloppify.engine._plan.auto_cluster import _generate_action

    # No metadata → fallback
    assert _generate_action(None, None) == "review and fix each finding"

    # Every registered detector, with and without subtype
    for name, meta in DETECTORS.items():
        result = _generate_action(meta, None)
        assert result, f"_generate_action({name}, None) returned empty"

        result_sub = _generate_action(meta, "some_subtype")
        assert result_sub, f"_generate_action({name}, 'some_subtype') returned empty"


def test_generate_action_strips_subtype_examples():
    """Guidance with ' — ' should be stripped to the core verb for subtypes."""
    from desloppify.engine._plan.auto_cluster import _strip_guidance_examples

    assert _strip_guidance_examples("fix code smells — dead useEffect, empty if chains") == "fix code smells"
    assert _strip_guidance_examples("fix dict key mismatches — dead writes are likely dead code") == "fix dict key mismatches"
    # No dash → keep as-is
    assert _strip_guidance_examples("review and fix each finding") == "review and fix each finding"


# ---------------------------------------------------------------------------
# Manual cluster accepts action
# ---------------------------------------------------------------------------

def test_manual_cluster_accepts_action():
    plan = empty_plan()
    ensure_plan_defaults(plan)
    cluster = create_cluster(plan, "my-task", description="Refactor auth", action="refactor auth flow")
    assert cluster["action"] == "refactor auth flow"
    assert cluster["description"] == "Refactor auth"


# ---------------------------------------------------------------------------
# Collapse fallback action
# ---------------------------------------------------------------------------

def test_collapse_fallback_action():
    """Collapsed clusters always have a primary_command, even if action is None."""
    plan = empty_plan()
    plan["clusters"]["auto/test"] = {
        "name": "auto/test",
        "auto": True,
        "cluster_key": "auto::test",
        "finding_ids": ["t1", "t2"],
        "description": "Fix 2 test issues",
        "action": None,  # no action set
        "user_modified": False,
    }

    items = [
        {"id": "t1", "kind": "finding", "effective_tier": 1, "tier": 1,
         "detector": "test", "confidence": "high", "detail": {}},
        {"id": "t2", "kind": "finding", "effective_tier": 1, "tier": 1,
         "detector": "test", "confidence": "high", "detail": {}},
    ]

    result = _collapse_clusters(items, plan)
    cluster_items = [i for i in result if i["kind"] == "cluster"]
    assert len(cluster_items) == 1
    assert cluster_items[0]["primary_command"] is not None
    assert "desloppify next --cluster" in cluster_items[0]["primary_command"]


# ---------------------------------------------------------------------------
# Narrative actions mention clusters
# ---------------------------------------------------------------------------

def test_narrative_actions_mention_clusters():
    """When clusters exist, narrative actions should reference them."""
    from desloppify.intelligence.narrative.action_engine import _annotate_with_clusters

    actions = [
        {"detector": "unused", "count": 5, "command": "desloppify fix unused-imports --dry-run",
         "description": "5 unused findings", "type": "auto_fix", "impact": 3.0},
    ]
    clusters = {
        "auto/unused": {
            "name": "auto/unused",
            "auto": True,
            "cluster_key": "auto::unused",
            "finding_ids": ["u1", "u2", "u3", "u4", "u5"],
        },
    }

    _annotate_with_clusters(actions, clusters)
    assert actions[0].get("cluster_count") == 1
    assert actions[0].get("clusters") == ["auto/unused"]
    assert "cluster" in actions[0]["description"]
    assert actions[0]["command"] == "desloppify next"


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


def _stale_state(*dim_keys: str, score: float = 50.0) -> dict:
    """Build a state with stale (previously scored) subjective dimensions."""
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


def test_initial_review_cluster_created():
    """Unscored dims are grouped into auto/initial-review."""
    plan = empty_plan()
    plan["queue_order"] = [
        "subjective::design_coherence",
        "subjective::error_consistency",
    ]
    state = _unscored_state("design_coherence", "error_consistency")

    changes = auto_cluster_findings(plan, state)
    assert changes >= 1
    assert "auto/initial-review" in plan["clusters"]

    cluster = plan["clusters"]["auto/initial-review"]
    assert cluster["auto"] is True
    assert cluster["cluster_key"] == "subjective::unscored"
    assert set(cluster["finding_ids"]) == {
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

    changes = auto_cluster_findings(plan, state)
    assert changes >= 1
    assert "auto/initial-review" in plan["clusters"]
    assert len(plan["clusters"]["auto/initial-review"]["finding_ids"]) == 1


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

    changes = auto_cluster_findings(plan, state)
    assert changes >= 2

    # Initial review cluster
    assert "auto/initial-review" in plan["clusters"]
    initial = plan["clusters"]["auto/initial-review"]
    assert initial["finding_ids"] == ["subjective::design_coherence"]

    # Stale review cluster
    assert "auto/stale-review" in plan["clusters"]
    stale_cluster = plan["clusters"]["auto/stale-review"]
    assert set(stale_cluster["finding_ids"]) == {
        "subjective::error_consistency",
        "subjective::convention_drift",
    }

    # Disjoint
    initial_set = set(initial["finding_ids"])
    stale_set = set(stale_cluster["finding_ids"])
    assert initial_set.isdisjoint(stale_set)
