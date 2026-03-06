"""Plan reorder subcommand handlers."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import append_log_entry, load_plan, move_items, plan_path_for_state, save_plan


def resolve_target(plan: dict, target: str | None, position: str) -> str | None:
    """Resolve a cluster name used as a before/after target to a member ID."""
    if target is None:
        return None
    clusters = plan.get("clusters", {})
    if target not in clusters:
        return target
    member_ids = clusters[target].get("issue_ids", [])
    if not member_ids:
        return target
    order = plan.get("queue_order", [])
    member_set = set(member_ids)
    ordered = [fid for fid in order if fid in member_set]
    if not ordered:
        return member_ids[0]
    return ordered[0] if position == "before" else ordered[-1]


def cmd_plan_reorder(args: argparse.Namespace) -> None:
    """Reorder issues in the queue."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    position: str = getattr(args, "position", "top")
    target: str | None = getattr(args, "target", None)

    if position in ("before", "after") and target is None:
        print(colorize(f"  '{position}' requires --target (-t). Example: plan reorder <pat> {position} -t <id>", "red"))
        return
    if position in ("up", "down") and target is None:
        print(colorize(f"  '{position}' requires --target (-t) with an integer offset. Example: plan reorder <pat> {position} -t 3", "red"))
        return

    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)

    target = resolve_target(plan, target, position)

    issue_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not issue_ids:
        print(colorize("  No matching issues found.", "yellow"))
        return

    offset: int | None = None
    if position in ("up", "down") and target is not None:
        try:
            offset = int(target)
        except (ValueError, TypeError):
            print(colorize(f"  Invalid offset: {target}", "red"))
            return
        target = None

    count = move_items(plan, issue_ids, position, target=target, offset=offset)
    append_log_entry(
        plan, "reorder", issue_ids=issue_ids, actor="user",
        detail={"position": position, "target": target, "offset": offset},
    )
    save_plan(plan, plan_file)
    print(colorize(f"  Moved {count} item(s) to {position}.", "green"))


__all__ = ["cmd_plan_reorder", "resolve_target"]
