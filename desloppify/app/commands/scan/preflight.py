"""Scan preflight guard: warn and gate scan when queue has unfinished items."""

from __future__ import annotations

import logging

from desloppify import state as state_mod
from desloppify.app.commands.helpers.queue_progress import (
    ScoreDisplayMode,
    plan_aware_queue_breakdown,
    score_display_mode,
)
from desloppify.app.commands.helpers.queue_progress import get_plan_start_strict
from desloppify.app.commands.helpers.state import state_path
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.app.commands.resolve.plan_load import warn_plan_load_degraded_once
from desloppify.engine._work_queue.context import resolve_plan_load_status
from desloppify.engine._plan.constants import WORKFLOW_RUN_SCAN_ID
from desloppify.engine.planning.queue_policy import build_execution_queue
from desloppify.engine._work_queue.core import QueueBuildOptions

_logger = logging.getLogger(__name__)


def _only_run_scan_workflow_remaining(state: dict, plan: dict) -> bool:
    result = build_execution_queue(
        state,
        options=QueueBuildOptions(
            status="open",
            count=None,
            plan=plan,
            include_skipped=False,
        ),
    )
    items = result.get("items", [])
    return len(items) == 1 and items[0].get("id") == WORKFLOW_RUN_SCAN_ID


def scan_queue_preflight(args: object) -> None:
    """Warn and gate scan when queue has unfinished items."""
    # CI profile always passes
    if getattr(args, "profile", None) == "ci":
        return

    # --force-rescan with valid attestation bypasses
    if getattr(args, "force_rescan", False):
        attest = getattr(args, "attest", None) or ""
        if "i understand" not in attest.lower():
            raise CommandError(
                '--force-rescan requires --attest "I understand this is not '
                "the intended workflow and I am intentionally skipping queue "
                'completion"'
            )
        print(
            colorize(
                "  --force-rescan: bypassing queue completion check. "
                "Queue-destructive reconciliation steps will be skipped.",
                "yellow",
            )
        )
        return

    # No plan = no gate (first scan, or user never uses plan). Use the same
    # plan-load contract as the work queue so degraded-plan handling stays
    # consistent across queue rendering and scan preflight.
    plan_status = resolve_plan_load_status()
    if plan_status.degraded:
        _logger.debug(
            "scan preflight plan load degraded: %s",
            plan_status.error_kind,
        )
        warn_plan_load_degraded_once(
            command_label="scan preflight",
            error_kind=plan_status.error_kind,
            behavior="Queue gating is disabled until the living plan can be loaded again.",
        )
        return
    plan = plan_status.plan
    if not isinstance(plan, dict):
        return
    if not plan.get("plan_start_scores"):
        return  # No active cycle

    # Count plan-aware remaining items.  Block scan when ANY queue items
    # remain (objective OR subjective).  Mid-cycle scans regenerate issue
    # IDs which wipes triage state and re-clusters the queue, undoing
    # prioritisation work.
    try:
        state = state_mod.load_state(state_path(args))
        breakdown = plan_aware_queue_breakdown(state, plan)
        plan_start_strict = get_plan_start_strict(plan)
        mode = score_display_mode(breakdown, plan_start_strict)
    except OSError:
        _logger.debug("scan preflight queue breakdown skipped", exc_info=True)
        return
    if mode is ScoreDisplayMode.LIVE:
        return  # Queue fully clear or no active cycle — scan allowed
    if (
        mode is ScoreDisplayMode.PHASE_TRANSITION
        and breakdown.queue_total == 1
        and breakdown.workflow == 1
        and _only_run_scan_workflow_remaining(state, plan)
    ):
        return

    remaining = breakdown.queue_total
    # GATE — block both FROZEN (objective work) and PHASE_TRANSITION
    # (subjective/workflow items remain)
    raise CommandError(
        f"{remaining} item{'s' if remaining != 1 else ''}"
        " remaining in your queue.\n"
        "  Scanning mid-cycle regenerates issue IDs and breaks triage state.\n"
        "  Work through items with `desloppify next`, then scan when clear.\n\n"
        "  To force a rescan (resets your plan-start score):\n"
        '    desloppify scan --force-rescan --attest "I understand this is not '
        "the intended workflow and I am intentionally skipping queue "
        'completion"'
    )


__all__ = ["scan_queue_preflight"]
