"""Queue-order enforcement helpers for resolve command flows."""

from __future__ import annotations

import logging

from desloppify.base.output.terminal import colorize
from desloppify.engine._work_queue.context import (
    queue_context,
    resolve_plan_load_status,
)
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    build_work_queue,
)
from desloppify.engine._work_queue.plan_order import collapse_clusters

from .plan_load import warn_plan_load_degraded_once

_logger = logging.getLogger(__name__)


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
) -> bool:
    """Warn and block if resolving items not at the front of the plan queue."""
    if status != "fixed":
        return False
    plan_status = resolve_plan_load_status()
    if plan_status.degraded:
        _logger.debug(
            "queue order guard skipped due to degraded plan load (%s)",
            plan_status.error_kind,
        )
        warn_plan_load_degraded_once(
            error_kind=plan_status.error_kind,
            behavior="Queue-order enforcement is disabled until plan loading succeeds.",
        )
        return False

    plan = plan_status.plan
    if not isinstance(plan, dict):
        return False
    queue_order = plan.get("queue_order", [])
    if not queue_order:
        return False

    ctx = queue_context(state, plan=plan)
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
    issues = state.get("issues", {})
    resolved_ids = _resolve_target_ids(patterns, clusters)
    resolved_ids = _filter_open_or_cluster_targets(
        resolved_ids,
        clusters=clusters,
        issues=issues,
    )
    if not resolved_ids:
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
