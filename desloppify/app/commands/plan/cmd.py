"""plan command: dispatcher for plan subcommands."""

from __future__ import annotations

import argparse

from desloppify.app.commands.plan.cluster_handlers import cmd_cluster_dispatch
from desloppify.app.commands.plan.move_handlers import cmd_plan_move
from desloppify.app.commands.plan.override_handlers import (
    cmd_plan_describe,
    cmd_plan_done,
    cmd_plan_focus,
    cmd_plan_note,
    cmd_plan_reopen,
    cmd_plan_skip,
    cmd_plan_unskip,
)
from desloppify.app.commands.plan.queue_render import cmd_plan_queue
from desloppify.app.commands.plan_cmd import cmd_plan_output as _plan_output_impl
from desloppify.core.output_api import colorize
from desloppify.engine.plan import load_plan, reset_plan, save_plan


def _cmd_plan_generate(args: argparse.Namespace) -> None:
    """Generate the prioritized markdown plan (existing behavior)."""
    _plan_output_impl(args)


def _cmd_plan_show(args: argparse.Namespace) -> None:
    """Show plan metadata summary."""
    plan = load_plan()
    ordered = len(plan.get("queue_order", []))
    skipped = plan.get("skipped", {})
    total_skipped = len(skipped)
    temp_count = sum(1 for e in skipped.values() if e.get("kind") == "temporary")
    perm_count = sum(1 for e in skipped.values() if e.get("kind") == "permanent")
    fp_count = sum(1 for e in skipped.values() if e.get("kind") == "false_positive")
    clusters = plan.get("clusters", {})
    overrides = plan.get("overrides", {})
    active = plan.get("active_cluster")
    superseded = len(plan.get("superseded", {}))

    # Count meaningful annotations (descriptions and notes)
    described = sum(1 for o in overrides.values() if o.get("description"))
    noted = sum(1 for o in overrides.values() if o.get("note"))

    print(colorize("  Living Plan Status", "bold"))
    print(colorize("  " + "─" * 40, "dim"))
    print(f"  Queue:            {ordered} items prioritized")
    if total_skipped:
        print(f"  Skipped:          {total_skipped} (temp: {temp_count}, wontfix: {perm_count}, fp: {fp_count})")
    else:
        print(f"  Skipped:          0")
    print(f"  Clusters:         {len(clusters)}")
    if clusters:
        for name, cluster in clusters.items():
            desc = cluster.get("description") or ""
            member_count = len(cluster.get("finding_ids", []))
            marker = " (focused)" if name == active else ""
            desc_str = f" — {desc}" if desc else ""
            print(f"    {name}: {member_count} items{desc_str}{marker}")
    if described or noted:
        print(f"  Annotations:      {described} described, {noted} noted")
    if active:
        print(f"  Focus:            {active}")
    if superseded:
        print(f"  Disappeared:      {superseded} (resolved or removed since last scan)")


def _cmd_plan_reset(args: argparse.Namespace) -> None:
    """Reset the plan to empty."""
    plan = load_plan()
    reset_plan(plan)
    save_plan(plan)
    print(colorize("  Plan reset to empty.", "green"))


def cmd_plan(args: argparse.Namespace) -> None:
    """Dispatch plan subcommand or generate markdown output."""
    plan_action = getattr(args, "plan_action", None)

    if plan_action is None:
        _cmd_plan_generate(args)
        return

    if plan_action == "show":
        _cmd_plan_show(args)
        return

    if plan_action == "queue":
        cmd_plan_queue(args)
        return

    if plan_action == "reset":
        _cmd_plan_reset(args)
        return

    if plan_action == "move":
        cmd_plan_move(args)
        return

    if plan_action in (
        "describe", "note", "focus",
        "skip", "unskip", "reopen", "done",
    ):
        dispatch = {
            "describe": cmd_plan_describe,
            "done": cmd_plan_done,
            "note": cmd_plan_note,
            "focus": cmd_plan_focus,
            "skip": cmd_plan_skip,
            "unskip": cmd_plan_unskip,
            "reopen": cmd_plan_reopen,
        }
        dispatch[plan_action](args)
        return

    if plan_action == "cluster":
        cmd_cluster_dispatch(args)
        return

    if plan_action == "synthesize":
        from desloppify.app.commands.plan.synthesize_handlers import cmd_plan_synthesize

        cmd_plan_synthesize(args)
        return

    print(f"Unknown plan action: {plan_action}")


# Backwards-compatible alias
cmd_plan_output = cmd_plan

__all__ = ["cmd_plan", "cmd_plan_output"]
