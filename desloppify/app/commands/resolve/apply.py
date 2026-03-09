"""State-application helpers for resolve command flows."""

from __future__ import annotations

import argparse
import logging

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import (
    write_query_best_effort as _write_query_best_effort,
)
from desloppify.engine._work_queue.context import resolve_plan_load_status

from .plan_load import warn_plan_load_degraded_once
from .selection import ResolveQueryContext

_logger = logging.getLogger(__name__)


def _try_expand_cluster(pattern: str) -> list[str] | None:
    """If pattern matches a cluster name, return its issue IDs."""
    plan_status = resolve_plan_load_status()
    if plan_status.degraded:
        _logger.debug(
            "cluster expansion skipped for %r due to degraded plan load (%s)",
            pattern,
            plan_status.error_kind,
        )
        warn_plan_load_degraded_once(
            error_kind=plan_status.error_kind,
            behavior=(
                "Cluster-name pattern expansion is disabled until plan loading succeeds."
            ),
        )
        return None
    plan = plan_status.plan
    if not isinstance(plan, dict):
        return None
    cluster = plan.get("clusters", {}).get(pattern)
    if cluster and cluster.get("issue_ids"):
        return list(cluster["issue_ids"])
    return None


def _resolve_all_patterns(
    state: dict,
    args: argparse.Namespace,
    *,
    attestation: str | None,
) -> list[str]:
    all_resolved: list[str] = []
    for pattern in args.patterns:
        # Check if pattern is a cluster name — expand to member IDs
        cluster_ids = _try_expand_cluster(pattern)
        if cluster_ids:
            for fid in cluster_ids:
                resolved = state_mod.resolve_issues(
                    state,
                    fid,
                    args.status,
                    args.note,
                    attestation=attestation,
                )
                all_resolved.extend(resolved)
            continue

        resolved = state_mod.resolve_issues(
            state,
            pattern,
            args.status,
            args.note,
            attestation=attestation,
        )
        all_resolved.extend(resolved)
    return all_resolved

def _write_resolve_query_entry(context: ResolveQueryContext) -> None:
    scores = state_mod.score_snapshot(context.state)
    _write_query_best_effort(
        {
            "command": "resolve",
            "patterns": context.patterns,
            "status": context.status,
            "resolved": context.resolved,
            "count": len(context.resolved),
            "next_command": context.next_command,
            "overall_score": scores.overall,
            "objective_score": scores.objective,
            "strict_score": scores.strict,
            "verified_strict_score": scores.verified,
            "prev_overall_score": context.prev_overall,
            "prev_objective_score": context.prev_objective,
            "prev_strict_score": context.prev_strict,
            "prev_verified_strict_score": context.prev_verified,
            "attestation": context.attestation,
            "narrative": context.narrative,
        },
        context="resolve query payload update",
    )
