"""Living-plan update helpers used by resolve command."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import NamedTuple

from desloppify.app.commands.helpers.transition_messages import emit_transition_message
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.app.commands.resolve.plan_load import warn_plan_load_degraded_once
from desloppify.engine._plan.sync import live_planned_queue_empty, reconcile_plan
from desloppify.engine.plan_ops import (
    append_log_entry,
    auto_complete_steps,
    purge_ids,
)
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_EXECUTE,
    clear_postflight_scan_completion,
)
from desloppify.engine.plan_state import (
    add_uncommitted_issues,
    has_living_plan,
    load_plan,
    plan_path_for_state,
    purge_uncommitted_ids,
    save_plan,
)

_logger = logging.getLogger(__name__)


class ClusterContext(NamedTuple):
    cluster_name: str | None
    cluster_completed: bool
    cluster_remaining: int


def _reconcile_if_queue_drained(plan: dict, state: dict | None) -> str | None:
    """Advance the living plan when a resolve drains the explicit live queue.

    Returns the new lifecycle phase if a transition occurred, so the caller
    can emit the directive after all other output.
    """
    if state is None or not live_planned_queue_empty(plan):
        return None
    target_strict = target_strict_score_from_config(state.get("config"))
    result = reconcile_plan(plan, state, target_strict=target_strict)
    if result is not None and result.lifecycle_phase_changed:
        return result.lifecycle_phase
    return None


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
    state: dict | None = None,
    state_file: Path | str | None = None,
) -> tuple[dict | None, ClusterContext]:
    """Apply resolve side effects to the living plan when it exists."""
    plan_path = plan_path_for_state(Path(state_file)) if state_file else None
    plan = None
    ctx = ClusterContext(cluster_name=None, cluster_completed=False, cluster_remaining=0)
    try:
        if not has_living_plan(plan_path):
            return None, ctx
        plan = load_plan(plan_path)
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
            # Clear focus when cluster is done
            if plan.get("active_cluster") == ctx.cluster_name:
                plan["active_cluster"] = None
        elif ctx.cluster_name and ctx.cluster_remaining > 0:
            # Auto-focus on the cluster while there's still work in it
            plan["active_cluster"] = ctx.cluster_name
        if args.status == "fixed":
            add_uncommitted_issues(plan, all_resolved)
        elif args.status == "open":
            purge_uncommitted_ids(plan, all_resolved)
        transition_phase: str | None = None
        if clear_postflight_scan_completion(plan, issue_ids=all_resolved, state=state):
            transition_phase = LIFECYCLE_PHASE_EXECUTE
        reconcile_phase = _reconcile_if_queue_drained(plan, state)
        if reconcile_phase:
            transition_phase = reconcile_phase
        save_plan(plan, plan_path)
        if purged:
            print(colorize(f"  Plan updated: {purged} item(s) removed from queue.", "dim"))
        if transition_phase:
            emit_transition_message(transition_phase)
    except PLAN_LOAD_EXCEPTIONS as exc:
        _logger.debug("plan update failed after resolve", exc_info=True)
        warn_plan_load_degraded_once(
            command_label="resolve",
            error_kind=exc.__class__.__name__,
            behavior="Living-plan queue metadata could not be updated after resolve.",
        )
    return plan, ctx


__all__ = ["ClusterContext", "capture_cluster_context", "update_living_plan_after_resolve"]
