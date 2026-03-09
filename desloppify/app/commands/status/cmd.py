"""status command: score dashboard with per-tier progress."""

from __future__ import annotations

import argparse
import json

from desloppify import state as state_mod
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.engine._scoring.results.core import compute_health_breakdown
from desloppify.engine.planning.scorecard_projection import (
    scorecard_dimensions_payload,
)

from .flow import render_terminal_status


def cmd_status(args: argparse.Namespace) -> None:
    """Show score dashboard."""
    runtime = command_runtime(args)
    state = runtime.state
    config = runtime.config

    stats = state.get("stats", {})
    dim_scores = state.get("dimension_scores", {}) or {}
    scorecard_dims = scorecard_dimensions_payload(state, dim_scores=dim_scores)
    subjective_measures = [row for row in scorecard_dims if row.get("subjective")]
    suppression = state_mod.suppression_metrics(state)

    if getattr(args, "json", False):
        print(
            json.dumps(
                _status_json_payload(
                    state,
                    stats,
                    dim_scores,
                    scorecard_dims,
                    subjective_measures,
                    suppression,
                ),
                indent=2,
            )
        )
        return

    if not require_completed_scan(state):
        return

    render_terminal_status(
        args,
        state=state,
        config=config,
        stats=stats,
        dim_scores=dim_scores,
        scorecard_dims=scorecard_dims,
        subjective_measures=subjective_measures,
        suppression=suppression,
    )


def _status_json_payload(
    state: dict,
    stats: dict,
    dim_scores: dict,
    scorecard_dims: list[dict],
    subjective_measures: list[dict],
    suppression: dict,
) -> dict:
    scores = state_mod.score_snapshot(state)
    issues = state.get("issues", {})
    open_scope = (
        state_mod.open_scope_breakdown(issues, state.get("scan_path"))
        if isinstance(issues, dict)
        else None
    )
    return {
        "overall_score": scores.overall,
        "objective_score": scores.objective,
        "strict_score": scores.strict,
        "verified_strict_score": scores.verified,
        "dimension_scores": dim_scores,
        "score_breakdown": compute_health_breakdown(dim_scores) if dim_scores else None,
        "scorecard_dimensions": scorecard_dims,
        "subjective_measures": subjective_measures,
        "potentials": state.get("potentials"),
        "codebase_metrics": state.get("codebase_metrics"),
        "stats": stats,
        "open_scope": open_scope,
        "suppression": suppression,
        "scan_count": state.get("scan_count", 0),
        "last_scan": state.get("last_scan"),
    }

__all__ = ["cmd_status"]
