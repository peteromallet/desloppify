"""plan command: generate prioritized markdown plan from state.

This module preserves the original import path. The full plan command
(with subcommands) lives in ``desloppify.app.commands.plan.cmd``.
"""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.rendering import print_agent_plan
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.core.fallbacks import warn_best_effort
from desloppify.engine import planning as planning_mod
from desloppify.core.discovery_api import safe_write_text
from desloppify.core.output_api import colorize
from desloppify.core.tooling import check_config_staleness


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


__all__ = ["cmd_plan_output"]
