"""status command: score dashboard with per-tier progress."""

from __future__ import annotations

import argparse
import json
import logging

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.queue_progress import (
    get_plan_start_strict,
    plan_aware_queue_count,
    print_frozen_score_with_queue_context,
)
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.core.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.app.commands.scan import (
    scan_reporting_dimensions as reporting_dimensions_mod,
)
from desloppify.app.commands.status_parts.render import (
    print_open_scope_breakdown,
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
from desloppify.engine.plan import load_plan
from desloppify.engine.planning.scorecard_projection import (
    scorecard_dimensions_payload,
)
from desloppify.core.output_api import colorize
from desloppify.core.skill_docs import check_skill_version
from desloppify.core.tooling import check_config_staleness, check_tool_staleness
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.scoring import compute_health_breakdown


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
    config_warning = check_config_staleness(config)
    if config_warning:
        print(colorize(f"  {config_warning}", "yellow"))

    scores = state_mod.score_snapshot(state)
    by_tier = stats.get("by_tier", {})
    target_strict_score = target_strict_score_from_config(config, fallback=95.0)

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None

    # Load living plan for plan-aware rendering and narrative
    _plan = load_plan()
    _plan_active = _plan if (
        _plan.get("queue_order") or _plan.get("clusters")
    ) else None

    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="status", plan=_plan_active),
    )
    ignores = config.get("ignore", [])

    # Show frozen plan-start score when in an active queue cycle
    _plan_start_strict = get_plan_start_strict(_plan)
    _status_queue_remaining = 0
    if _plan_start_strict is not None:
        try:
            _status_queue_remaining = plan_aware_queue_count(state, _plan)
        except PLAN_LOAD_EXCEPTIONS as exc:
            logging.debug("Plan-aware queue count failed: %s", exc)
            _status_queue_remaining = 0
    if _plan_start_strict is not None and _status_queue_remaining > 0:
        print_frozen_score_with_queue_context(_plan, _status_queue_remaining)
    else:
        for line, style in score_summary_lines(
            overall_score=scores.overall,
            objective_score=scores.objective,
            strict_score=scores.strict,
            verified_strict_score=scores.verified,
            target_strict=target_strict_score,
        ):
            print(colorize(line, style))
    print_scan_metrics(state)
    print_open_scope_breakdown(state)
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
        show_focus_suggestion(dim_scores, state, plan=_plan_active)
        show_subjective_followup(
            state,
            dim_scores,
            target_strict_score=target_strict_score,
        )

    show_review_summary(state)
    show_structural_areas(state)
    show_agent_plan(narrative, plan=_plan_active)

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
        plan=_plan_active,
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
    findings = state.get("findings", {})
    open_scope = (
        state_mod.open_scope_breakdown(findings, state.get("scan_path"))
        if isinstance(findings, dict)
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

__all__ = [
    "cmd_status",
    "show_dimension_table",
    "show_focus_suggestion",
    "show_ignore_summary",
    "show_structural_areas",
    "show_subjective_followup",
]
