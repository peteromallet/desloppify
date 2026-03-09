"""User-facing message helpers for resolve command."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message

from .living_plan import ClusterContext


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


__all__ = ["print_fixed_next_user_message", "print_no_match_warning"]
