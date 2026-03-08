"""plan command: dispatcher for plan subcommands."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.rendering import print_agent_plan
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan.cluster_handlers import cmd_cluster_dispatch
from desloppify.app.commands.plan.commit_log_handlers import cmd_commit_log_dispatch
from desloppify.app.commands.plan.override_handlers import (
    cmd_plan_describe,
    cmd_plan_focus,
    cmd_plan_note,
    cmd_plan_reopen,
    cmd_plan_resolve,
    cmd_plan_scan_gate,
    cmd_plan_skip,
    cmd_plan_unskip,
)
from desloppify.app.commands.plan.queue_render import cmd_plan_queue
from desloppify.app.commands.plan.reorder_handlers import cmd_plan_reorder
from desloppify.app.commands.plan.triage_handlers import cmd_plan_triage
from desloppify.base.config import load_config
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.fallbacks import warn_best_effort
from desloppify.base.output.terminal import colorize
from desloppify.base.tooling import check_config_staleness
from desloppify.engine import planning as planning_mod
from desloppify.app.commands.helpers.queue_progress import (
    format_queue_headline,
    plan_aware_queue_breakdown,
)
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.engine.plan import (
    USER_SKIP_KINDS,
    annotation_counts,
    append_log_entry,
    commit_tracking_summary,
    load_plan,
    reset_plan,
    save_plan,
)


def cmd_plan_output(args: argparse.Namespace) -> None:
    """Generate a prioritized markdown plan from state."""
    runtime = command_runtime(args)
    state = runtime.state

    if not require_completed_scan(state):
        return

    config_warning = check_config_staleness(runtime.config)
    if config_warning:
        print(colorize(f"  {config_warning}", "yellow"))

    plan_md = planning_mod.generate_plan_md(state)
    next_command = "desloppify next --count 20"

    output = getattr(args, "output", None)
    if output:
        try:
            from pathlib import Path
            output_path = Path(output)
            if output_path.exists():
                print(colorize(
                    f"  {output} already exists — refusing to overwrite.",
                    "red",
                ))
                print(colorize(
                    f"  Delete it first (`desloppify plan reset` or `rm {output}`), "
                    f"or choose a different filename.",
                    "dim",
                ))
                return
            safe_write_text(output, plan_md)
            print(colorize(f"Plan written to {output}", "green"))
            print_agent_plan(
                ["Inspect and execute the generated plan."],
                next_command=next_command,
            )
        except OSError as e:
            warn_best_effort(f"Could not write plan to {output}: {e}")
    else:
        print(plan_md)
        print()
        print_agent_plan(
            ["Start from the top-ranked action in this plan."],
            next_command=next_command,
        )


def _cmd_plan_generate(args: argparse.Namespace) -> None:
    """Generate the prioritized markdown plan (existing behavior)."""
    cmd_plan_output(args)


def _cmd_plan_show(args: argparse.Namespace) -> None:
    """Show plan metadata summary."""
    plan = load_plan()
    runtime = command_runtime(args)

    # Dynamic queue count — matches what `next` and `plan queue` show.
    try:
        breakdown = plan_aware_queue_breakdown(runtime.state, plan)
        queue_line = format_queue_headline(breakdown)
    except PLAN_LOAD_EXCEPTIONS:
        # Fallback to raw plan data if queue build fails
        ordered = len(plan.get("queue_order", []))
        queue_line = f"Queue: {ordered} items prioritized"

    skipped = plan.get("skipped", {})
    total_skipped = len(skipped)
    kind_counts = {
        kind: sum(1 for entry in skipped.values() if entry.get("kind") == kind)
        for kind in USER_SKIP_KINDS
    }
    temp_count = kind_counts["temporary"]
    perm_count = kind_counts["permanent"]
    fp_count = kind_counts["false_positive"]
    clusters = plan.get("clusters", {})
    active = plan.get("active_cluster")
    superseded = len(plan.get("superseded", {}))

    described, noted = annotation_counts(plan)

    print(colorize("  Living Plan Status", "bold"))
    print(colorize("  " + "─" * 40, "dim"))
    print(f"  {queue_line}")
    if total_skipped:
        print(f"  Skipped:          {total_skipped} (temp: {temp_count}, wontfix: {perm_count}, fp: {fp_count})")
    else:
        print("  Skipped:          0")
    print(f"  Clusters:         {len(clusters)}")
    if clusters:
        for name, cluster in clusters.items():
            desc = cluster.get("description") or ""
            member_count = len(cluster.get("issue_ids", []))
            marker = " (focused)" if name == active else ""
            desc_str = f" — {desc}" if desc else ""
            print(f"    {name}: {member_count} items{desc_str}{marker}")
    if described or noted:
        print(f"  Annotations:      {described} described, {noted} noted")
    if active:
        print(f"  Focus:            {active}")
    if superseded:
        print(f"  Disappeared:      {superseded} (resolved or removed since last scan)")

    # Commit tracking summary
    _cfg = load_config()
    if _cfg.get("commit_tracking_enabled", True):
        ct = commit_tracking_summary(plan)
        if ct["total"] > 0:
            pr_num = _cfg.get("commit_pr", 0)
            pr_str = f"  PR: #{pr_num}" if pr_num else ""
            print(
                f"  Commit tracking:  {ct['uncommitted']} uncommitted, "
                f"{ct['committed']} committed ({ct['total']} issues){pr_str}"
            )


def _cmd_plan_reset(args: argparse.Namespace) -> None:
    """Reset the plan to empty."""
    plan = load_plan()
    queue_len = len(plan.get("queue_order", []))
    cluster_count = len(plan.get("clusters", {}))
    reset_plan(plan)
    append_log_entry(
        plan, "reset", actor="user",
        detail={"previous_queue_size": queue_len, "previous_cluster_count": cluster_count},
    )
    save_plan(plan)
    print(colorize("  Plan reset to empty.", "green"))


_PLAN_ACTION_HANDLERS = {
    "show": _cmd_plan_show,
    "queue": cmd_plan_queue,
    "reset": _cmd_plan_reset,
    "reorder": cmd_plan_reorder,
    "describe": cmd_plan_describe,
    "resolve": cmd_plan_resolve,
    "note": cmd_plan_note,
    "focus": cmd_plan_focus,
    "skip": cmd_plan_skip,
    "unskip": cmd_plan_unskip,
    "reopen": cmd_plan_reopen,
    "cluster": cmd_cluster_dispatch,
    "triage": cmd_plan_triage,
    "scan-gate": cmd_plan_scan_gate,
    "commit-log": cmd_commit_log_dispatch,
}


def cmd_plan(args: argparse.Namespace) -> None:
    """Dispatch plan subcommand or generate markdown output."""
    plan_action = getattr(args, "plan_action", None)
    if plan_action is None:
        _cmd_plan_generate(args)
        return

    handler = _PLAN_ACTION_HANDLERS.get(plan_action)
    if handler is None:
        print(f"Unknown plan action: {plan_action}")
        return
    handler(args)

__all__ = ["cmd_plan", "cmd_plan_output"]
