"""Scan preflight guard: warn and gate scan when queue has unfinished items."""

from __future__ import annotations

import logging

from desloppify import state as state_mod
from desloppify.app.commands.helpers.queue_progress import (
    ScoreDisplayMode,
    get_plan_start_strict,
    plan_aware_queue_breakdown,
    score_display_mode,
)
from desloppify.app.commands.helpers.state import state_path
from desloppify.app.commands.resolve.plan_load import warn_plan_load_degraded_once
from desloppify.base.exception_sets import CommandError, ScanQueueBlockedError
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.constants import WORKFLOW_RUN_SCAN_ID
from desloppify.engine._plan.refresh_lifecycle import current_lifecycle_phase
from desloppify.engine._plan.sync.pipeline import live_planned_queue_empty
from desloppify.engine._state.progression import (
    append_progression_event,
    build_scan_preflight_event,
)
from desloppify.engine._work_queue.context import resolve_plan_load_status
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine.planning.queue_policy import build_execution_queue

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


def _log_preflight(plan: dict | None, result: str, reason: str, queue_count: int) -> None:
    """Best-effort append of scan_preflight progression event."""
    try:
        phase = current_lifecycle_phase(plan) if isinstance(plan, dict) else None
        append_progression_event(
            build_scan_preflight_event(
                plan, result=result, reason=reason,
                queue_count=queue_count, phase_before=phase,
            )
        )
    except Exception:
        _logger.warning("Failed to append scan_preflight progression event", exc_info=True)


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
        _log_preflight(None, "bypassed", "force-rescan with attestation", 0)
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
        _log_preflight(plan, "allowed", "queue clear", 0)
        return  # Queue fully clear or no active cycle — scan allowed
    if (
        mode is ScoreDisplayMode.PHASE_TRANSITION
        and breakdown.queue_total == 1
        and breakdown.workflow == 1
        and _only_run_scan_workflow_remaining(state, plan)
    ):
        _log_preflight(plan, "allowed", "only workflow::run-scan remaining", 1)
        return
    # The breakdown may count items from queue_order that the snapshot
    # correctly filters out (stale items, subjective items from before
    # boundary-only sync).  If the snapshot shows no execution items,
    # the user has nothing actionable — allow the scan.
    if live_planned_queue_empty(plan):
        _log_preflight(plan, "allowed", "live planned queue empty", 0)
        return
    # Even if live_planned_queue_empty is False (non-synthetic items in
    # queue_order), those items may be stale (not in current state).
    # If the snapshot agrees the queue is empty, allow the scan.
    from desloppify.engine._work_queue.context import queue_context
    try:
        ctx = queue_context(state, plan=plan)
        if len(ctx.snapshot.execution_items) == 0:
            _log_preflight(plan, "allowed", "snapshot execution queue empty", 0)
            return
    except Exception:
        pass  # Fall through to the normal gate

    remaining = breakdown.queue_total
    _log_preflight(plan, "blocked", f"{remaining} item(s) remaining", remaining)
    # GATE — block both FROZEN (objective work) and PHASE_TRANSITION
    # (subjective/workflow items remain)
    raise ScanQueueBlockedError(
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
