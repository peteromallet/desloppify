"""State-application helpers for resolve command flows."""

from __future__ import annotations

import argparse

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query

from .selection import ResolveQueryContext


def _resolve_all_patterns(
    state: dict,
    args: argparse.Namespace,
    *,
    attestation: str | None,
) -> list[str]:
    all_resolved: list[str] = []
    for pattern in args.patterns:
        resolved = state_mod.resolve_findings(
            state,
            pattern,
            args.status,
            args.note,
            attestation=attestation,
        )
        all_resolved.extend(resolved)
    return all_resolved


def _write_resolve_query_entry(context: ResolveQueryContext) -> None:
    write_query(
        {
            "command": "resolve",
            "patterns": context.patterns,
            "status": context.status,
            "resolved": context.resolved,
            "count": len(context.resolved),
            "next_command": context.next_command,
            "overall_score": state_mod.get_overall_score(context.state),
            "objective_score": state_mod.get_objective_score(context.state),
            "strict_score": state_mod.get_strict_score(context.state),
            "verified_strict_score": state_mod.get_verified_strict_score(context.state),
            "prev_overall_score": context.prev_overall,
            "prev_objective_score": context.prev_objective,
            "prev_strict_score": context.prev_strict,
            "prev_verified_strict_score": context.prev_verified,
            "attestation": context.attestation,
            "narrative": context.narrative,
        }
    )
