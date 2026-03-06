"""Plan move subcommand handlers."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan._resolve import resolve_ids_from_patterns
from desloppify.core.output_api import colorize
from desloppify.engine.plan import load_plan, move_items, plan_path_for_state, save_plan


def cmd_plan_move(args: argparse.Namespace) -> None:
    """Move findings to a position in the queue."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    patterns: list[str] = getattr(args, "patterns", [])
    position: str = getattr(args, "position", "top")
    target: str | None = getattr(args, "target", None)

    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)
    finding_ids = resolve_ids_from_patterns(state, patterns, plan=plan)
    if not finding_ids:
        print(colorize("  No matching findings found.", "yellow"))
        return

    offset: int | None = None
    if position in ("up", "down") and target is not None:
        try:
            offset = int(target)
        except (ValueError, TypeError):
            print(colorize(f"  Invalid offset: {target}", "red"))
            return
        target = None

    count = move_items(plan, finding_ids, position, target=target, offset=offset)
    save_plan(plan, plan_file)
    print(colorize(f"  Moved {count} item(s) to {position}.", "green"))


__all__ = ["cmd_plan_move"]
