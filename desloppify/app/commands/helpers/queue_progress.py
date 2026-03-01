"""Plan-aware queue progress and frozen score display helpers."""

from __future__ import annotations

from desloppify.core.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.core.output_api import colorize


def plan_aware_queue_count(state: dict, plan: dict | None = None) -> int:
    """Count remaining plan-aware queue items (skips excluded, clusters collapsed)."""
    from desloppify.engine.work_queue import QueueBuildOptions, build_work_queue

    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            status="open",
            count=None,
            plan=plan,
            collapse_clusters=True,
            include_skipped=False,
        ),
    )
    return result["total"]


def get_plan_start_strict(plan: dict | None) -> float | None:
    """Extract the frozen plan-start strict score, or None if unset."""
    if not plan:
        return None
    return plan.get("plan_start_scores", {}).get("strict")


def print_frozen_score_with_queue_context(
    plan: dict,
    queue_remaining: int,
) -> None:
    """Show frozen plan-start score + queue progress."""
    scores = plan.get("plan_start_scores", {})
    strict = scores.get("strict")
    if strict is None:
        return
    print(
        colorize(
            f"\n  Score (frozen at plan start): strict {strict:.1f}/100",
            "cyan",
        )
    )
    print(
        colorize(
            f"  Queue: {queue_remaining} item{'s' if queue_remaining != 1 else ''}"
            " remaining. Score will not update until the queue is clear and you run `desloppify scan`.",
            "dim",
        )
    )


def print_execution_or_reveal(
    state: dict,
    prev,
    plan: dict | None,
) -> None:
    """Context-aware score display: frozen plan-start score or live scores.

    If a plan has ``plan_start_scores`` and there are queue items remaining,
    show the frozen score + queue progress.  Otherwise delegate to the
    existing live ``print_score_update``.
    """
    if plan and plan.get("plan_start_scores", {}).get("strict") is not None:
        try:
            remaining = plan_aware_queue_count(state, plan)
        except PLAN_LOAD_EXCEPTIONS:
            remaining = 0
        if remaining > 0:
            print_frozen_score_with_queue_context(plan, remaining)
            return

    # No active plan cycle or queue is clear — live scores
    from desloppify.app.commands.helpers.score_update import print_score_update

    print_score_update(state, prev)


__all__ = [
    "get_plan_start_strict",
    "plan_aware_queue_count",
    "print_execution_or_reveal",
    "print_frozen_score_with_queue_context",
]
