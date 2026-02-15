"""plan command: generate prioritized markdown plan from state."""

from ..utils import colorize
from ._helpers import state_path


def cmd_plan_output(args):
    """Generate a prioritized markdown plan from state."""
    from ..state import load_state
    from ..plan import generate_plan_md

    sp = state_path(args)
    state = load_state(sp)

    if not state.get("last_scan"):
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
        return

    plan_md = generate_plan_md(state)

    output = getattr(args, "output", None)
    if output:
        try:
            from ..utils import safe_write_text
            safe_write_text(output, plan_md)
            print(colorize(f"Plan written to {output}", "green"))
        except OSError as e:
            print(colorize(f"Could not write plan to {output}: {e}", "red"))
    else:
        print(plan_md)
