"""plan command: generate prioritized markdown plan from state."""

from desloppify.app.commands.helpers.rendering import print_agent_plan
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.core.fallbacks import warn_best_effort
from desloppify.engine.planning import core as plan_mod
from desloppify.utils import colorize, safe_write_text

command_context = command_runtime


def cmd_plan_output(args) -> None:
    """Generate a prioritized markdown plan from state."""
    state = command_context(args).state

    if not require_completed_scan(state):
        return

    plan_md = plan_mod.generate_plan_md(state)
    next_command = "desloppify next --count 20"

    output = getattr(args, "output", None)
    if output:
        try:
            safe_write_text(output, plan_md)
            print(colorize(f"Plan written to {output}", "green"))
            print_agent_plan(["Inspect and execute the generated plan."], next_command=next_command)
        except OSError as e:
            warn_best_effort(f"Could not write plan to {output}: {e}")
    else:
        print(plan_md)
        print()
        print_agent_plan(["Start from the top-ranked action in this plan."], next_command=next_command)
