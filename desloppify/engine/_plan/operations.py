"""Pure mutation operations on the plan model."""

from __future__ import annotations

from desloppify.engine._plan.schema import (
    Cluster,
    PlanModel,
    SkipEntry,
    ensure_plan_defaults,
)
from desloppify.engine._state.schema import utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _remove_id_from_lists(plan: PlanModel, finding_id: str) -> None:
    """Remove a finding ID from queue_order and skipped."""
    order: list[str] = plan["queue_order"]
    skipped: dict[str, SkipEntry] = plan.get("skipped", {})
    if finding_id in order:
        order.remove(finding_id)
    skipped.pop(finding_id, None)


def _resolve_position(
    order: list[str],
    position: str,
    target: str | None = None,
    offset: int | None = None,
    finding_ids: list[str] | None = None,
) -> int:
    """Resolve a position specifier to an insertion index.

    *finding_ids* are the IDs being moved — used to calculate relative
    positions when they already exist in the list.
    """
    moving = set(finding_ids or [])

    if position == "top":
        return 0
    if position == "bottom":
        return len(order)

    if position == "before" and target:
        for i, item_id in enumerate(order):
            if item_id == target and item_id not in moving:
                return i
        return 0

    if position == "after" and target:
        for i, item_id in enumerate(order):
            if item_id == target and item_id not in moving:
                return i + 1
        return len(order)

    if position == "up" and offset is not None:
        if not finding_ids:
            return 0
        # Find current position of first item
        first_id = finding_ids[0]
        current_idx = None
        clean_order = [x for x in order if x not in moving]
        for i, item_id in enumerate(clean_order):
            if item_id == first_id:
                current_idx = i
                break
        if current_idx is None:
            # Item not yet in order; treat as "insert at position offset from top"
            return max(0, len(clean_order) - offset)
        return max(0, current_idx - offset)

    if position == "down" and offset is not None:
        if not finding_ids:
            return len(order)
        first_id = finding_ids[0]
        clean_order = [x for x in order if x not in moving]
        current_idx = None
        for i, item_id in enumerate(clean_order):
            if item_id == first_id:
                current_idx = i
                break
        if current_idx is None:
            return len(clean_order)
        return min(len(clean_order), current_idx + offset)

    return len(order)


# ---------------------------------------------------------------------------
# Move items
# ---------------------------------------------------------------------------

def move_items(
    plan: PlanModel,
    finding_ids: list[str],
    position: str,
    target: str | None = None,
    offset: int | None = None,
) -> int:
    """Move finding IDs to a position in queue_order. Returns count moved."""
    ensure_plan_defaults(plan)
    order: list[str] = plan["queue_order"]

    # Remove from skipped if present
    skipped: dict[str, SkipEntry] = plan.get("skipped", {})
    for fid in finding_ids:
        skipped.pop(fid, None)

    # Remove from current position in order
    for fid in finding_ids:
        if fid in order:
            order.remove(fid)

    # Resolve insertion point
    idx = _resolve_position(order, position, target, offset, finding_ids)

    # Insert in original order
    for i, fid in enumerate(finding_ids):
        order.insert(idx + i, fid)

    return len(finding_ids)


# ---------------------------------------------------------------------------
# Skip / unskip
# ---------------------------------------------------------------------------

def skip_items(
    plan: PlanModel,
    finding_ids: list[str],
    *,
    kind: str = "temporary",
    reason: str | None = None,
    note: str | None = None,
    attestation: str | None = None,
    review_after: int | None = None,
    scan_count: int = 0,
) -> int:
    """Move finding IDs to the skipped dict. Returns count skipped."""
    ensure_plan_defaults(plan)
    now = utc_now()
    count = 0
    skipped: dict[str, SkipEntry] = plan["skipped"]
    for fid in finding_ids:
        _remove_id_from_lists(plan, fid)
        skipped[fid] = {
            "finding_id": fid,
            "kind": kind,
            "reason": reason,
            "note": note,
            "attestation": attestation,
            "created_at": now,
            "review_after": review_after,
            "skipped_at_scan": scan_count,
        }
        count += 1
    return count


def unskip_items(
    plan: PlanModel, finding_ids: list[str]
) -> tuple[int, list[str]]:
    """Bring finding IDs back from skipped to the end of queue_order.

    Returns ``(count_unskipped, permanent_ids_needing_state_reopen)``
    where the second list contains IDs that were permanent or false_positive
    and need their state-layer status reopened by the caller.
    """
    ensure_plan_defaults(plan)
    count = 0
    need_reopen: list[str] = []
    skipped: dict[str, SkipEntry] = plan["skipped"]
    for fid in finding_ids:
        entry = skipped.pop(fid, None)
        if entry is not None:
            if entry.get("kind") in ("permanent", "false_positive"):
                need_reopen.append(fid)
            if fid not in plan["queue_order"]:
                plan["queue_order"].append(fid)
            count += 1
    return count, need_reopen


def resurface_stale_skips(
    plan: PlanModel, current_scan_count: int
) -> list[str]:
    """Move temporary skips past their review_after threshold back to queue.

    Returns list of resurfaced finding IDs.
    """
    ensure_plan_defaults(plan)
    skipped: dict[str, SkipEntry] = plan["skipped"]
    resurfaced: list[str] = []
    for fid in list(skipped):
        entry = skipped[fid]
        if entry.get("kind") != "temporary":
            continue
        review_after = entry.get("review_after")
        if review_after is None:
            continue
        skipped_at = entry.get("skipped_at_scan", 0)
        if current_scan_count >= skipped_at + review_after:
            skipped.pop(fid)
            if fid not in plan["queue_order"]:
                plan["queue_order"].append(fid)
            resurfaced.append(fid)
    return resurfaced


# ---------------------------------------------------------------------------
# Describe / annotate
# ---------------------------------------------------------------------------

def describe_finding(
    plan: PlanModel, finding_id: str, description: str | None
) -> None:
    """Set or clear an augmented description on a finding."""
    ensure_plan_defaults(plan)
    now = utc_now()
    overrides = plan["overrides"]
    if finding_id not in overrides:
        overrides[finding_id] = {"finding_id": finding_id, "created_at": now}
    overrides[finding_id]["description"] = description
    overrides[finding_id]["updated_at"] = now


def annotate_finding(
    plan: PlanModel, finding_id: str, note: str | None
) -> None:
    """Set or clear a note on a finding."""
    ensure_plan_defaults(plan)
    now = utc_now()
    overrides = plan["overrides"]
    if finding_id not in overrides:
        overrides[finding_id] = {"finding_id": finding_id, "created_at": now}
    overrides[finding_id]["note"] = note
    overrides[finding_id]["updated_at"] = now


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

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
    if name in plan["clusters"]:
        raise ValueError(f"Cluster {name!r} already exists")
    now = utc_now()
    cluster: Cluster = {
        "name": name,
        "description": description,
        "finding_ids": [],
        "created_at": now,
        "updated_at": now,
        "auto": False,
        "cluster_key": "",
        "action": action,
        "user_modified": False,
    }
    plan["clusters"][name] = cluster
    return cluster


def add_to_cluster(
    plan: PlanModel, cluster_name: str, finding_ids: list[str]
) -> int:
    """Add finding IDs to a cluster. Returns count added."""
    ensure_plan_defaults(plan)
    cluster = plan["clusters"].get(cluster_name)
    if cluster is None:
        raise ValueError(f"Cluster {cluster_name!r} does not exist")

    member_ids: list[str] = cluster["finding_ids"]
    count = 0
    now = utc_now()
    for fid in finding_ids:
        if fid not in member_ids:
            member_ids.append(fid)
            count += 1
        # Update override to track cluster membership
        overrides = plan["overrides"]
        if fid not in overrides:
            overrides[fid] = {"finding_id": fid, "created_at": now}
        overrides[fid]["cluster"] = cluster_name
        overrides[fid]["updated_at"] = now

    cluster["updated_at"] = now
    return count


def remove_from_cluster(
    plan: PlanModel, cluster_name: str, finding_ids: list[str]
) -> int:
    """Remove finding IDs from a cluster. Returns count removed."""
    ensure_plan_defaults(plan)
    cluster = plan["clusters"].get(cluster_name)
    if cluster is None:
        raise ValueError(f"Cluster {cluster_name!r} does not exist")

    member_ids: list[str] = cluster["finding_ids"]
    now = utc_now()
    count = 0
    for fid in finding_ids:
        if fid in member_ids:
            member_ids.remove(fid)
            count += 1
        # Clear cluster from override
        override = plan["overrides"].get(fid)
        if override and override.get("cluster") == cluster_name:
            override["cluster"] = None
            override["updated_at"] = now

    # Mark auto-clusters as user_modified when items are manually removed
    if count > 0 and cluster.get("auto"):
        cluster["user_modified"] = True

    cluster["updated_at"] = now
    return count


def delete_cluster(plan: PlanModel, name: str) -> list[str]:
    """Delete a cluster and clear cluster refs from overrides. Returns orphaned IDs."""
    ensure_plan_defaults(plan)
    cluster = plan["clusters"].pop(name, None)
    if cluster is None:
        raise ValueError(f"Cluster {name!r} does not exist")

    orphaned = list(cluster.get("finding_ids", []))
    now = utc_now()
    for fid in orphaned:
        override = plan["overrides"].get(fid)
        if override and override.get("cluster") == name:
            override["cluster"] = None
            override["updated_at"] = now

    if plan.get("active_cluster") == name:
        plan["active_cluster"] = None

    return orphaned


def move_cluster(
    plan: PlanModel,
    cluster_name: str,
    position: str,
    target: str | None = None,
    offset: int | None = None,
) -> int:
    """Move all cluster members as a contiguous block. Returns count moved."""
    ensure_plan_defaults(plan)
    cluster = plan["clusters"].get(cluster_name)
    if cluster is None:
        raise ValueError(f"Cluster {cluster_name!r} does not exist")

    member_ids = list(cluster.get("finding_ids", []))
    if not member_ids:
        return 0

    return move_items(plan, member_ids, position, target, offset)


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------

def set_focus(plan: PlanModel, cluster_name: str) -> None:
    """Set the active cluster focus."""
    ensure_plan_defaults(plan)
    if cluster_name not in plan["clusters"]:
        raise ValueError(f"Cluster {cluster_name!r} does not exist")
    plan["active_cluster"] = cluster_name


def clear_focus(plan: PlanModel) -> None:
    """Clear the active cluster focus."""
    ensure_plan_defaults(plan)
    plan["active_cluster"] = None


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def reset_plan(plan: PlanModel) -> None:
    """Reset plan to empty state, preserving version and created timestamp."""
    created = plan.get("created", utc_now())
    plan.clear()
    from desloppify.engine._plan.schema import empty_plan as _empty
    for k, v in _empty().items():
        plan[k] = v
    plan["created"] = created


def purge_ids(plan: PlanModel, finding_ids: list[str]) -> int:
    """Remove finding IDs from the plan entirely.

    Cleans queue_order, skipped, and all cluster memberships.
    Does NOT touch overrides (descriptions/notes are kept for history).
    Returns count of IDs that were actually present somewhere.
    """
    ensure_plan_defaults(plan)
    found = 0

    order: list[str] = plan["queue_order"]
    skipped: dict[str, SkipEntry] = plan["skipped"]
    for fid in finding_ids:
        was_present = False
        if fid in order:
            order.remove(fid)
            was_present = True
        if fid in skipped:
            skipped.pop(fid)
            was_present = True
        for cluster in plan.get("clusters", {}).values():
            ids = cluster.get("finding_ids", [])
            if fid in ids:
                ids.remove(fid)
                was_present = True
        if was_present:
            found += 1

    return found


__all__ = [
    "add_to_cluster",
    "annotate_finding",
    "clear_focus",
    "create_cluster",
    "delete_cluster",
    "describe_finding",
    "move_cluster",
    "move_items",
    "purge_ids",
    "remove_from_cluster",
    "reset_plan",
    "resurface_stale_skips",
    "set_focus",
    "skip_items",
    "unskip_items",
]
