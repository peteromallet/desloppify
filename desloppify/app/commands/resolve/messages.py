"""User-facing message helpers for resolve command."""

from __future__ import annotations

import argparse
import logging

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message

from .living_plan import ClusterContext

logger = logging.getLogger(__name__)

_NEXT_TASK_INSTRUCTIONS = (
    "A desloppify task was just marked complete. Here's what to do next:\n"
    "\n"
    "1. Run `desloppify next` to see the next task in the queue\n"
    "2. Read and understand the issue — explore the relevant files and scope\n"
    "3. Execute the fix thoroughly and verify it works\n"
    "4. Once you're happy with it, commit and push:\n"
    "   `git add -A && git commit -m '<describe the fix>' && git push`\n"
    "5. Record the commit: `desloppify plan commit-log record`\n"
    "6. Mark it resolved: `desloppify resolve <pattern> --fixed --attest '<what you did>'`"
)


def _hermes_reset_and_instruct(
    *,
    cluster_name: str | None = None,
    cluster_remaining: int = 0,
) -> None:
    """Reset Hermes context and inject next-task instructions via control API."""
    from desloppify.app.commands.helpers.transition_messages import (
        _hermes_available,
        _hermes_send_message,
    )

    if not _hermes_available():
        return
    try:
        # Reset conversation to clear stale context from the previous task
        result = _hermes_send_message("/reset", mode="interrupt")
        if not result.get("success"):
            return

        # Build context-aware instructions
        if cluster_name and cluster_remaining > 0:
            instructions = (
                f"A desloppify task was just marked complete. You're working through "
                f"cluster '{cluster_name}' — {cluster_remaining} item(s) remaining.\n"
                f"\n"
                f"1. Run `desloppify next` to see the next task (focus is on '{cluster_name}')\n"
                f"2. Read the step detail shown under 'Your step(s):' — it has exact file paths and line numbers\n"
                f"3. Execute the fix and verify it works\n"
                f"4. Commit: `git add -A && git commit -m '<describe the fix>' && git push`\n"
                f"5. Record: `desloppify plan commit-log record`\n"
                f"6. Resolve: `desloppify resolve <pattern> --fixed --attest '<what you did>'`\n"
                f"\nKeep going until the cluster is finished."
            )
        else:
            instructions = _NEXT_TASK_INSTRUCTIONS

        _hermes_send_message(instructions, mode="queue")
    except Exception as exc:
        logger.debug("Hermes next-task injection skipped: %s", exc)


def print_no_match_warning(args: argparse.Namespace) -> None:
    status_label = "resolved" if args.status == "open" else "open"
    print(colorize(f"No {status_label} issues matching: {' '.join(args.patterns)}", "yellow"))


def print_fixed_next_user_message(
    *,
    args: argparse.Namespace,
    plan: dict | None,
    next_command: str,
    mid_cluster: bool,
    cluster_ctx: ClusterContext,
) -> None:
    if args.status != "fixed" or plan is None or next_command != "desloppify next":
        return

    if mid_cluster:
        print_user_message(
            f"Hey — task done, {cluster_ctx.cluster_remaining} left in"
            f" cluster '{cluster_ctx.cluster_name}'. Run `desloppify next`"
            " to pick up the next one. Keep going — don't stop until the"
            " cluster is finished."
        )
    elif cluster_ctx.cluster_completed and cluster_ctx.cluster_name:
        print_user_message(
            f"Hey — nice, you just finished cluster '{cluster_ctx.cluster_name}'."
            " Check the commit tracking above — this is a good time to"
            " commit and push your work. Then run `desloppify next` to"
            " pick up your next task."
        )
    else:
        print_user_message(
            "Hey — nice, on to the next one. Run `desloppify next`"
            " to pick up your next task. Before moving on, glance at the"
            " commit tracking above — if there's a decent chunk of"
            " uncommitted work, consider whether now's a good time"
            " to commit and push. Otherwise just keep going."
        )

    # Also inject via Hermes control API for a clean context switch
    _hermes_reset_and_instruct(
        cluster_name=cluster_ctx.cluster_name if mid_cluster else None,
        cluster_remaining=cluster_ctx.cluster_remaining if mid_cluster else 0,
    )


__all__ = ["print_fixed_next_user_message", "print_no_match_warning"]
