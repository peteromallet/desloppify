"""Post-scan plan workflow nudge.

Dependency-light module that only imports plan/queue helpers — avoids
the import cycle that previously forced function-level imports in scan.py.
"""

from __future__ import annotations

from desloppify.app.commands.helpers.queue_progress import plan_aware_queue_count
from desloppify.core.output_api import colorize
from desloppify.engine.plan import load_plan


def print_plan_workflow_nudge(state: dict) -> None:
    """Print a queue-count reminder when plan-start scores exist."""
    try:
        plan = load_plan()
        if not plan.get("plan_start_scores"):
            return
        queue_total = plan_aware_queue_count(state, plan)
    except (OSError, ValueError, KeyError, TypeError):
        return

    if queue_total <= 0:
        return
    print(
        colorize(
            f"  Workflow: {queue_total} queue item{'s' if queue_total != 1 else ''}."
            " Score is frozen until the queue is clear — use `desloppify next` to begin.",
            "dim",
        )
    )
