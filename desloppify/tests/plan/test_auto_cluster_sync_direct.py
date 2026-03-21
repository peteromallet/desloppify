"""Direct coverage tests for auto-cluster sync helpers."""

from __future__ import annotations

import desloppify.engine._plan.auto_cluster_sync as sync_mod
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility


NOW = "2026-03-08T00:00:00Z"


def _unused_issue(fid: str) -> dict:
    return {
        "id": fid,
        "status": "open",
        "suppressed": False,
        "detector": "unused",
        "file": f"src/{fid.replace('::', '_')}.py",
        "detail": {},
    }


def test_sync_issue_clusters_creates_auto_cluster_and_overrides() -> None:
    plan = {"overrides": {}}
    issues = {
        "unused::a": _unused_issue("unused::a"),
        "unused::b": _unused_issue("unused::b"),
        "unused::closed": {
            **_unused_issue("unused::closed"),
            "status": "closed",
        },
    }
    clusters: dict[str, dict] = {}
    existing_by_key: dict[str, str] = {}
    active_auto_keys: set[str] = set()

    changes = sync_mod.sync_issue_clusters(
        plan,
        issues,
        clusters,
        existing_by_key,
        active_auto_keys,
        NOW,
    )

    assert changes == 1
    assert active_auto_keys == {"auto::unused"}

    assert "auto/unused" in clusters
    cluster = clusters["auto/unused"]
    assert cluster["auto"] is True
    assert cluster["cluster_key"] == "auto::unused"
    assert set(cluster["issue_ids"]) == {"unused::a", "unused::b"}

    assert plan["overrides"]["unused::a"]["cluster"] == "auto/unused"
    assert plan["overrides"]["unused::b"]["cluster"] == "auto/unused"


def test_sync_issue_clusters_respects_user_modified_clusters() -> None:
    plan = {
        "overrides": {
            "unused::a": {
                "issue_id": "unused::a",
                "cluster": "auto/unused",
                "created_at": "old",
                "updated_at": "old",
            }
        }
    }
    issues = {
        "unused::a": _unused_issue("unused::a"),
        "unused::b": _unused_issue("unused::b"),
    }
    clusters = {
        "auto/unused": {
            "name": "auto/unused",
            "description": "custom desc",
            "issue_ids": ["unused::a"],
            "created_at": "old",
            "updated_at": "old",
            "auto": True,
            "cluster_key": "auto::unused",
            "action": "custom action",
            "user_modified": True,
        }
    }
    existing_by_key = {"auto::unused": "auto/unused"}
    active_auto_keys: set[str] = set()

    changes = sync_mod.sync_issue_clusters(
        plan,
        issues,
        clusters,
        existing_by_key,
        active_auto_keys,
        NOW,
    )

    assert changes == 1
    assert clusters["auto/unused"]["issue_ids"] == ["unused::a", "unused::b"]
    assert clusters["auto/unused"]["description"] == "custom desc"
    assert plan["overrides"]["unused::b"]["cluster"] == "auto/unused"


def test_sync_subjective_clusters_creates_optional_under_target_cluster() -> None:
    plan = {
        "queue_order": [
            "subjective::naming",
            "subjective::error_handling",
            "subjective::architecture",
            "subjective::api_surface",
        ],
        "overrides": {},
        "clusters": {},
    }
    clusters = plan["clusters"]
    existing_by_key: dict[str, str] = {}
    active_auto_keys: set[str] = set()

    policy = SubjectiveVisibility(
        has_objective_backlog=False,
        objective_count=0,
        unscored_ids=frozenset({"subjective::naming"}),
        stale_ids=frozenset({"subjective::error_handling"}),
        under_target_ids=frozenset({"subjective::architecture", "subjective::api_surface"}),
    )

    changes = sync_mod.sync_subjective_clusters(
        plan,
        state={"issues": {}},
        issues={},
        clusters=clusters,
        existing_by_key=existing_by_key,
        active_auto_keys=active_auto_keys,
        now=NOW,
        target_strict=95.0,
        policy=policy,
    )

    assert changes >= 2
    assert "subjective::unscored" in active_auto_keys
    assert "subjective::under-target" in active_auto_keys

    under_target = clusters["auto/under-target-review"]
    assert under_target["optional"] is True
    assert set(under_target["issue_ids"]) == {
        "subjective::architecture",
        "subjective::api_surface",
    }


def test_sync_subjective_clusters_no_eviction_when_objective_exists() -> None:
    """auto_cluster_sync no longer evicts under_target IDs — sync_stale owns that."""
    plan = {
        "queue_order": [
            "subjective::architecture",
            "subjective::api_surface",
            "unused::x",
        ],
        "clusters": {},
        "overrides": {},
    }
    existing_by_key: dict[str, str] = {}
    active_auto_keys: set[str] = set()
    issues = {"unused::x": _unused_issue("unused::x")}

    policy = SubjectiveVisibility(
        has_objective_backlog=True,
        objective_count=1,
        unscored_ids=frozenset(),
        stale_ids=frozenset(),
        under_target_ids=frozenset({"subjective::architecture", "subjective::api_surface"}),
    )

    sync_mod.sync_subjective_clusters(
        plan,
        state={"issues": issues},
        issues=issues,
        clusters=plan["clusters"],
        existing_by_key=existing_by_key,
        active_auto_keys=active_auto_keys,
        now=NOW,
        target_strict=95.0,
        policy=policy,
    )

    # Under-target IDs remain in queue — sync_stale is the authority on eviction
    assert "subjective::architecture" in plan["queue_order"]
    assert "subjective::api_surface" in plan["queue_order"]
    assert "unused::x" in plan["queue_order"]
    assert "auto/under-target-review" not in plan["clusters"]


def test_sync_stale_escalates_after_repeated_defers() -> None:
    """Escalation is now owned by sync_subjective_dimensions, not auto_cluster_sync."""
    from desloppify.engine._plan.schema import empty_plan
    from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions

    plan = empty_plan()
    plan["queue_order"] = ["unused::x"]
    plan["plan_start_scores"] = {"strict": 50.0}  # mid-cycle

    issues = {"unused::x": _unused_issue("unused::x")}
    policy = SubjectiveVisibility(
        has_objective_backlog=True,
        objective_count=1,
        unscored_ids=frozenset(),
        stale_ids=frozenset({"subjective::architecture"}),
        under_target_ids=frozenset({"subjective::api_surface"}),
    )

    state = {
        "issues": issues,
        "scan_count": 1,
        "last_scan": "2026-03-01T00:00:00+00:00",
        "dimension_scores": {
            "architecture": {
                "score": 50.0, "strict": 50.0, "checks": 1, "failing": 0,
                "detectors": {"subjective_assessment": {"dimension_key": "architecture", "placeholder": False}},
            },
            "api_surface": {
                "score": 50.0, "strict": 50.0, "checks": 1, "failing": 0,
                "detectors": {"subjective_assessment": {"dimension_key": "api_surface", "placeholder": False}},
            },
        },
        "subjective_assessments": {
            "architecture": {"score": 50.0, "needs_review_refresh": True, "stale_since": "2026-01-01T00:00:00+00:00"},
            "api_surface": {"score": 50.0, "needs_review_refresh": False},
        },
    }

    # Defer 1
    sync_subjective_dimensions(plan, state, policy=policy)
    assert plan["subjective_defer_meta"]["defer_count"] == 1
    assert plan["subjective_defer_meta"]["deferred_review_ids"] == [
        "subjective::api_surface",
    ]
    assert plan["subjective_defer_meta"]["deferred_stale_ids"] == []
    assert plan["subjective_defer_meta"]["deferred_under_target_ids"] == [
        "subjective::api_surface",
    ]
    assert "force_visible_ids" not in plan["subjective_defer_meta"]
    assert plan["queue_order"] == ["subjective::architecture", "unused::x"]

    # Defer 2
    state["scan_count"] = 2
    state["last_scan"] = "2026-03-02T00:00:00+00:00"
    sync_subjective_dimensions(plan, state, policy=policy)
    assert plan["subjective_defer_meta"]["defer_count"] == 2
    assert plan["queue_order"] == ["subjective::architecture", "unused::x"]

    # Defer 3 → escalation
    state["scan_count"] = 3
    state["last_scan"] = "2026-03-03T00:00:00+00:00"
    sync_subjective_dimensions(plan, state, policy=policy)

    defer_meta = plan["subjective_defer_meta"]
    assert defer_meta["defer_count"] == 3
    assert defer_meta["force_visible_ids"] == ["subjective::api_surface"]
    assert plan["queue_order"][:2] == [
        "subjective::api_surface",
        "subjective::architecture",
    ]
    assert "unused::x" in plan["queue_order"]


def test_subjective_state_sets_fallback_uses_module_helpers(monkeypatch) -> None:
    monkeypatch.setattr(sync_mod, "current_unscored_ids", lambda _state: {"subjective::a"})
    monkeypatch.setattr(
        sync_mod.stale_policy_mod,
        "current_stale_ids",
        lambda _state, subjective_prefix: {f"{subjective_prefix}stale"},
    )
    monkeypatch.setattr(
        sync_mod,
        "current_under_target_ids",
        lambda _state, target_strict: {f"subjective::{int(target_strict)}"},
    )

    stale_ids, under_target_ids, unscored_ids = sync_mod._subjective_state_sets(
        {"issues": {}},
        policy=None,
        target_strict=97.0,
    )

    assert stale_ids == {"subjective::stale"}
    assert under_target_ids == {"subjective::97"}
    assert unscored_ids == {"subjective::a"}


def test_sync_subjective_clusters_does_not_append_skipped_under_target_ids() -> None:
    plan = {
        "queue_order": [],
        "clusters": {},
        "overrides": {},
        "skipped": {
            "subjective::architecture": {"kind": "permanent"},
            "subjective::api_surface": {"kind": "permanent"},
        },
    }
    existing_by_key: dict[str, str] = {}
    active_auto_keys: set[str] = set()

    policy = SubjectiveVisibility(
        has_objective_backlog=False,
        objective_count=0,
        unscored_ids=frozenset(),
        stale_ids=frozenset(),
        under_target_ids=frozenset({"subjective::architecture", "subjective::api_surface"}),
    )

    changes = sync_mod.sync_subjective_clusters(
        plan,
        state={"issues": {}},
        issues={},
        clusters=plan["clusters"],
        existing_by_key=existing_by_key,
        active_auto_keys=active_auto_keys,
        now=NOW,
        target_strict=95.0,
        policy=policy,
    )

    assert changes == 0
    assert plan["queue_order"] == []
    assert "auto/under-target-review" not in plan["clusters"]
