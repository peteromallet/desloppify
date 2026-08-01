"""State-application helpers for resolve command flows."""

from __future__ import annotations

import argparse
import logging

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import (
    write_query_best_effort as _write_query_best_effort,
)
from desloppify.engine._plan.triage.protection import protected_review_issue_ids

from .plan_load import ResolvePlanAccess, load_resolve_plan_access
from .selection import ResolveQueryContext

_logger = logging.getLogger(__name__)


def _try_expand_cluster(
    pattern: str,
    *,
    plan_access: ResolvePlanAccess | None = None,
) -> list[str] | None:
    """If pattern matches a cluster name, return its issue IDs."""
    resolved_plan_access = plan_access or load_resolve_plan_access()
    plan = resolved_plan_access.usable_plan(
        behavior="Cluster-name pattern expansion is disabled until plan loading succeeds.",
    )
    if plan is None:
        _logger.debug(
            "cluster expansion skipped for %r because no usable living plan is available",
            pattern,
        )
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
    plan_access: ResolvePlanAccess | None = None,
) -> list[str]:
    all_resolved: list[str] = []
    resolved_plan_access = plan_access or load_resolve_plan_access()
    plan = resolved_plan_access.usable_plan(
        behavior="Protected review holds are unavailable until plan loading succeeds.",
    )
    protected_ids = protected_review_issue_ids(plan)
    for pattern in args.patterns:
        # Check if pattern is a cluster name — expand to member IDs
        cluster_ids = _try_expand_cluster(pattern, plan_access=resolved_plan_access)
        if cluster_ids:
            for fid in cluster_ids:
                if fid in protected_ids:
                    continue
                resolved = state_mod.resolve_issues(
                    state,
                    fid,
                    args.status,
                    args.note,
                    attestation=attestation,
                )
                all_resolved.extend(resolved)
            continue

        if pattern in protected_ids:
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
