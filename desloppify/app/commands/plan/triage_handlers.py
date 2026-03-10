"""Handler for ``plan triage`` subcommand."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan.triage import confirmations_router as _confirmations_router_mod
from desloppify.app.commands.plan.triage import display as _display_mod
from desloppify.app.commands.plan.triage import helpers as _helpers_mod
from desloppify.app.commands.plan.triage import services as _services_mod
from desloppify.app.commands.plan.triage import stage_completion_commands as _completion_mod
from desloppify.app.commands.plan.triage import stage_flow_commands as _flow_mod
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    TRIAGE_CMD_OBSERVE,
    append_log_entry,
    build_triage_prompt,
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
    load_plan,
    save_plan,
)

_triage_coverage = _helpers_mod.triage_coverage


def _build_triage_services() -> _services_mod.TriageServices:
    """Resolve triage dependencies from this module for easy monkeypatching."""
    return _services_mod.TriageServices(
        command_runtime=command_runtime,
        load_plan=load_plan,
        save_plan=save_plan,
        collect_triage_input=collect_triage_input,
        detect_recurring_patterns=detect_recurring_patterns,
        append_log_entry=append_log_entry,
        extract_issue_citations=extract_issue_citations,
        build_triage_prompt=build_triage_prompt,
    )


def _cmd_triage_start(
    args: argparse.Namespace,
    *,
    services: _services_mod.TriageServices | None = None,
) -> None:
    """Manually inject triage stage IDs into the queue and clear prior stages."""
    resolved_services = services or _build_triage_services()
    plan = resolved_services.load_plan()

    if _helpers_mod.has_triage_in_queue(plan):
        print(colorize("  Planning mode stages are already in the queue.", "yellow"))
        meta = plan.get("epic_triage_meta", {})
        stages = meta.get("triage_stages", {})
        if stages:
            print(
                colorize(
                    f"  {len(stages)} stage(s) in progress — clearing to restart.", "yellow"
                )
            )
            meta["triage_stages"] = {}
            _helpers_mod.inject_triage_stages(plan)
            resolved_services.save_plan(plan)
            resolved_services.append_log_entry(
                plan,
                "triage_start",
                actor="user",
                detail={"action": "restart", "cleared_stages": list(stages.keys())},
            )
            resolved_services.save_plan(plan)
            print(colorize("  Stages cleared. Begin with observe:", "green"))
        else:
            _helpers_mod.inject_triage_stages(plan)
            resolved_services.save_plan(plan)
            print(colorize("  Begin with observe:", "green"))
        print(colorize(f"    {TRIAGE_CMD_OBSERVE}", "dim"))
        return

    _helpers_mod.inject_triage_stages(plan)
    meta = plan.setdefault("epic_triage_meta", {})
    meta["triage_stages"] = {}
    resolved_services.save_plan(plan)

    resolved_services.append_log_entry(
        plan,
        "triage_start",
        actor="user",
        detail={"action": "start"},
    )
    resolved_services.save_plan(plan)

    runtime = resolved_services.command_runtime(args)
    si = resolved_services.collect_triage_input(plan, runtime.state)
    print(colorize("  Planning mode started (6 stages queued).", "green"))
    print(f"  Open review issues: {len(si.open_issues)}")
    print(colorize("  Begin with observe:", "dim"))
    print(colorize(f"    {TRIAGE_CMD_OBSERVE}", "dim"))


def cmd_plan_triage(args: argparse.Namespace) -> None:
    """Run epic triage: staged workflow OBSERVE → REFLECT → ORGANIZE → ENRICH → COMMIT."""
    resolved_services = _build_triage_services()
    runtime = resolved_services.command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    if getattr(args, "stage_prompt", None):
        from .triage.runner.stage_prompts import cmd_stage_prompt
        cmd_stage_prompt(args, services=resolved_services)
        return
    if getattr(args, "run_stages", False):
        from desloppify.base.output.terminal import colorize
        from .triage.runner.orchestrator_common import parse_only_stages
        runner = str(getattr(args, "runner", "codex")).strip().lower()
        try:
            stages_to_run = parse_only_stages(getattr(args, "only_stages", None))
        except ValueError as exc:
            print(colorize(f"  {exc}", "red"))
            return
        if runner == "claude":
            from .triage.runner.orchestrator_claude import run_claude_orchestrator
            run_claude_orchestrator(args, services=resolved_services)
        elif runner == "codex":
            from .triage.runner.orchestrator_codex_pipeline import run_codex_pipeline
            run_codex_pipeline(args, stages_to_run=stages_to_run, services=resolved_services)
        else:
            print(colorize(f"  Unknown runner: {runner}. Use 'codex' or 'claude'.", "red"))
        return

    if getattr(args, "start", False):
        _cmd_triage_start(args, services=resolved_services)
        return
    if getattr(args, "confirm", None):
        _confirmations_router_mod.cmd_confirm_stage(args, services=resolved_services)
        return
    if getattr(args, "complete", False):
        _completion_mod.cmd_triage_complete(args, services=resolved_services)
        return
    if getattr(args, "confirm_existing", False):
        _completion_mod.cmd_confirm_existing(args, services=resolved_services)
        return

    stage = getattr(args, "stage", None)
    if stage == "observe":
        _flow_mod.cmd_stage_observe(args, services=resolved_services)
        return
    if stage == "reflect":
        _flow_mod.cmd_stage_reflect(args, services=resolved_services)
        return
    if stage == "organize":
        _flow_mod.cmd_stage_organize(args, services=resolved_services)
        return
    if stage == "enrich":
        _flow_mod.cmd_stage_enrich(args, services=resolved_services)
        return
    if stage == "sense-check":
        _flow_mod.cmd_stage_sense_check(args, services=resolved_services)
        return
    if stage == "commit":
        _flow_mod.cmd_stage_commit(args, services=resolved_services)
        return

    # Default: show help
    print(colorize("  No valid stage specified.", "yellow"))
    print("  Usage: desloppify plan triage --stage <observe|reflect|organize|enrich|sense-check|commit>")
