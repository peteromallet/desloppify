"""show command: dig into findings by file, directory, detector, or pattern."""

from __future__ import annotations

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.utils import check_tool_staleness, colorize

from .payload import ShowPayloadMeta, build_show_payload
from .render import (
    render_findings,
    show_agent_plan,
    show_subjective_followup,
    write_show_output_file,
)
from .scope import load_matches, resolve_noise, resolve_show_scope


def cmd_show(args) -> None:
    """Show all findings for a file, directory, detector, or pattern."""
    runtime = command_runtime(args)
    state = runtime.state
    config = runtime.config

    if not require_completed_scan(state):
        return

    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    show_code = getattr(args, "code", False)
    chronic = getattr(args, "chronic", False)
    ok, pattern, status_filter, scope = resolve_show_scope(args)
    if not ok or pattern is None:
        return

    matches = load_matches(state, scope=scope, status_filter=status_filter, chronic=chronic)
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="show"),
    )

    if not matches:
        print(colorize(f"No {status_filter} findings matching: {pattern}", "yellow"))
        write_query(
            {
                "command": "show",
                "query": pattern,
                "status_filter": status_filter,
                "total": 0,
                "findings": [],
                "narrative": narrative,
            }
        )
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

    output_file = getattr(args, "output", None)
    if output_file:
        if write_show_output_file(output_file, payload, len(surfaced_matches)):
            return
        raise SystemExit(1)

    top = getattr(args, "top", 20) or 20
    render_findings(
        surfaced_matches,
        pattern=pattern,
        status_filter=status_filter,
        show_code=show_code,
        top=top,
        hidden_by_detector=hidden_by_detector,
        hidden_total=hidden_total,
        noise_budget=noise_budget,
        global_noise_budget=global_noise_budget,
        budget_warning=budget_warning,
    )
    show_agent_plan(narrative, surfaced_matches)
    show_subjective_followup(
        state,
        target_strict_score_from_config(config, fallback=95.0),
    )


__all__ = ["cmd_show"]
