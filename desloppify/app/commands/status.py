"""status command: score dashboard with per-tier progress."""

from __future__ import annotations

import argparse
import json

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.scan import (
    scan_reporting_dimensions as reporting_dimensions_mod,
)
from desloppify.app.commands.status_parts.render import (
    print_scan_completeness,
    print_scan_metrics,
    score_summary_lines,
    show_agent_plan,
    show_dimension_table,
    show_focus_suggestion,
    show_ignore_summary,
    show_review_summary,
    show_structural_areas,
    show_subjective_followup,
    show_tier_progress_table,
    write_status_query,
)
from desloppify.app.output.scorecard_parts.projection import (
    scorecard_dimensions_payload,
)
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.scoring import compute_health_breakdown
from desloppify.utils import check_skill_version, check_tool_staleness, colorize


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

    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))
    skill_warning = check_skill_version()
    if skill_warning:
        print(colorize(f"  {skill_warning}", "yellow"))

    scores = state_mod.score_snapshot(state)
    by_tier = stats.get("by_tier", {})
    target_strict_score = target_strict_score_from_config(config, fallback=95.0)

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="status"),
    )
    ignores = config.get("ignore", [])

    for line, style in score_summary_lines(
        overall_score=scores.overall,
        objective_score=scores.objective,
        strict_score=scores.strict,
        verified_strict_score=scores.verified,
    ):
        print(colorize(line, style))
    print_scan_metrics(state)
    print_scan_completeness(state)

    if dim_scores:
        show_dimension_table(state, dim_scores)
        reporting_dimensions_mod.show_score_model_breakdown(
            state,
            dim_scores=dim_scores,
        )
    else:
        show_tier_progress_table(by_tier)

    if dim_scores:
        show_focus_suggestion(dim_scores, state)
        show_subjective_followup(
            state,
            dim_scores,
            target_strict_score=target_strict_score,
        )

    show_review_summary(state)
    show_structural_areas(state)
    show_agent_plan(narrative)

    if narrative.get("headline"):
        print(colorize(f"  -> {narrative['headline']}", "cyan"))
        print()

    if ignores:
        show_ignore_summary(ignores, suppression)

    review_age = config.get("review_max_age_days", 30)
    if review_age != 30:
        label = "never" if review_age == 0 else f"{review_age} days"
        print(colorize(f"  Review staleness: {label}", "dim"))
    print()

    write_status_query(
        state=state,
        stats=stats,
        by_tier=by_tier,
        dim_scores=dim_scores,
        scorecard_dims=scorecard_dims,
        subjective_measures=subjective_measures,
        suppression=suppression,
        narrative=narrative,
        ignores=ignores,
        overall_score=scores.overall,
        objective_score=scores.objective,
        strict_score=scores.strict,
        verified_strict_score=scores.verified,
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
        "suppression": suppression,
        "scan_count": state.get("scan_count", 0),
        "last_scan": state.get("last_scan"),
    }

__all__ = [
    "cmd_status",
    "show_dimension_table",
    "show_focus_suggestion",
    "show_ignore_summary",
    "show_structural_areas",
    "show_subjective_followup",
]
