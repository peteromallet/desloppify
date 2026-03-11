"""Plan-order and cluster-collapse helpers for work queues."""

from __future__ import annotations

from typing import Any

from desloppify.base.registry import DETECTORS
from desloppify.engine.plan_ops import (
    get_issue_description,
    get_issue_note,
    get_issue_override,
)
from desloppify.engine._work_queue.types import WorkQueueItem
from desloppify.state_io import StateModel


def _cluster_issue_ids(cluster: dict[str, Any]) -> list[str]:
    """Return canonical cluster members after plan-load normalization."""
    issue_ids = cluster.get("issue_ids", [])
    if not isinstance(issue_ids, list):
        return []
    return [issue_id for issue_id in issue_ids if isinstance(issue_id, str) and issue_id]


def new_item_ids(state: StateModel) -> set[str]:
    """Return issue IDs added in the most recent scan."""
    scan_history = state.get("scan_history", [])
    if not scan_history:
        return set()
    threshold = scan_history[-1].get("timestamp", "")
    if not threshold:
        return set()
    return {
        issue_id
        for issue_id, issue in state.get("issues", {}).items()
        if issue.get("first_seen", "") >= threshold
    }


def enrich_plan_metadata(items: list[WorkQueueItem], plan: dict) -> None:
    """Stamp plan description, note, and cluster info from overrides."""
    clusters: dict = plan.get("clusters", {})

    for item in items:
        issue_id = item["id"]
        description = get_issue_description(plan, issue_id)
        note = get_issue_note(plan, issue_id)
        override = get_issue_override(plan, issue_id)
        if description:
            item["plan_description"] = description
        if note:
            item["plan_note"] = note
        if override.get("cluster"):
            cluster_name = override["cluster"]
            cluster_data = clusters.get(cluster_name, {})
            item["plan_cluster"] = {
                "name": cluster_name,
                "description": cluster_data.get("description"),
                "total_items": len(_cluster_issue_ids(cluster_data)),
                "action_steps": cluster_data.get("action_steps") or [],
            }


def stamp_plan_sort_keys(
    items: list[WorkQueueItem],
    plan: dict,
    new_ids: set[str],
) -> None:
    """Stamp ``_plan_position`` and ``_is_new`` on each item.

    These fields are consumed by :func:`item_sort_key` in ``ranking.py``
    to produce the correct final ordering in a single sort pass.
    """
    queue_order: list[str] = plan.get("queue_order", [])
    skipped_ids: set[str] = set(plan.get("skipped", {}).keys())
    subjective_defer_meta = plan.get("subjective_defer_meta", {})
    if not isinstance(subjective_defer_meta, dict):
        subjective_defer_meta = {}
    normalized_force_visible_ids = sorted({
        str(fid).strip()
        for fid in subjective_defer_meta.get("force_visible_ids", [])
        if str(fid).strip()
    })
    subjective_defer_meta["force_visible_ids"] = normalized_force_visible_ids
    force_visible_ids = set(normalized_force_visible_ids)

    position_map: dict[str, int] = {}
    for idx, issue_id in enumerate(queue_order):
        if issue_id not in skipped_ids:
            position_map[issue_id] = idx

    for item in items:
        item_id = item["id"]
        pos = position_map.get(item_id)
        item["_plan_position"] = pos  # None if not in queue_order
        item["_is_new"] = item_id in new_ids
        if item_id in force_visible_ids:
            item["force_visible"] = True


def separate_skipped(
    items: list[WorkQueueItem],
    plan: dict,
) -> tuple[list[WorkQueueItem], list[WorkQueueItem]]:
    """Separate skipped items from the main list.

    Returns ``(non_skipped, skipped)`` so callers can optionally re-append.
    """
    skipped_ids: set[str] = set(plan.get("skipped", {}).keys())
    if not skipped_ids:
        return items, []
    non_skipped: list[WorkQueueItem] = []
    skipped: list[WorkQueueItem] = []
    for item in items:
        if item["id"] in skipped_ids:
            skipped.append(item)
        else:
            non_skipped.append(item)
    return non_skipped, skipped


def filter_cluster_focus(
    items: list[WorkQueueItem],
    plan: dict,
    cluster: str | None,
) -> list[WorkQueueItem]:
    """Filter to only cluster members when a cluster focus is active."""
    effective_cluster = cluster or plan.get("active_cluster")
    if not effective_cluster:
        return items
    clusters: dict = plan.get("clusters", {})
    cluster_data = clusters.get(effective_cluster, {})
    cluster_member_ids = set(_cluster_issue_ids(cluster_data))
    if not cluster_member_ids:
        return items
    return [item for item in items if item["id"] in cluster_member_ids]


def stamp_positions(items: list[WorkQueueItem], plan: dict) -> None:
    """Stamp queue_position and plan_skipped metadata on each item."""
    skipped_map: dict = plan.get("skipped", {})
    skipped_ids: set[str] = set(skipped_map.keys())

    for position, item in enumerate(items):
        item["queue_position"] = position + 1
        if item["id"] in skipped_ids:
            item["plan_skipped"] = True
            skip_entry = skipped_map.get(item["id"])
            if skip_entry:
                item["plan_skip_kind"] = skip_entry.get("kind", "temporary")
                skip_reason = skip_entry.get("reason")
                if skip_reason:
                    item["plan_skip_reason"] = skip_reason


def action_type_for_detector(detector: str) -> str:
    """Look up the action_type for a detector from the registry."""
    meta = DETECTORS.get(detector)
    if meta:
        return meta.action_type
    return "manual_fix"


def _build_cluster_meta(
    cluster_name: str, members: list[WorkQueueItem], cluster_data: dict[str, Any]
) -> WorkQueueItem:
    """Build a cluster meta-item from its member items."""
    detector = members[0].get("detector", "") if members else ""
    action = cluster_data.get("action") or ""
    if "desloppify autofix" in action:
        action_type = "auto_fix"
    elif "desloppify move" in action:
        action_type = "reorganize"
    else:
        action_type = action_type_for_detector(detector)
        if action_type == "auto_fix" and "desloppify autofix" not in action:
            action_type = "refactor"

    stored_desc = cluster_data.get("description") or ""
    total_in_cluster = len(_cluster_issue_ids(cluster_data))
    if stored_desc and total_in_cluster != len(members):
        summary = stored_desc.replace(str(total_in_cluster), str(len(members)))
    else:
        summary = stored_desc or f"{len(members)} issues"

    action = cluster_data.get("action") or ""
    if "desloppify autofix" in action:
        primary_command = f"desloppify next --cluster {cluster_name} --count 10"
        autofix_hint = action
    else:
        primary_command = action or f"desloppify next --cluster {cluster_name} --count 10"
        autofix_hint = None

    estimated_impact = max(
        (m.get("estimated_impact", 0.0) for m in members), default=0.0
    )

    return {
        "id": cluster_name,
        "kind": "cluster",
        "action_type": action_type,
        "summary": summary,
        "members": members,
        "member_count": len(members),
        "primary_command": primary_command,
        "autofix_hint": autofix_hint,
        "cluster_name": cluster_name,
        "cluster_auto": bool(cluster_data.get("auto")),
        "cluster_optional": bool(cluster_data.get("optional")),
        "confidence": "high",
        "detector": detector,
        "file": "",
        "estimated_impact": estimated_impact,
        "action_steps": cluster_data.get("action_steps") or [],
    }


def collapse_clusters(items: list[WorkQueueItem], plan: dict) -> list[WorkQueueItem]:
    """Replace cluster member items with single cluster meta-items.

    Both auto-clusters and manual (triage) clusters are collapsed.  Manual
    clusters are inserted at the front in plan order so triage-prioritised
    work appears before auto-clustered mechanical items.
    """
    clusters = plan.get("clusters", {})
    if not clusters:
        return items

    fid_to_cluster: dict[str, str] = {}
    for name, cluster in clusters.items():
        for issue_id in _cluster_issue_ids(cluster):
            # Manual clusters take priority when an issue is in both
            if issue_id not in fid_to_cluster or not cluster.get("auto"):
                fid_to_cluster[issue_id] = name

    if not fid_to_cluster:
        return items

    # Collect members per cluster (preserving encounter order)
    cluster_members: dict[str, list[WorkQueueItem]] = {}
    for item in items:
        cname = fid_to_cluster.get(item.get("id", ""))
        if cname:
            cluster_members.setdefault(cname, []).append(item)

    # Build meta-items only for clusters with 2+ members in the queue
    meta_items: dict[str, WorkQueueItem] = {}
    for cname, members in cluster_members.items():
        if len(members) < 2:
            continue
        meta_items[cname] = _build_cluster_meta(
            cname, members, clusters.get(cname, {})
        )

    # Collect manual cluster names in plan order (for front-insertion)
    manual_names = [
        name for name in clusters
        if not clusters[name].get("auto") and name in meta_items
    ]

    # Walk in order: replace first auto-cluster member with meta-item,
    # skip subsequent members.  Manual cluster members are always skipped
    # (they'll be inserted at the front).
    seen_clusters: set[str] = set()
    rest: list[WorkQueueItem] = []
    for item in items:
        cname = fid_to_cluster.get(item.get("id", ""))
        if cname and cname in meta_items:
            if cname not in seen_clusters:
                seen_clusters.add(cname)
                # Auto-clusters collapse in-place; manual clusters go to front
                if clusters.get(cname, {}).get("auto"):
                    rest.append(meta_items[cname])
            # skip individual member
        else:
            rest.append(item)

    # Manual clusters at the front in plan order, then everything else
    manual_result = [meta_items[name] for name in manual_names if name in seen_clusters]
    return manual_result + rest


__all__ = [
    "collapse_clusters",
    "enrich_plan_metadata",
    "filter_cluster_focus",
    "new_item_ids",
    "separate_skipped",
    "stamp_plan_sort_keys",
    "stamp_positions",
]
