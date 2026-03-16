"""Terminal rendering flow for the status command."""

from __future__ import annotations

import argparse
import logging

from desloppify.app.commands.helpers.guardrails import print_triage_guardrail_info
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.queue_progress import (
    ScoreDisplayMode,
    format_queue_block,
    get_plan_start_strict,
    plan_aware_queue_breakdown,
    print_frozen_score_with_queue_context,
    print_objective_drained_banner,
    score_display_mode,
)
from desloppify.app.commands.next.render_nudges import render_uncommitted_reminder
from desloppify.app.commands.scan.reporting import (
    dimensions as reporting_dimensions_mod,
)
from desloppify.app.skill_docs import check_skill_version
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.base.tooling import check_config_staleness
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine.plan_state import load_plan
from desloppify.intelligence.narrative.core import NarrativeContext, compute_narrative
from desloppify.state_io import StateModel
from desloppify.state_scoring import ScoreSnapshot, score_snapshot

from .render import (
    StatusQueryRequest,
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

_logger = logging.getLogger(__name__)


def _print_status_warnings(config: dict) -> None:
    if config.get("hermes_enabled"):
        print(colorize(
            '  ⚕ Hermes agent mode — model switching, autoreply, task handoff active'
            '\n    To disable: set "hermes_enabled": false in config.json',
            "cyan",
        ))
    skill_warning = check_skill_version()
    if skill_warning:
        print(colorize(f"  {skill_warning}", "yellow"))
    config_warning = check_config_staleness(config)
    if config_warning:
        print(colorize(f"  {config_warning}", "yellow"))


def _active_plan(plan: dict) -> dict | None:
    return plan if (plan.get("queue_order") or plan.get("clusters")) else None


def _build_status_context(
    args: argparse.Namespace,
    *,
    state: dict,
    config: dict,
    target_strict_score: float,
) -> tuple[dict, object, dict, list[str]]:
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    plan = load_plan()
    active_plan = _active_plan(plan)
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="status", plan=active_plan),
    )
    queue_ctx = queue_context(
        state,
        config=config,
        plan=active_plan,
        target_strict=target_strict_score,
    )
    ignores = config.get("ignore", [])
    return plan, queue_ctx, narrative, ignores


def _show_status_progress(
    *,
    state: dict,
    dim_scores: dict,
    by_tier: dict,
    objective_backlog: int,
    plan: dict | None,
    target_strict_score: float,
) -> None:
    if dim_scores:
        show_dimension_table(state, dim_scores, objective_backlog=objective_backlog)
        reporting_dimensions_mod.show_score_model_breakdown(state, dim_scores=dim_scores)
        show_focus_suggestion(dim_scores, state, plan=plan)
        show_subjective_followup(
            state,
            dim_scores,
            target_strict_score=target_strict_score,
            objective_backlog=objective_backlog,
        )
        return
    show_tier_progress_table(by_tier)


def _print_review_staleness(review_age: object) -> None:
    if review_age == 30:
        return
    label = "never" if review_age == 0 else f"{review_age} days"
    print(colorize(f"  Review staleness: {label}", "dim"))


def print_score_section(
    state: StateModel,
    scores: ScoreSnapshot,
    plan: dict,
    target_strict_score: float | None,
    ctx: object | None = None,
):
    """Print score header using live or frozen plan-start mode."""
    plan_start_strict = get_plan_start_strict(plan)
    breakdown = None
    try:
        breakdown = plan_aware_queue_breakdown(state, plan, context=ctx)
    except PLAN_LOAD_EXCEPTIONS as exc:
        _logger.debug("Plan-aware queue count failed: %s", exc)

    mode = score_display_mode(breakdown, plan_start_strict)
    if mode is ScoreDisplayMode.FROZEN:
        print_frozen_score_with_queue_context(
            breakdown,
            frozen_strict=plan_start_strict,
            live_score=scores.strict,
        )
    else:
        for line, style in score_summary_lines(
            overall_score=scores.overall,
            objective_score=scores.objective,
            strict_score=scores.strict,
            verified_strict_score=scores.verified,
            target_strict=target_strict_score,
        ):
            print(colorize(line, style))
        if breakdown is not None and breakdown.queue_total > 0:
            block = format_queue_block(breakdown)
            for text, style in block:
                print(colorize(text, style))
        if mode is ScoreDisplayMode.PHASE_TRANSITION:
            print_objective_drained_banner(plan_start_strict, breakdown.queue_total, breakdown)
    return breakdown


def render_terminal_status(
    args: argparse.Namespace,
    *,
    state: dict,
    config: dict,
    stats: dict,
    dim_scores: dict,
    scorecard_dims: list[dict],
    subjective_measures: list[dict],
    suppression: dict,
) -> None:
    """Render full terminal status output and write status query payload."""
    _print_status_warnings(config)
    scores = score_snapshot(state)
    by_tier = stats.get("by_tier", {})
    target_strict_score = target_strict_score_from_config(config)
    plan, queue_ctx, narrative, ignores = _build_status_context(
        args,
        state=state,
        config=config,
        target_strict_score=target_strict_score,
    )
    active_plan = _active_plan(plan)

    print_triage_guardrail_info(plan=plan, state=state)

    print_score_section(state, scores, plan, target_strict_score, queue_ctx)
    print_scan_metrics(state)
    print_open_scope_breakdown(state)
    print_scan_completeness(state)

    objective_backlog = queue_ctx.snapshot.objective_in_scope_count
    _show_status_progress(
        state=state,
        dim_scores=dim_scores,
        by_tier=by_tier,
        objective_backlog=objective_backlog,
        plan=active_plan,
        target_strict_score=target_strict_score,
    )

    show_review_summary(state)
    show_structural_areas(state)

    try:
        render_uncommitted_reminder(active_plan)
    except PLAN_LOAD_EXCEPTIONS:
        _logger.debug("commit tracking reminder skipped", exc_info=True)

    show_agent_plan(narrative, plan=active_plan)

    if narrative.get("headline"):
        print(colorize(f"  -> {narrative['headline']}", "cyan"))
        print()

    if ignores:
        show_ignore_summary(ignores, suppression)

    review_age = config.get("review_max_age_days", 30)
    _print_review_staleness(review_age)
    print()

    write_status_query(
        StatusQueryRequest(
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
            plan=active_plan,
        )
    )


__all__ = ["print_score_section", "render_terminal_status"]
