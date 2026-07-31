"""Canonical cluster mutations for plan operations."""

from __future__ import annotations

from desloppify.engine._plan.cluster_semantics import (
    ACTION_TYPE_MANUAL_FIX,
    EXECUTION_POLICY_PLANNED_ONLY,
    EXECUTION_STATUS_ACTIVE,
)
from desloppify.engine._plan.operations.lifecycle import clear_focus_if_cluster_empty
from desloppify.engine._plan.operations.queue import move_items
from desloppify.engine._plan.schema import Cluster, PlanModel, ensure_plan_defaults
from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._state.schema import utc_now


def _cluster_or_raise(plan: PlanModel, cluster_name: str) -> Cluster:
    cluster = plan["clusters"].get(cluster_name)
    if cluster is None:
        raise ValueError(f"Cluster {cluster_name!r} does not exist")
    return cluster


def _upsert_cluster_override(
    plan: PlanModel,
    issue_id: str,
    *,
    cluster_name: str,
    timestamp: str,
) -> None:
    if issue_id in protected_review_issue_ids(plan):
        return
    overrides = plan["overrides"]
    if issue_id not in overrides:
        overrides[issue_id] = {"issue_id": issue_id, "created_at": timestamp}
    overrides[issue_id]["cluster"] = cluster_name
    overrides[issue_id]["updated_at"] = timestamp


def _clear_cluster_override(
    plan: PlanModel,
    issue_id: str,
    *,
    cluster_name: str,
    timestamp: str,
) -> None:
    override = plan["overrides"].get(issue_id)
    if override and override.get("cluster") == cluster_name:
        override["cluster"] = None
        override["updated_at"] = timestamp


def _copy_missing_cluster_metadata(target: Cluster, source: Cluster) -> None:
    if not target.get("description") and source.get("description"):
        target["description"] = source["description"]
    if not target.get("action_steps") and source.get("action_steps"):
        target["action_steps"] = list(source["action_steps"])
    if not target.get("action") and source.get("action"):
        target["action"] = source["action"]


def create_cluster(
    plan: PlanModel,
    name: str,
    description: str | None = None,
    action: str | None = None,
) -> Cluster:
    """Create a named cluster. Raises ValueError if it already exists."""
    ensure_plan_defaults(plan)
    if name.startswith("auto/"):
        raise ValueError(
            f"Cluster names starting with 'auto/' are reserved for auto-clusters: {name!r}"
        )
    if name.startswith("epic/"):
        raise ValueError(
            f"Cluster names starting with 'epic/' are reserved for triage epics: {name!r}"
        )
    if name in plan["clusters"]:
        raise ValueError(f"Cluster {name!r} already exists")
    now = utc_now()
    cluster: Cluster = {
        "name": name,
        "description": description,
        "issue_ids": [],
        "created_at": now,
        "updated_at": now,
        "auto": False,
        "cluster_key": "",
        "action": action,
        "action_type": ACTION_TYPE_MANUAL_FIX,
        "execution_policy": EXECUTION_POLICY_PLANNED_ONLY,
        "execution_status": EXECUTION_STATUS_ACTIVE,
        "user_modified": False,
    }
    plan["clusters"][name] = cluster
    return cluster


def add_to_cluster(
    plan: PlanModel,
    cluster_name: str,
    issue_ids: list[str],
) -> int:
    """Add issue IDs to a cluster. Returns count added.

    For non-auto clusters, also ensures the issue IDs appear in
    ``queue_order`` so they're visible in ``desloppify next``.
    """
    ensure_plan_defaults(plan)
    cluster = _cluster_or_raise(plan, cluster_name)
    member_ids: list[str] = cluster["issue_ids"]
    queue_order: list[str] = plan.get("queue_order", [])
    is_manual = not cluster.get("auto")
    protected_ids = protected_review_issue_ids(plan)
    count = 0
    now = utc_now()
    for fid in issue_ids:
        if fid not in member_ids:
            member_ids.append(fid)
            count += 1
        # Ensure manual cluster members are in the queue
        if is_manual and fid not in protected_ids and fid not in queue_order:
            queue_order.append(fid)
        _upsert_cluster_override(
            plan,
            fid,
            cluster_name=cluster_name,
            timestamp=now,
        )

    cluster["updated_at"] = now
    return count


def remove_from_cluster(
    plan: PlanModel,
    cluster_name: str,
    issue_ids: list[str],
) -> int:
    """Remove issue IDs from a cluster. Returns count removed."""
    ensure_plan_defaults(plan)
    cluster = _cluster_or_raise(plan, cluster_name)
    member_ids: list[str] = cluster["issue_ids"]
    removed_ids = set(issue_ids)
    now = utc_now()
    count = 0
    for fid in issue_ids:
        if fid in member_ids:
            member_ids.remove(fid)
            count += 1
        _clear_cluster_override(
            plan,
            fid,
            cluster_name=cluster_name,
            timestamp=now,
        )

    steps = cluster.get("action_steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            refs = step.get("issue_refs")
            if not isinstance(refs, list):
                continue
            filtered_refs = [
                ref for ref in refs
                if isinstance(ref, str) and ref not in removed_ids
            ]
            if filtered_refs != refs:
                step["issue_refs"] = filtered_refs

    if count > 0 and cluster.get("auto"):
        cluster["user_modified"] = True

    cluster["updated_at"] = now
    clear_focus_if_cluster_empty(plan)
    return count


def delete_cluster(plan: PlanModel, name: str) -> list[str]:
    """Delete a cluster and clear cluster refs from overrides. Returns orphaned IDs."""
    ensure_plan_defaults(plan)
    cluster = _cluster_or_raise(plan, name)
    plan["clusters"].pop(name, None)

    orphaned = list(cluster.get("issue_ids", []))
    now = utc_now()
    for fid in orphaned:
        _clear_cluster_override(
            plan,
            fid,
            cluster_name=name,
            timestamp=now,
        )

    if plan.get("active_cluster") == name:
        plan["active_cluster"] = None

    return orphaned


def merge_clusters(
    plan: PlanModel,
    source_name: str,
    target_name: str,
) -> tuple[int, list[str]]:
    """Move all source issues to target, copy missing metadata, delete source."""
    ensure_plan_defaults(plan)
    if source_name == target_name:
        raise ValueError("Cannot merge a cluster into itself")
    source = _cluster_or_raise(plan, source_name)
    target = _cluster_or_raise(plan, target_name)

    source_ids = list(source.get("issue_ids", []))
    target_ids: list[str] = target["issue_ids"]
    now = utc_now()

    existing = set(target_ids)
    added = 0
    for fid in source_ids:
        if fid not in existing:
            target_ids.append(fid)
            existing.add(fid)
            added += 1
        _upsert_cluster_override(
            plan,
            fid,
            cluster_name=target_name,
            timestamp=now,
        )

    _copy_missing_cluster_metadata(target, source)

    target["updated_at"] = now

    plan["clusters"].pop(source_name, None)
    if plan.get("active_cluster") == source_name:
        plan["active_cluster"] = None

    return added, source_ids


def move_cluster(
    plan: PlanModel,
    cluster_name: str,
    position: str,
    target: str | None = None,
    offset: int | None = None,
) -> int:
    """Move all cluster members as a contiguous block. Returns count moved."""
    ensure_plan_defaults(plan)
    cluster = _cluster_or_raise(plan, cluster_name)
    member_ids = list(cluster.get("issue_ids", []))
    if not member_ids:
        return 0

    return move_items(plan, member_ids, position, target, offset)


__all__ = [
    "add_to_cluster",
    "create_cluster",
    "delete_cluster",
    "merge_clusters",
    "move_cluster",
    "remove_from_cluster",
]
