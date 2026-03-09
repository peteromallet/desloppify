"""Living-plan update helpers used by resolve command."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import NamedTuple

from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    add_uncommitted_issues,
    append_log_entry,
    auto_complete_steps,
    has_living_plan,
    load_plan,
    purge_ids,
    purge_uncommitted_ids,
    save_plan,
)

_logger = logging.getLogger(__name__)


class ClusterContext(NamedTuple):
    cluster_name: str | None
    cluster_completed: bool
    cluster_remaining: int


def capture_cluster_context(plan: dict, resolved_ids: list[str]) -> ClusterContext:
    """Determine cluster membership for resolved issues before purge."""
    clusters = plan.get("clusters") or {}
    overrides = plan.get("overrides") or {}
    cluster_name: str | None = None
    for resolved_id in resolved_ids:
        override = overrides.get(resolved_id)
        if override and override.get("cluster"):
            cluster_name = override["cluster"]
            break
    if not cluster_name or cluster_name not in clusters:
        return ClusterContext(cluster_name=None, cluster_completed=False, cluster_remaining=0)
    current_ids = set(clusters[cluster_name].get("issue_ids") or [])
    remaining = current_ids - set(resolved_ids)
    return ClusterContext(
        cluster_name=cluster_name,
        cluster_completed=len(remaining) == 0,
        cluster_remaining=len(remaining),
    )


def update_living_plan_after_resolve(
    *,
    args: argparse.Namespace,
    all_resolved: list[str],
    attestation: str | None,
) -> tuple[dict | None, ClusterContext]:
    """Apply resolve side effects to the living plan when it exists."""
    plan = None
    ctx = ClusterContext(cluster_name=None, cluster_completed=False, cluster_remaining=0)
    try:
        if not has_living_plan():
            return None, ctx
        plan = load_plan()
        ctx = capture_cluster_context(plan, all_resolved)
        purged = purge_ids(plan, all_resolved)
        step_messages = auto_complete_steps(plan)
        for msg in step_messages:
            print(colorize(msg, "green"))
        append_log_entry(
            plan,
            "resolve",
            issue_ids=all_resolved,
            actor="user",
            note=getattr(args, "note", None),
            detail={"status": args.status, "attestation": attestation},
        )
        if ctx.cluster_completed and ctx.cluster_name:
            append_log_entry(
                plan,
                "cluster_done",
                issue_ids=all_resolved,
                cluster_name=ctx.cluster_name,
                actor="user",
            )
        if args.status == "fixed":
            add_uncommitted_issues(plan, all_resolved)
        elif args.status == "open":
            purge_uncommitted_ids(plan, all_resolved)
        save_plan(plan)
        if purged:
            print(colorize(f"  Plan updated: {purged} item(s) removed from queue.", "dim"))
    except PLAN_LOAD_EXCEPTIONS:
        _logger.debug("plan update failed after resolve", exc_info=True)
        print(colorize("  Warning: could not update living plan.", "yellow"), file=sys.stderr)
    return plan, ctx


__all__ = ["ClusterContext", "capture_cluster_context", "update_living_plan_after_resolve"]
