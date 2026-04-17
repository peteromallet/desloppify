"""Auto-clustering algorithm — groups issues into task clusters."""

from __future__ import annotations

from desloppify.base.config import DEFAULT_TARGET_STRICT_SCORE
from desloppify.engine._plan.cluster_semantics import cluster_is_active
from desloppify.engine._plan.constants import AUTO_PREFIX
from desloppify.engine._plan.auto_cluster_sync import (
    prune_stale_clusters as _prune_stale_clusters,
    sync_issue_clusters as _sync_issue_clusters,
    sync_subjective_clusters as _sync_subjective_clusters,
)
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility
from desloppify.engine._plan.sync.context import is_mid_cycle
from desloppify.engine._state.schema import StateModel, utc_now

# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

def _clear_missing_cluster_override(
    override: dict,
    clusters: dict,
    now: str,
) -> int:
    cluster_name = override.get("cluster")
    if not cluster_name or cluster_name in clusters:
        return 0
    override["cluster"] = None
    override["updated_at"] = now
    return 1


def _canonical_cluster_membership(clusters: dict) -> dict[str, str]:
    canonical: dict[str, str] = {}
    for name, cluster in clusters.items():
        for issue_id in cluster.get("issue_ids", []):
            if issue_id not in canonical or not cluster.get("auto"):
                canonical[issue_id] = name
    return canonical


def _sync_override_to_canonical_cluster(
    issue_id: str,
    cluster_name: str,
    overrides: dict,
    now: str,
) -> int:
    override = overrides.get(issue_id)
    if override is None:
        overrides[issue_id] = {
            "issue_id": issue_id,
            "cluster": cluster_name,
            "created_at": now,
            "updated_at": now,
        }
        return 1
    if override.get("cluster") == cluster_name:
        return 0
    override["cluster"] = cluster_name
    override["updated_at"] = now
    return 1


def _clear_stale_override_cluster_refs(
    overrides: dict,
    clusters: dict,
    canonical: dict[str, str],
    now: str,
) -> int:
    repaired = 0
    for issue_id, override in overrides.items():
        ref = override.get("cluster")
        if not ref or ref not in clusters or issue_id in canonical:
            continue
        override["cluster"] = None
        override["updated_at"] = now
        repaired += 1
    return repaired


def _repair_ghost_cluster_refs(plan: PlanModel, now: str) -> int:
    """Cross-check cluster membership between cluster.issue_ids and overrides.

    Repairs three kinds of drift:
    1. Override points to a cluster that does not exist → clear override.
    2. Override points to cluster X, but issue is not in X's issue_ids → add it.
    3. Issue is in cluster.issue_ids but override points elsewhere (or has no
       cluster ref) → update override to match cluster.issue_ids.

    cluster.issue_ids is treated as authoritative when it disagrees with
    the override, because the sync helpers always write issue_ids first.
    """
    clusters = plan.get("clusters", {})
    overrides = plan.get("overrides", {})
    repaired = 0

    for override in overrides.values():
        repaired += _clear_missing_cluster_override(override, clusters, now)

    canonical = _canonical_cluster_membership(clusters)

    for issue_id, cluster_name in canonical.items():
        repaired += _sync_override_to_canonical_cluster(issue_id, cluster_name, overrides, now)

    repaired += _clear_stale_override_cluster_refs(overrides, clusters, canonical, now)

    return repaired


def _existing_auto_cluster_keys(clusters: dict) -> dict[str, str]:
    existing_by_key: dict[str, str] = {}
    for name, cluster in list(clusters.items()):
        if cluster.get("auto"):
            cluster_key = cluster.get("cluster_key", "")
            if cluster_key:
                existing_by_key[cluster_key] = name
    return existing_by_key


def _sync_auto_clusters(
    plan: PlanModel,
    state: StateModel,
    issues: dict,
    clusters: dict,
    existing_by_key: dict[str, str],
    now: str,
    *,
    target_strict: float,
    policy: SubjectiveVisibility | None,
) -> int:
    active_auto_keys: set[str] = set()
    changes = 0
    changes += _sync_issue_clusters(
        plan, issues, clusters, existing_by_key, active_auto_keys, now,
    )
    changes += _sync_subjective_clusters(
        plan, state, issues, clusters, existing_by_key, active_auto_keys, now,
        target_strict=target_strict,
        policy=policy,
    )
    changes += _prune_stale_clusters(
        plan, issues, clusters, active_auto_keys, now,
    )
    return changes


def _evictable_auto_cluster_issue_ids(plan: PlanModel) -> set[str]:
    """Return queue_order IDs that belong to non-active auto-clusters.

    After sync rewrites a cluster (e.g. Rust detectors losing auto_queue),
    the cluster's execution_policy is already updated to planned_only and
    execution_status to review. So we can't rely on the old policy value.
    Instead: collect detector-based IDs from all non-active auto-clusters,
    then subtract IDs owned by any active cluster (handles cross-cluster moves).

    Synthetic IDs (subjective::*, triage::*, workflow::*) are never evicted
    here — their lifecycle is managed by sync_subjective_dimensions.
    """
    from desloppify.engine._plan.constants import is_synthetic_id

    active_ids: set[str] = set()
    inactive_ids: set[str] = set()
    for cluster in plan.get("clusters", {}).values():
        if not isinstance(cluster, dict):
            continue
        ids = {
            issue_id
            for issue_id in cluster.get("issue_ids", [])
            if isinstance(issue_id, str) and issue_id and not is_synthetic_id(issue_id)
        }
        if not cluster.get("auto"):
            active_ids |= ids
            continue
        if cluster_is_active(cluster):
            active_ids |= ids
        else:
            inactive_ids |= ids
    return inactive_ids - active_ids


def _sync_active_auto_cluster_queue_membership(plan: PlanModel) -> int:
    order: list[str] = plan.get("queue_order", [])
    skipped = set(plan.get("skipped", {}).keys())
    existing = set(order)
    changes = 0

    # Evict queue_order entries from non-active auto-clusters.
    evict_ids = _evictable_auto_cluster_issue_ids(plan)
    if evict_ids:
        before = len(order)
        plan["queue_order"] = [oid for oid in order if oid not in evict_ids]
        order = plan["queue_order"]
        existing = set(order)
        changes += before - len(order)

    # Append issue IDs from active auto-clusters.
    for cluster in plan.get("clusters", {}).values():
        if not isinstance(cluster, dict) or not cluster.get("auto") or not cluster_is_active(cluster):
            continue
        for issue_id in cluster.get("issue_ids", []):
            if (
                not isinstance(issue_id, str)
                or not issue_id
                or issue_id in skipped
                or issue_id in existing
            ):
                continue
            order.append(issue_id)
            existing.add(issue_id)
            changes += 1
    return changes


def auto_cluster_issues(
    plan: PlanModel,
    state: StateModel,
    *,
    target_strict: float = DEFAULT_TARGET_STRICT_SCORE,
    policy: SubjectiveVisibility | None = None,
) -> int:
    """Regenerate auto-clusters from current open issues.

    Returns count of changes made (clusters created, updated, or deleted).
    """
    ensure_plan_defaults(plan)
    if is_mid_cycle(plan):
        return 0

    issues = (state.get("work_items") or state.get("issues", {}))
    clusters = plan.get("clusters", {})

    now = utc_now()
    changes = _sync_auto_clusters(
        plan,
        state,
        issues,
        clusters,
        _existing_auto_cluster_keys(clusters),
        now,
        target_strict=target_strict,
        policy=policy,
    )
    changes += _repair_ghost_cluster_refs(plan, now)
    changes += _sync_active_auto_cluster_queue_membership(plan)

    plan["updated"] = now
    return changes


__all__ = [
    "AUTO_PREFIX",
    "auto_cluster_issues",
]
