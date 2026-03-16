"""Plan-aware queue progress and frozen score display helpers."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.app.commands.helpers.dynamic_loaders import load_score_update_module
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.refresh_lifecycle import (
    COARSE_PHASE_MAP,
    coarse_lifecycle_phase,
    LIFECYCLE_PHASE_EXECUTE,
    LIFECYCLE_PHASE_REVIEW,
    LIFECYCLE_PHASE_SCAN,
    LIFECYCLE_PHASE_TRIAGE,
    LIFECYCLE_PHASE_WORKFLOW,
)
from desloppify.engine.plan_state import load_plan
from desloppify.state_scoring import score_snapshot
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.helpers import is_subjective_queue_item
from desloppify.engine._work_queue.plan_order import collapse_clusters
from desloppify.engine.planning.queue_policy import build_execution_queue
from desloppify.app.commands.helpers.queue_progress_render import (
    format_plan_delta,
    format_queue_block,
    format_queue_headline,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from desloppify.engine._work_queue.context import QueueContext


# ---------------------------------------------------------------------------
# QueueBreakdown — single source of truth for queue numbers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QueueBreakdown:
    """All numbers needed to render the standardized queue display."""

    queue_total: int = 0
    plan_ordered: int = 0
    stale_plan_ordered: int = 0
    skipped: int = 0
    subjective: int = 0
    workflow: int = 0
    lifecycle_phase: str | None = None
    focus_cluster: str | None = None
    focus_cluster_count: int = 0
    focus_cluster_total: int = 0

    @property
    def objective_actionable(self) -> int:
        """Objective items only — excludes subjective and workflow.

        This is the count used by :func:`score_display_mode` to decide
        frozen vs live display.  Do not use it directly for gating —
        use ``score_display_mode()`` instead.
        """
        if self.lifecycle_phase in {
            LIFECYCLE_PHASE_SCAN,
            LIFECYCLE_PHASE_REVIEW,
            LIFECYCLE_PHASE_WORKFLOW,
            LIFECYCLE_PHASE_TRIAGE,
        }:
            return 0
        return max(0, self.queue_total - self.subjective - self.workflow)


# ---------------------------------------------------------------------------
# ScoreDisplayMode — single decision point for frozen vs live score display
# ---------------------------------------------------------------------------

class ScoreDisplayMode(enum.Enum):
    """How to display the score given the current plan cycle and queue state.

    - ``FROZEN``: objective work remains → show frozen plan-start score.
    - ``PHASE_TRANSITION``: objective drained, subjective/workflow remain
      → show live scores + transition banner.
    - ``LIVE``: no active plan cycle or queue fully clear → show live scores.
    """
    FROZEN = "frozen"
    PHASE_TRANSITION = "phase_transition"
    LIVE = "live"


def score_display_mode(
    breakdown: QueueBreakdown | None,
    plan_start_strict: float | None,
) -> ScoreDisplayMode:
    """Determine the score display mode from breakdown + plan-start score.

    This is the **single source of truth** for the frozen-vs-live decision.
    Every call site (status, scan reveal, next nudges, plan reconcile, plan
    nudge) must use this instead of ad-hoc count checks.
    """
    if plan_start_strict is None:
        return ScoreDisplayMode.LIVE
    if breakdown is None:
        return ScoreDisplayMode.LIVE
    if breakdown.queue_total == 0:
        return ScoreDisplayMode.LIVE  # Queue fully drained — always live (#441)
    if breakdown.lifecycle_phase == LIFECYCLE_PHASE_SCAN:
        return ScoreDisplayMode.LIVE
    if breakdown.lifecycle_phase == LIFECYCLE_PHASE_EXECUTE:
        return ScoreDisplayMode.FROZEN
    if breakdown.lifecycle_phase in {
        LIFECYCLE_PHASE_REVIEW,
        LIFECYCLE_PHASE_WORKFLOW,
        LIFECYCLE_PHASE_TRIAGE,
    }:
        return ScoreDisplayMode.PHASE_TRANSITION
    if breakdown.objective_actionable > 0:
        return ScoreDisplayMode.FROZEN
    if breakdown.queue_total > 0:
        return ScoreDisplayMode.PHASE_TRANSITION
    return ScoreDisplayMode.LIVE


def plan_aware_queue_breakdown(
    state: dict,
    plan: dict | None = None,
    *,
    context: QueueContext | None = None,
) -> QueueBreakdown:
    """Build a full :class:`QueueBreakdown` from a single ``build_work_queue`` call.

    When *context* is provided, its ``plan`` and ``policy`` are forwarded to
    ``build_work_queue`` so the counts agree with the caller's resolution.
    """
    effective_plan = context.plan if context is not None else plan

    result = build_execution_queue(
        state,
        options=QueueBuildOptions(
            status="open",
            count=None,
            plan=effective_plan if context is None else None,
            include_skipped=False,
            context=context,
        ),
    )

    # Collapse clusters for display-level counting
    items = result.get("items", [])
    snapshot = (
        context.snapshot
        if context is not None
        else queue_context(state, plan=effective_plan).snapshot
    )
    refresh_state = effective_plan.get("refresh_state") if isinstance(effective_plan, dict) else None
    persisted_phase = (
        coarse_lifecycle_phase(effective_plan)
        if isinstance(refresh_state, dict) and isinstance(refresh_state.get("lifecycle_phase"), str)
        else None
    )
    lifecycle_phase = persisted_phase or COARSE_PHASE_MAP.get(snapshot.phase, snapshot.phase)
    if effective_plan and not effective_plan.get("active_cluster"):
        items = collapse_clusters(items, effective_plan)

    queue_total = len(items)

    # Count subjective and workflow items in the queue.
    # Collapsed clusters whose members are all subjective count as subjective.
    subjective = sum(
        1 for item in items
        if is_subjective_queue_item(item)
    )
    workflow = sum(
        1 for item in items
        if item.get("kind") in ("workflow_stage", "workflow_action")
    )

    # Plan-derived counts
    plan_ordered = 0
    stale_plan_ordered = 0
    skipped = 0
    if effective_plan:
        skipped = len(effective_plan.get("skipped", {}))
        # plan_ordered = live queue_order items that still exist in the current
        # snapshot; stale_plan_ordered captures dead queue_order entries so the
        # summary does not imply they are still blocking the live queue.
        queue_order = effective_plan.get("queue_order", [])
        skipped_ids = set(effective_plan.get("skipped", {}).keys())
        current_item_ids = _snapshot_item_ids(snapshot)
        if current_item_ids is None:
            plan_ordered = sum(1 for fid in queue_order if fid not in skipped_ids)
        else:
            plan_ordered = sum(
                1 for fid in queue_order
                if fid not in skipped_ids and fid in current_item_ids
            )
            stale_plan_ordered = sum(
                1 for fid in queue_order
                if fid not in skipped_ids and fid not in current_item_ids
            )

    # Focus cluster info
    focus_cluster = None
    focus_cluster_count = 0
    focus_cluster_total = 0
    if effective_plan:
        active = effective_plan.get("active_cluster")
        if active:
            focus_cluster = active
            cluster_data = effective_plan.get("clusters", {}).get(active, {})
            focus_cluster_total = len(cluster_data.get("issue_ids", []))
            # Count how many cluster members are still in the queue
            cluster_member_ids = set(cluster_data.get("issue_ids", []))
            open_issues = {
                fid
                for fid, f in (state.get("work_items") or state.get("issues", {})).items()
                if f.get("status") == "open"
            }
            focus_cluster_count = len(cluster_member_ids & open_issues)

    return QueueBreakdown(
        queue_total=queue_total,
        plan_ordered=plan_ordered,
        stale_plan_ordered=stale_plan_ordered,
        skipped=skipped,
        subjective=subjective,
        workflow=workflow,
        lifecycle_phase=lifecycle_phase,
        focus_cluster=focus_cluster,
        focus_cluster_count=focus_cluster_count,
        focus_cluster_total=focus_cluster_total,
    )


def _snapshot_item_ids(snapshot: object) -> set[str] | None:
    """Return all live queue item IDs represented by a snapshot.

    When tests stub ``snapshot`` with only a ``phase`` attribute, return
    ``None`` so callers can fall back to legacy plan_ordered counting.
    """
    partition_names = (
        "all_objective_items",
        "all_initial_review_items",
        "all_postflight_assessment_items",
        "all_postflight_review_items",
        "all_scan_items",
        "all_postflight_workflow_items",
        "all_postflight_triage_items",
    )
    item_ids: set[str] = set()
    saw_partition = False
    for name in partition_names:
        items = getattr(snapshot, name, None)
        if items is None:
            continue
        saw_partition = True
        for item in items:
            if isinstance(item, dict):
                item_id = item.get("id")
                if isinstance(item_id, str) and item_id:
                    item_ids.add(item_id)
    if not saw_partition:
        return None
    return item_ids


def get_plan_start_strict(plan: dict | None) -> float | None:
    """Extract the frozen plan-start strict score, or None if unset."""
    if not plan:
        return None
    return plan.get("plan_start_scores", {}).get("strict")


def print_frozen_score_with_queue_context(
    breakdown: QueueBreakdown,
    *,
    frozen_strict: float,
    live_score: float | None = None,
) -> None:
    """Show frozen plan-start score + queue progress.

    Only call from a ``ScoreDisplayMode.FROZEN`` path — assumes objective
    work remains in the queue.
    """
    block = format_queue_block(breakdown, frozen_score=frozen_strict, live_score=live_score)
    print()
    for text, style in block:
        print(colorize(text, style))
    print(colorize(
        "  Score will not update until the queue is clear and you run `desloppify scan`.",
        "dim",
    ))


def print_objective_drained_banner(
    frozen_strict: float,
    remaining: int,
    breakdown: QueueBreakdown,
) -> None:
    """Show a phase-transition banner when objective work is drained."""
    kind_labels: list[str] = []
    if breakdown.subjective > 0:
        kind_labels.append("subjective")
    if breakdown.workflow > 0:
        kind_labels.append("workflow")
    kind_desc = " + ".join(kind_labels) if kind_labels else "non-objective"
    print(colorize(
        f"\n  Objective queue complete (plan-start was {frozen_strict:.1f})."
        f" {remaining} {kind_desc} item{'s' if remaining != 1 else ''} remain.",
        "cyan",
    ))
    print(colorize(
        "  Run `desloppify next` for remaining work,"
        " then `desloppify scan` to finalize.",
        "dim",
    ))


def print_execution_or_reveal(
    state: dict,
    prev,
    plan: dict | None,
) -> None:
    """Context-aware score display using :func:`score_display_mode`."""
    frozen_strict = get_plan_start_strict(plan)
    breakdown: QueueBreakdown | None = None

    if frozen_strict is not None:
        try:
            breakdown = plan_aware_queue_breakdown(state, plan)
        except PLAN_LOAD_EXCEPTIONS:
            _logger.debug("queue breakdown computation skipped", exc_info=True)

    mode = score_display_mode(breakdown, frozen_strict)

    if mode is ScoreDisplayMode.FROZEN:
        print_frozen_score_with_queue_context(
            breakdown,
            frozen_strict=frozen_strict,
            live_score=score_snapshot(state).strict,
        )
        return

    # LIVE or PHASE_TRANSITION: show current scores
    score_update_mod = load_score_update_module()
    score_update_mod.print_score_update(state, prev)

    if mode is ScoreDisplayMode.PHASE_TRANSITION:
        print_objective_drained_banner(frozen_strict, breakdown.queue_total, breakdown)


def show_score_with_plan_context(state: dict, prev) -> None:
    """Load plan (best-effort) and show frozen or live score context.

    Encapsulates the common load_plan + PLAN_LOAD_EXCEPTIONS + reveal
    choreography so command modules don't each repeat it.
    """
    try:
        plan = load_plan()
    except PLAN_LOAD_EXCEPTIONS as exc:
        _logger.debug("score display skipped plan-aware context", exc_info=exc)
        plan = None
    print_execution_or_reveal(state, prev, plan)


__all__ = [
    "QueueBreakdown",
    "ScoreDisplayMode",
    "format_plan_delta",
    "format_queue_block",
    "format_queue_headline",
    "get_plan_start_strict",
    "plan_aware_queue_breakdown",
    "print_execution_or_reveal",
    "print_objective_drained_banner",
    "print_frozen_score_with_queue_context",
    "score_display_mode",
    "show_score_with_plan_context",
]
