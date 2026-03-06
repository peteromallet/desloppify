"""Reflect stage handler for plan triage."""

from __future__ import annotations

import argparse
import re

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.base.subjective_dimensions import DISPLAY_NAMES
from desloppify.engine._plan.epic_triage import (
    collect_triage_input,
    detect_recurring_patterns,
)
from desloppify.engine.plan import load_plan, plan_path_for_state

from .stage_helpers import _require_triage_pending, _validate_stage_report
from .stage_persistence import record_triage_stage


def _normalize_report_text(text: str) -> str:
    return " ".join(str(text).strip().lower().replace("_", " ").split())


def _dimension_report_aliases(dimension: str) -> set[str]:
    aliases: set[str] = set()
    canonical = _normalize_report_text(dimension)
    if canonical:
        aliases.add(canonical)
    display_name = DISPLAY_NAMES.get(dimension, "")
    display = _normalize_report_text(display_name)
    if display:
        aliases.add(display)
    return aliases


def _report_mentions_dimension(report: str, dimension: str) -> bool:
    normalized_report = _normalize_report_text(report)
    if not normalized_report:
        return False
    padded_report = f" {normalized_report} "
    for alias in _dimension_report_aliases(dimension):
        if alias and f" {alias} " in padded_report:
            return True
        if alias and re.search(rf"\b{re.escape(alias)}\b", normalized_report):
            return True
    return False


def cmd_stage_reflect(args: argparse.Namespace) -> None:
    """Record the REFLECT stage: compare current issues against completed work."""
    report: str | None = getattr(args, "report", None)

    runtime = command_runtime(args)
    state = runtime.state
    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)

    if not _require_triage_pending(plan, action="reflect"):
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    if "observe" not in stages:
        print(colorize("  Cannot reflect: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return

    si = collect_triage_input(plan, state)
    issue_count = len(si.open_issues)

    min_chars = 50 if issue_count <= 3 else 100
    validated_report = _validate_stage_report(
        report,
        stage="reflect",
        min_chars=min_chars,
        missing_guidance=[
            "Compare current issues against completed work and form a holistic strategy:",
            "- What clusters were previously completed? Did fixes hold?",
            "- Are any dimensions recurring (resolved before, open again)?",
            "- What contradictions did you find? Which direction will you take?",
            "- Big picture: what to prioritize, what to defer, what to skip?",
        ],
        short_guidance=[
            "Describe how current issues relate to previously completed work.",
        ],
    )
    if validated_report is None:
        return

    recurring = detect_recurring_patterns(si.open_issues, si.resolved_issues)
    recurring_dims = sorted(recurring.keys())

    if recurring_dims:
        mentioned = [
            dim
            for dim in recurring_dims
            if _report_mentions_dimension(validated_report, dim)
        ]
        if not mentioned:
            print(colorize("  Recurring patterns detected but not addressed in report:", "red"))
            for dim in recurring_dims:
                info = recurring[dim]
                display = DISPLAY_NAMES.get(dim, dim.replace("_", " "))
                print(
                    colorize(
                        f"    {display} ({dim}): {len(info['resolved'])} resolved, "
                        f"{len(info['open'])} still open \u2014 potential loop",
                        "yellow",
                    )
                )
            print(
                colorize(
                    "  Your report must mention at least one recurring dimension name.",
                    "dim",
                )
            )
            return

    record_triage_stage(
        plan,
        state,
        stage="reflect",
        report=validated_report,
        cited_ids=[],
        issue_count=issue_count,
        extra={"recurring_dims": recurring_dims},
        plan_path=plan_file,
    )

    print(
        colorize(
            f"  Reflect stage recorded: {issue_count} issues, "
            f"{len(recurring_dims)} recurring dimension(s).",
            "green",
        )
    )
    if recurring_dims:
        for dim in recurring_dims:
            info = recurring[dim]
            print(
                colorize(
                    f"    {dim}: {len(info['resolved'])} resolved, {len(info['open'])} still open",
                    "dim",
                )
            )

    print()
    print(colorize("  \u250c\u2500 Strategic briefing (share with user before organizing) \u2500\u2510", "cyan"))
    for line in validated_report.strip().splitlines():
        print(colorize(f"  \u2502 {line}", "cyan"))
    print(colorize("  \u2514" + "\u2500" * 57 + "\u2518", "cyan"))
    print()
    print(
        colorize(
            "  IMPORTANT: Present your holistic strategy to the user. Explain:",
            "yellow",
        )
    )
    print(colorize("  - What themes and root causes you see", "yellow"))
    print(
        colorize(
            "  - What contradictions you found and which direction you'll take",
            "yellow",
        )
    )
    print(
        colorize(
            "  - What you'll prioritize, what you'll defer, the overall arc of work",
            "yellow",
        )
    )
    print(colorize("  Wait for their input before creating clusters.", "yellow"))
    print()
    print(colorize("  Then create clusters and enrich each with action steps:", "dim"))
    print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
    print(colorize("    desloppify plan cluster add <name> <issue-patterns>", "dim"))
    print(
        colorize(
            '    desloppify plan cluster update <name> --steps "step 1" "step 2" ...',
            "dim",
        )
    )
    print(
        colorize(
            "    desloppify plan triage --stage organize --report \"summary of what was organized...\"",
            "dim",
        )
    )
