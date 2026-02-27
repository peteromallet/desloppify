"""State-application helpers for resolve command flows."""

from __future__ import annotations

import argparse

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query_best_effort as _write_query_best_effort
from desloppify.core.output_contract import OutputResult

from .selection import ResolveQueryContext


def _try_expand_cluster(pattern: str) -> list[str] | None:
    """If pattern matches a cluster name, return its finding IDs."""
    try:
        from desloppify.engine.plan import has_living_plan, load_plan

        if not has_living_plan():
            return None
        plan = load_plan()
        cluster = plan.get("clusters", {}).get(pattern)
        if cluster and cluster.get("finding_ids"):
            return list(cluster["finding_ids"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
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
                resolved = state_mod.resolve_findings(
                    state,
                    fid,
                    args.status,
                    args.note,
                    attestation=attestation,
                )
                all_resolved.extend(resolved)
            continue

        resolved = state_mod.resolve_findings(
            state,
            pattern,
            args.status,
            args.note,
            attestation=attestation,
        )
        all_resolved.extend(resolved)
    return all_resolved


def write_query(payload: dict) -> OutputResult:
    """Backward-compatible resolve query writer seam."""
    return _write_query_best_effort(
        payload,
        context="resolve query payload update",
    )


def _write_resolve_query_entry(context: ResolveQueryContext) -> None:
    scores = state_mod.score_snapshot(context.state)
    write_query(
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
        }
    )
