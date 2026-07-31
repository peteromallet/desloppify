"""Queue-order enforcement helpers for resolve command flows."""

from __future__ import annotations

import logging

from desloppify.base.config import load_config
from desloppify.base.output.terminal import colorize
from desloppify.engine._work_queue.context import (
    queue_context,
)
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine._work_queue.plan_order import collapse_clusters
from desloppify.engine.planning.queue_policy import build_execution_queue

from .plan_load import ResolvePlanAccess, load_resolve_plan_access

_logger = logging.getLogger(__name__)

# Backward-compatible test seam: queue-order enforcement now uses the execution queue.
build_work_queue = build_execution_queue


def _front_item_ids(front_item: dict) -> tuple[str, set[str]]:
    front_id = front_item["id"]
    front_ids = {front_id}
    if front_item.get("kind") != "cluster":
        return front_id, front_ids
    for member in front_item.get("members", []):
        front_ids.add(member["id"])
    return front_id, front_ids


def _resolve_target_ids(patterns: list[str], clusters: dict) -> set[str]:
    resolved_ids: set[str] = set()
    for pattern in patterns:
        if pattern in clusters:
            resolved_ids.update(clusters[pattern].get("issue_ids", []))
            resolved_ids.add(pattern)
            continue
        resolved_ids.add(pattern)
    return resolved_ids


def _filter_open_or_cluster_targets(
    resolved_ids: set[str],
    *,
    clusters: dict,
    issues: dict,
) -> set[str]:
    return {
        issue_id
        for issue_id in resolved_ids
        if issue_id in clusters
        or (issue_id in issues and issues[issue_id].get("status") == "open")
    }


def _front_planned_issue_ids(
    queue_order: list[str],
    *,
    issues: dict,
    depth: int,
) -> set[str]:
    """Return the first N live issue IDs from the persisted queue order."""
    if depth <= 0:
        return set()
    front: list[str] = []
    for issue_id in queue_order:
        issue = issues.get(issue_id)
        if not isinstance(issue, dict) or issue.get("status") != "open":
            continue
        front.append(issue_id)
        if len(front) >= depth:
            break
    return set(front)


def _prune_front_covered_clusters(
    out_of_order: set[str],
    *,
    clusters: dict,
    issues: dict,
    front_ids: set[str],
) -> None:
    for cluster_id in list(out_of_order):
        if cluster_id not in clusters:
            continue
        alive_members = {
            issue_id
            for issue_id in clusters[cluster_id].get("issue_ids", [])
            if issue_id in issues and issues[issue_id].get("status") == "open"
        }
        if alive_members and alive_members <= front_ids:
            out_of_order.discard(cluster_id)


def _print_queue_order_violation(front_id: str, out_of_order: set[str]) -> None:
    print(colorize("\n  Queue order violation: these items are not next in the plan queue:\n", "yellow"))
    for issue_id in sorted(out_of_order):
        print(f"    {issue_id}")
    print(colorize(f"\n  The current next item is: {front_id}", "dim"))
    print(colorize("  Items must be resolved in plan order. If you need to reprioritize:", "dim"))
    print(colorize("    desloppify plan reorder <pattern> top            # move to front", "dim"))
    print(colorize("    desloppify plan skip <pattern> --reason '...'    # skip for now", "dim"))
    print(colorize("    desloppify next                                  # see what's next\n", "dim"))


def _check_queue_order_guard(
    state: dict,
    patterns: list[str],
    status: str,
    *,
    plan_access: ResolvePlanAccess | None = None,
) -> bool:
    """Warn and block if resolving items not at the front of the plan queue."""
    if status != "fixed":
        return False
    resolved_plan_access = plan_access or load_resolve_plan_access()
    plan = resolved_plan_access.usable_plan(
        behavior="Queue-order enforcement is disabled until plan loading succeeds.",
    )
    if plan is None:
        _logger.debug(
            "queue order guard skipped because no usable living plan is available",
        )
        return False
    queue_order = plan.get("queue_order", [])
    if not queue_order:
        return False

    # Resolve with the same configured threshold as ``desloppify next``.
    # Otherwise a project target below the default 95 can make resolve see
    # synthetic re-review work while next correctly presents its planned packet.
    ctx = queue_context(state, plan=plan, config=load_config())
    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            include_subjective=True,
            context=ctx,
        ),
    )
    items = result["items"]
    if not plan.get("active_cluster"):
        items = collapse_clusters(items, plan)
    if not items:
        return False

    clusters = plan.get("clusters", {})
    issues = (state.get("work_items") or state.get("issues", {}))
    resolved_ids = _resolve_target_ids(patterns, clusters)
    resolved_ids = _filter_open_or_cluster_targets(
        resolved_ids,
        clusters=clusters,
        issues=issues,
    )
    if not resolved_ids:
        return False

    resolved_issue_ids = {issue_id for issue_id in resolved_ids if issue_id in issues}
    if resolved_issue_ids:
        planned_front_ids = _front_planned_issue_ids(
            queue_order,
            issues=issues,
            depth=max(len(resolved_issue_ids), 1),
        )
        if resolved_issue_ids <= planned_front_ids:
            return False

    # Collect IDs from the first N queue positions where N is the
    # number of items being resolved.  This allows batch-resolving
    # a contiguous prefix (e.g. the first 9 items in one command).
    prefix_depth = max(len(resolved_ids), 1)
    front_ids: set[str] = set()
    front_id = items[0]["id"]
    for item in items[:prefix_depth]:
        _, item_ids = _front_item_ids(item)
        front_ids.update(item_ids)

    out_of_order = resolved_ids - front_ids
    _prune_front_covered_clusters(
        out_of_order,
        clusters=clusters,
        issues=issues,
        front_ids=front_ids,
    )
    if not out_of_order:
        return False

    _print_queue_order_violation(front_id, out_of_order)
    return True


__all__ = ["_check_queue_order_guard"]
