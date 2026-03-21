"""Tests for auto-clustering algorithm."""

from __future__ import annotations

from desloppify.engine._plan.auto_cluster import (
    _repair_ghost_cluster_refs,
    auto_cluster_issues,
)
from desloppify.engine._plan.cluster_semantics import (
    EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
    EXECUTION_POLICY_PLANNED_ONLY,
)
from desloppify.engine._plan.cluster_strategy import (
    cluster_name_from_key,
    grouping_key,
)
from desloppify.engine._plan.operations.cluster import (
    add_to_cluster,
    create_cluster,
    remove_from_cluster,
)
from desloppify.engine._plan.schema import empty_plan, ensure_plan_defaults
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    build_work_queue,
)
from desloppify.engine._work_queue.plan_order import (
    collapse_clusters as _collapse_clusters,
)
from desloppify.engine._work_queue.plan_order import (
    filter_cluster_focus,
)
from desloppify.engine._work_queue.ranking import item_sort_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issue(fid: str, detector: str = "unused", tier: int = 1,
             file: str = "test.py", detail: dict | None = None) -> dict:
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
    return {"work_items": fmap, "issues": fmap, "scan_count": 5}


# ---------------------------------------------------------------------------
# Grouping key tests
# ---------------------------------------------------------------------------

def test_grouping_key_auto_fix():
    from desloppify.base.registry import DETECTORS
    f = _issue("a", "unused")
    meta = DETECTORS.get("unused")
    key = grouping_key(f, meta)
    assert key == "auto::unused"


def test_grouping_key_review():
    from desloppify.base.registry import DETECTORS
    f = _issue("a", "review", detail={"dimension": "abstraction_fitness"})
    meta = DETECTORS.get("review")
    key = grouping_key(f, meta)
    assert key == "review::abstraction_fitness"


def test_grouping_key_judgment_required_returns_none():
    from desloppify.base.registry import DETECTORS
    # needs_judgment=True detectors return None (flow through review, not auto-task)
    f = _issue("a", "dict_keys", detail={"kind": "phantom_read"})
    meta = DETECTORS.get("dict_keys")
    assert grouping_key(f, meta) is None

    f2 = _issue("a", "structural", file="src/big_file.py")
    meta2 = DETECTORS.get("structural")
    assert grouping_key(f2, meta2) is None

    f3 = _issue("a", "smells")
    meta3 = DETECTORS.get("smells")
    assert grouping_key(f3, meta3) is None


def test_grouping_key_unknown_detector():
    f = _issue("a", "totally_unknown")
    key = grouping_key(f, None)
    assert key == "detector::totally_unknown"


# ---------------------------------------------------------------------------
# Cluster name from key
# ---------------------------------------------------------------------------

def test_cluster_name_auto():
    assert cluster_name_from_key("auto::unused") == "auto/unused"


def test_cluster_name_typed():
    assert cluster_name_from_key("typed::dict_keys::phantom_read") == "auto/dict_keys-phantom_read"


def test_cluster_name_file():
    assert cluster_name_from_key("file::structural::big.py") == "auto/structural-big.py"


def test_cluster_name_review():
    assert cluster_name_from_key("review::abstraction_fitness") == "auto/review-abstraction_fitness"


# ---------------------------------------------------------------------------
# auto_cluster_issues — core behavior
# ---------------------------------------------------------------------------

def test_auto_cluster_creates_cluster_from_issues():
    plan = empty_plan()
    state = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
        _issue("u3", "unused"),
    )

    changes = auto_cluster_issues(plan, state)
    assert changes >= 1
    assert "auto/unused" in plan["clusters"]
    cluster = plan["clusters"]["auto/unused"]
    assert cluster["auto"] is True
    assert set(cluster["issue_ids"]) == {"u1", "u2", "u3"}
    assert cluster["action"] is not None  # should have fix command
    assert cluster["action_type"] == "auto_fix"
    assert cluster["execution_policy"] == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE


def test_auto_cluster_skips_singletons():
    plan = empty_plan()
    state = _state_with(
        _issue("u1", "unused"),
        _issue("s1", "security"),  # only one security issue
    )

    auto_cluster_issues(plan, state)
    # unused has only 1 issue too, so neither should be clustered
    assert "auto/unused" not in plan["clusters"]
    assert "auto/security" not in plan["clusters"]


def test_auto_cluster_skips_non_open():
    plan = empty_plan()
    f1 = _issue("u1", "unused")
    f2 = _issue("u2", "unused")
    f2["status"] = "resolved"
    state = _state_with(f1, f2)

    auto_cluster_issues(plan, state)
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_skips_suppressed():
    plan = empty_plan()
    f1 = _issue("u1", "unused")
    f2 = _issue("u2", "unused")
    f2["suppressed"] = True
    state = _state_with(f1, f2)

    auto_cluster_issues(plan, state)
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_skips_manual_cluster_members():
    plan = empty_plan()
    ensure_plan_defaults(plan)
    # Create manual cluster
    create_cluster(plan, "my-cluster")
    add_to_cluster(plan, "my-cluster", ["u1"])

    state = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
    )

    auto_cluster_issues(plan, state)
    # u1 is in a manual cluster, so only u2 is available — singleton, no auto-cluster
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_replaces_membership_on_rescan():
    plan = empty_plan()
    state = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
    )
    auto_cluster_issues(plan, state)
    assert set(plan["clusters"]["auto/unused"]["issue_ids"]) == {"u1", "u2"}

    # Rescan: u2 gone, u3 added
    state2 = _state_with(
        _issue("u1", "unused"),
        _issue("u3", "unused"),
    )
    changes = auto_cluster_issues(plan, state2)
    assert changes >= 1
    assert set(plan["clusters"]["auto/unused"]["issue_ids"]) == {"u1", "u3"}


def test_auto_cluster_user_modified_merges():
    plan = empty_plan()
    state = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
    )
    auto_cluster_issues(plan, state)
    # Simulate user removing u2 — sets user_modified
    remove_from_cluster(plan, "auto/unused", ["u2"])
    assert plan["clusters"]["auto/unused"]["user_modified"] is True

    # Rescan: u2 still there, u3 added
    state2 = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
        _issue("u3", "unused"),
    )
    auto_cluster_issues(plan, state2)
    # user_modified: merges new issues in, doesn't replace
    ids = set(plan["clusters"]["auto/unused"]["issue_ids"])
    assert "u1" in ids
    assert "u3" in ids  # new issue added


def test_remove_from_cluster_clears_focus_when_cluster_becomes_non_actionable():
    plan = empty_plan()
    ensure_plan_defaults(plan)
    create_cluster(plan, "manual/cleanup")
    add_to_cluster(plan, "manual/cleanup", ["u1"])
    plan["queue_order"] = ["u1"]
    plan["active_cluster"] = "manual/cleanup"

    removed = remove_from_cluster(plan, "manual/cleanup", ["u1"])

    assert removed == 1
    assert plan["clusters"]["manual/cleanup"]["issue_ids"] == []
    assert plan["active_cluster"] is None


def test_remove_from_cluster_also_clears_step_issue_refs():
    plan = empty_plan()
    ensure_plan_defaults(plan)
    create_cluster(plan, "manual/cleanup")
    add_to_cluster(plan, "manual/cleanup", ["u1", "u2"])
    plan["clusters"]["manual/cleanup"]["action_steps"] = [
        {"title": "Fix first issue", "issue_refs": ["u1"]},
        {"title": "Fix both issues", "issue_refs": ["u1", "u2"]},
        {"title": "Keep second issue", "issue_refs": ["u2"]},
    ]

    removed = remove_from_cluster(plan, "manual/cleanup", ["u1"])

    assert removed == 1
    assert plan["clusters"]["manual/cleanup"]["issue_ids"] == ["u2"]
    assert plan["clusters"]["manual/cleanup"]["action_steps"][0]["issue_refs"] == []
    assert plan["clusters"]["manual/cleanup"]["action_steps"][1]["issue_refs"] == ["u2"]
    assert plan["clusters"]["manual/cleanup"]["action_steps"][2]["issue_refs"] == ["u2"]


def test_auto_cluster_deletes_stale():
    plan = empty_plan()
    state = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
    )
    auto_cluster_issues(plan, state)
    assert "auto/unused" in plan["clusters"]

    # All issues resolved
    state2 = _state_with()
    changes = auto_cluster_issues(plan, state2)
    assert changes >= 1
    assert "auto/unused" not in plan["clusters"]


def test_auto_cluster_no_tier_on_cluster():
    plan = empty_plan()
    state = _state_with(
        _issue("a", "unused", tier=2),
        _issue("b", "unused", tier=1),
        _issue("c", "unused", tier=3),
    )
    auto_cluster_issues(plan, state)
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
        "issue_ids": ["u1", "u2"],
        "description": "Remove 2 unused issues",
        "action": "desloppify autofix unused-imports --dry-run",
        "user_modified": False,
    }

    items = [
        {"id": "u1", "kind": "issue", "tier": 1,
         "detector": "unused", "confidence": "high", "detail": {}},
        {"id": "u2", "kind": "issue", "tier": 1,
         "detector": "unused", "confidence": "high", "detail": {}},
        {"id": "other", "kind": "issue", "tier": 2,
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
        "issue_ids": ["u1"],
        "description": "manual",
    }

    items = [
        {"id": "u1", "kind": "issue", "tier": 1,
         "detector": "unused", "confidence": "high", "detail": {}},
    ]

    result = _collapse_clusters(items, plan)
    # Manual clusters should not be collapsed
    assert all(i["kind"] == "issue" for i in result)


def test_cluster_sort_key_before_issues():
    cluster_item = {
        "kind": "cluster", "action_type": "auto_fix",
        "member_count": 5, "id": "auto/unused",
    }
    issue_item = {
        "kind": "issue", "tier": 1,
        "confidence": "high", "detector": "unused", "detail": {},
        "id": "some-issue",
    }
    assert item_sort_key(cluster_item) < item_sort_key(issue_item)


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
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "auto/" in str(e)


# ---------------------------------------------------------------------------
# ensure_plan_defaults normalizes new fields
# ---------------------------------------------------------------------------

def test_ensure_plan_defaults_adds_cluster_fields():
    plan = empty_plan()
    plan["clusters"]["test"] = {
        "name": "test",
        "issue_ids": ["a"],
    }
    ensure_plan_defaults(plan)
    cluster = plan["clusters"]["test"]
    assert cluster["auto"] is False
    assert cluster["cluster_key"] == ""
    assert cluster["action"] is None
    assert cluster["action_type"] == "manual_fix"
    assert cluster["execution_policy"] == EXECUTION_POLICY_PLANNED_ONLY
    assert cluster["user_modified"] is False


def test_ensure_plan_defaults_backfills_legacy_autofix_cluster_semantics():
    plan = empty_plan()
    plan["clusters"]["auto/unused"] = {
        "name": "auto/unused",
        "auto": True,
        "issue_ids": ["u1"],
        "action": "desloppify autofix unused-imports --dry-run",
    }

    ensure_plan_defaults(plan)

    cluster = plan["clusters"]["auto/unused"]
    assert cluster["action_type"] == "auto_fix"
    assert cluster["execution_policy"] == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE


# ---------------------------------------------------------------------------
# Integration: build_work_queue with collapse
# ---------------------------------------------------------------------------

def test_build_work_queue_collapses_clusters():
    state = _state_with(
        _issue("u1", "unused", tier=1),
        _issue("u2", "unused", tier=1),
    )
    plan = empty_plan()
    auto_cluster_issues(plan, state)

    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            plan=plan,
            count=10,
        ),
    )
    # Collapse is now a caller responsibility
    items = _collapse_clusters(result["items"], plan)
    cluster_items = [i for i in items if i.get("kind") == "cluster"]
    assert len(cluster_items) == 1
    assert cluster_items[0]["member_count"] == 2


def test_build_work_queue_no_collapse_when_drilling():
    state = _state_with(
        _issue("u1", "unused", tier=1),
        _issue("u2", "unused", tier=1),
    )
    plan = empty_plan()
    auto_cluster_issues(plan, state)

    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            plan=plan,
            count=10,
        ),
    )
    # Apply cluster focus at the call site (as production code now does)
    items = filter_cluster_focus(result["items"], plan, "auto/unused")
    # When drilling, items should be individual issues, not collapsed
    for item in items:
        assert item.get("kind") != "cluster"


# ---------------------------------------------------------------------------
# _generate_action always returns something
# ---------------------------------------------------------------------------

def test_generate_action_always_returns_something():
    """Every detector/subtype combination must produce a non-None action."""
    from desloppify.base.registry import DETECTORS
    from desloppify.engine._plan.cluster_strategy import (
        generate_action as _generate_action,
    )

    # No metadata → fallback
    assert _generate_action(None, None) == "review and fix each issue"

    # Every registered detector, with and without subtype
    for name, meta in DETECTORS.items():
        result = _generate_action(meta, None)
        assert result, f"_generate_action({name}, None) returned empty"

        result_sub = _generate_action(meta, "some_subtype")
        assert result_sub, f"_generate_action({name}, 'some_subtype') returned empty"


def test_generate_action_strips_subtype_examples():
    """Guidance with ' — ' should be stripped to the core verb for subtypes."""
    from desloppify.engine._plan.cluster_strategy import (
        strip_guidance_examples as _strip_guidance_examples,
    )

    assert _strip_guidance_examples("fix code smells — dead useEffect, empty if chains") == "fix code smells"
    assert _strip_guidance_examples("fix dict key mismatches — dead writes are likely dead code") == "fix dict key mismatches"
    # No dash → keep as-is
    assert _strip_guidance_examples("review and fix each issue") == "review and fix each issue"


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
        "issue_ids": ["t1", "t2"],
        "description": "Fix 2 test issues",
        "action": None,  # no action set
        "user_modified": False,
    }

    items = [
        {"id": "t1", "kind": "issue", "tier": 1,
         "detector": "test", "confidence": "high", "detail": {}},
        {"id": "t2", "kind": "issue", "tier": 1,
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
        {"detector": "unused", "count": 5, "command": "desloppify autofix unused-imports --dry-run",
         "description": "5 unused issues", "type": "auto_fix", "impact": 3.0},
    ]
    clusters = {
        "auto/unused": {
            "name": "auto/unused",
            "auto": True,
            "cluster_key": "auto::unused",
            "issue_ids": ["u1", "u2", "u3", "u4", "u5"],
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


def test_repair_missing_override_for_cluster_member():
    """Issue in cluster.issue_ids but no override → create override."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    plan["clusters"]["my-cluster"] = {
        "name": "my-cluster",
        "issue_ids": ["a", "b"],
        "auto": False,
        "cluster_key": "",
        "action": None,
        "user_modified": False,
    }
    # Only "a" has an override; "b" has none
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "cluster": "my-cluster",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    from desloppify.engine._state.schema import utc_now
    repaired = _repair_ghost_cluster_refs(plan, utc_now())

    assert repaired == 1
    assert "b" in plan["overrides"]
    assert plan["overrides"]["b"]["cluster"] == "my-cluster"


def test_repair_override_points_wrong_cluster():
    """Override says cluster X but issue is in cluster Y's issue_ids → fix override."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    plan["clusters"]["cluster-x"] = {
        "name": "cluster-x",
        "issue_ids": [],
        "auto": True,
        "cluster_key": "auto::x",
        "action": None,
        "user_modified": False,
    }
    plan["clusters"]["cluster-y"] = {
        "name": "cluster-y",
        "issue_ids": ["a"],
        "auto": True,
        "cluster_key": "auto::y",
        "action": None,
        "user_modified": False,
    }
    # Override wrongly points to cluster-x
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "cluster": "cluster-x",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    from desloppify.engine._state.schema import utc_now
    repaired = _repair_ghost_cluster_refs(plan, utc_now())

    assert repaired >= 1
    # Override should now match cluster.issue_ids (cluster-y)
    assert plan["overrides"]["a"]["cluster"] == "cluster-y"


def test_repair_override_not_in_any_cluster():
    """Override points to real cluster but issue not in any cluster's issue_ids → clear."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    plan["clusters"]["my-cluster"] = {
        "name": "my-cluster",
        "issue_ids": ["b"],  # "a" is NOT here
        "auto": False,
        "cluster_key": "",
        "action": None,
        "user_modified": False,
    }
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "cluster": "my-cluster",  # points to real cluster, but not in its issue_ids
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    plan["overrides"]["b"] = {
        "issue_id": "b",
        "cluster": "my-cluster",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    from desloppify.engine._state.schema import utc_now
    repaired = _repair_ghost_cluster_refs(plan, utc_now())

    assert repaired == 1
    assert plan["overrides"]["a"]["cluster"] is None
    assert plan["overrides"]["b"]["cluster"] == "my-cluster"


def test_repair_manual_cluster_wins_over_auto():
    """When issue is in both manual and auto cluster, override should point to manual."""
    plan = empty_plan()
    ensure_plan_defaults(plan)

    plan["clusters"]["auto/unused"] = {
        "name": "auto/unused",
        "issue_ids": ["a"],
        "auto": True,
        "cluster_key": "auto::unused",
        "action": None,
        "user_modified": False,
    }
    plan["clusters"]["my-manual"] = {
        "name": "my-manual",
        "issue_ids": ["a"],
        "auto": False,
        "cluster_key": "",
        "action": None,
        "user_modified": False,
    }
    plan["overrides"]["a"] = {
        "issue_id": "a",
        "cluster": "auto/unused",
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    from desloppify.engine._state.schema import utc_now
    _repair_ghost_cluster_refs(plan, utc_now())

    # Manual cluster should take priority
    assert plan["overrides"]["a"]["cluster"] == "my-manual"


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
    """auto_cluster_sync no longer evicts under-target IDs — sync_stale owns eviction."""
    from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions

    plan = empty_plan()
    ut = _under_target_state("design_coherence", "error_consistency", score=70.0)

    # Step 1: sync_stale injects when no objective backlog
    state_no_obj = {**ut, "issues": {}}
    sync_subjective_dimensions(plan, state_no_obj)

    order = plan["queue_order"]
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order

    # auto_cluster creates clusters from what sync_stale injected
    auto_cluster_issues(plan, state_no_obj)
    assert "auto/under-target-review" in plan["clusters"]

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
    """auto_cluster_sync no longer evicts stale IDs — sync_stale owns eviction."""
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
    # IDs remain — auto_cluster no longer evicts
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order


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

    # Phase 2: objective issues appear mid-cycle — sync_stale evicts
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

    # Phase 3: objective resolved — sync_stale re-injects
    state_empty2 = {**ut, "issues": {}}
    sync_subjective_dimensions(plan, state_empty2)

    order = plan["queue_order"]
    assert "subjective::design_coherence" in order
    assert "subjective::error_consistency" in order


# ---------------------------------------------------------------------------
# Judgment-required detectors don't auto-cluster
# ---------------------------------------------------------------------------

def test_judgment_required_issues_do_not_auto_cluster():
    """Issues from needs_judgment=True detectors (e.g. smells) must not auto-cluster."""
    plan = empty_plan()
    state = _state_with(
        _issue("s1", "smells"),
        _issue("s2", "smells"),
        _issue("s3", "smells"),
    )

    auto_cluster_issues(plan, state)
    # No auto-cluster should be created for smells
    for name in plan["clusters"]:
        assert "smells" not in name, f"unexpected cluster {name} for judgment-required detector"


def test_non_judgment_issues_still_auto_cluster():
    """Issues from needs_judgment=False detectors (e.g. unused) still auto-cluster."""
    plan = empty_plan()
    state = _state_with(
        _issue("u1", "unused"),
        _issue("u2", "unused"),
    )

    auto_cluster_issues(plan, state)
    assert "auto/unused" in plan["clusters"]
    assert set(plan["clusters"]["auto/unused"]["issue_ids"]) == {"u1", "u2"}


def test_concerns_issues_still_auto_cluster():
    """Reviewer-confirmed concerns (needs_judgment=False) still auto-cluster."""
    plan = empty_plan()
    state = _state_with(
        _issue("c1", "concerns", detail={"dimension": "design_coherence"}),
        _issue("c2", "concerns", detail={"dimension": "design_coherence"}),
    )

    auto_cluster_issues(plan, state)
    # concerns should still cluster
    cluster_names = list(plan["clusters"].keys())
    concerns_clusters = [n for n in cluster_names if "concerns" in n or "design_coherence" in n]
    assert len(concerns_clusters) >= 1


def test_judgment_required_issues_still_in_state():
    """Judgment-required issues remain in state (affecting scoring) even though they don't cluster."""
    plan = empty_plan()
    state = _state_with(
        _issue("s1", "smells"),
        _issue("s2", "smells"),
        _issue("u1", "unused"),
        _issue("u2", "unused"),
    )

    auto_cluster_issues(plan, state)
    # smells issues still exist in state
    assert "s1" in state["work_items"]
    assert "s2" in state["work_items"]
    # unused auto-clusters normally
    assert "auto/unused" in plan["clusters"]
