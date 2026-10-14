"""show command: dig into issues by file, directory, detector, or pattern."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from desloppify.app.commands.helpers.guardrails import print_triage_guardrail_info
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.state import require_issue_inventory
from desloppify.app.skill_docs import check_skill_version
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS, CommandError
from desloppify.base.output.terminal import colorize
from desloppify.base.tooling import check_config_staleness
from desloppify.engine.plan_state import load_plan
from desloppify.intelligence.narrative.core import NarrativeContext, compute_narrative

from .concerns_view import _show_concerns
from .dimension_views import (
    _load_dimension_issues,
    _render_clean_mechanical_dimension,
    _render_no_matches,
    _render_subjective_dimension,
    _render_subjective_views_guide,
)
from .payload import ShowPayloadMeta, build_show_payload
from .render import (
    render_issues,
    show_agent_plan,
    show_subjective_followup,
    write_show_output_file,
)
from .scope import load_matches, resolve_entity, resolve_noise, resolve_show_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShowOptions:
    """All user-facing show command options extracted once from argparse."""

    pattern_raw: str = ""
    show_code: bool = False
    chronic: bool = False
    no_budget: bool = False
    output_file: str | None = None
    top: int = 20

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> ShowOptions:
        return cls(
            pattern_raw=str(getattr(args, "pattern", "") or ""),
            show_code=bool(getattr(args, "code", False)),
            chronic=bool(getattr(args, "chronic", False)),
            no_budget=bool(getattr(args, "no_budget", False)),
            output_file=getattr(args, "output", None),
            top=int(getattr(args, "top", 20) or 20),
        )


def _handle_special_entity_views(
    *,
    entity,
    state: dict,
    config: dict,
    lang_name: str | None,
    pattern_raw: str,
) -> bool:
    if entity.kind == "special_view" and entity.pattern.strip().lower() == "concerns":
        _show_concerns(state, lang_name)
        return True
    if entity.kind == "dimension" and entity.is_subjective:
        _render_subjective_dimension(state, config, entity, pattern_raw)
        return True
    return False


def _load_entity_matches(
    *,
    state: dict,
    entity,
    pattern: str,
    status_filter: str,
    scope: str | None,
    chronic: bool,
) -> tuple[str, list[dict]] | None:
    if entity.kind != "dimension" or entity.is_subjective:
        return pattern, load_matches(
            state, scope=scope, status_filter=status_filter, chronic=chronic
        )
    matches = _load_dimension_issues(state, entity, status_filter)
    if not matches:
        _render_clean_mechanical_dimension(state, entity)
        return None
    return entity.display_name, matches


def _active_plan_or_none() -> dict | None:
    try:
        plan = load_plan()
    except PLAN_LOAD_EXCEPTIONS as exc:
        logger.debug("Show command skipped active-plan lookup.", exc_info=exc)
        return None
    if plan.get("queue_order") or plan.get("clusters"):
        return plan
    return None


def cmd_show(args: argparse.Namespace) -> None:
    """Show all issues for a file, directory, detector, or pattern."""
    runtime = command_runtime(args)
    state = runtime.state
    config = runtime.config

    if not require_issue_inventory(state):
        return

    skill_warning = check_skill_version()
    if skill_warning:
        print(colorize(f"  {skill_warning}", "yellow"))
    config_warning = check_config_staleness(config)
    if config_warning:
        print(colorize(f"  {config_warning}", "yellow"))

    print_triage_guardrail_info(state=state)

    opts = ShowOptions.from_args(args)

    ok, pattern, status_filter, scope = resolve_show_scope(args)
    if not ok or pattern is None:
        raise SystemExit(2)

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="show"),
    )

    entity = resolve_entity(pattern, state)
    if _handle_special_entity_views(
        entity=entity,
        state=state,
        config=config,
        lang_name=lang_name,
        pattern_raw=opts.pattern_raw,
    ):
        return

    match_result = _load_entity_matches(
        state=state,
        entity=entity,
        pattern=pattern,
        status_filter=status_filter,
        scope=scope,
        chronic=opts.chronic,
    )
    if match_result is None:
        return
    pattern, matches = match_result

    if not matches:
        _render_no_matches(entity, pattern, status_filter, narrative, state, config)
        return

    (
        surfaced_matches,
        hidden_by_detector,
        noise_budget,
        global_noise_budget,
        budget_warning,
    ) = resolve_noise(
        config,
        matches,
        no_budget=opts.no_budget,
    )
    hidden_total = sum(hidden_by_detector.values())

    payload = build_show_payload(
        surfaced_matches,
        pattern,
        status_filter,
        ShowPayloadMeta(
            total_matches=len(matches),
            hidden_by_detector=hidden_by_detector,
            noise_budget=noise_budget,
            global_noise_budget=global_noise_budget,
        ),
    )
    write_query({"command": "show", **payload, "narrative": narrative})

    if opts.output_file:
        if write_show_output_file(opts.output_file, payload, len(surfaced_matches)):
            return
        raise CommandError("Failed to write output file")

    render_issues(
        surfaced_matches,
        pattern=pattern,
        status_filter=status_filter,
        show_code=opts.show_code,
        top=opts.top,
        hidden_by_detector=hidden_by_detector,
        hidden_total=hidden_total,
        noise_budget=noise_budget,
        global_noise_budget=global_noise_budget,
        budget_warning=budget_warning,
    )
    plan_active = _active_plan_or_none()
    show_agent_plan(narrative, surfaced_matches, plan=plan_active)
    show_subjective_followup(
        state,
        target_strict_score_from_config(config),
    )

    _render_subjective_views_guide(entity)


__all__ = ["cmd_show"]
