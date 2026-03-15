"""Post-scan plan reconciliation — sync plan queue metadata after a scan merge."""

from __future__ import annotations

import logging
from typing import Any

from desloppify import state as state_mod
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.output.terminal import colorize
from desloppify.app.commands.helpers.transition_messages import emit_transition_message
from desloppify.base.config import target_strict_score_from_config
from desloppify.engine._plan.constants import (
    WORKFLOW_COMMUNICATE_SCORE_ID,
    is_synthetic_id,
)
from desloppify.engine._plan.operations.meta import append_log_entry
from desloppify.engine._plan.persistence import load_plan, save_plan
from desloppify.engine._plan.scan_issue_reconcile import reconcile_plan_after_scan
from desloppify.engine._plan.refresh_lifecycle import (
    mark_postflight_scan_completed,
)
from desloppify.engine._plan.sync import (
    ReconcileResult,
    live_planned_queue_empty,
    reconcile_plan,
)
from desloppify.engine._plan.sync.dimensions import current_unscored_ids
from desloppify.engine._plan.sync.context import is_mid_cycle
from desloppify.engine._plan.sync.workflow import clear_score_communicated_sentinel
from desloppify.engine.work_queue import build_deferred_disposition_item

logger = logging.getLogger(__name__)


def _reset_cycle_for_force_rescan(plan: dict[str, object]) -> bool:
    """Clear synthetic queue items when --force-rescan is used.

    Preserves ``plan_start_scores`` so that ``is_mid_cycle()`` still
    returns True — this prevents ``auto_cluster_issues()`` from running
    full cluster regeneration, which would wipe manual cluster items.
    """
    order: list[str] = plan.get("queue_order", [])
    synthetic = [item for item in order if is_synthetic_id(item)]
    if not synthetic:
        return False
    for item in synthetic:
        order.remove(item)
    clear_score_communicated_sentinel(plan)
    meta = plan.get("epic_triage_meta", {})
    if isinstance(meta, dict):
        meta.pop("triage_recommended", None)
    count = len(synthetic)
    if count:
        print(
            colorize(
                f"  Plan: force-rescan — removed {count} synthetic item(s) "
                f"and reset cycle state.",
                "yellow",
            )
        )
    return True


def _plan_has_user_content(plan: dict[str, object]) -> bool:
    return bool(
        plan.get("queue_order")
        or plan.get("overrides")
        or plan.get("clusters")
        or plan.get("skipped")
    )


def _apply_plan_reconciliation(plan: dict[str, object], state: state_mod.StateModel) -> bool:
    if not _plan_has_user_content(plan):
        return False
    recon = reconcile_plan_after_scan(plan, state)
    if recon.resurfaced:
        print(
            colorize(
                f"  Plan: {len(recon.resurfaced)} skipped item(s) re-surfaced after review period.",
                "cyan",
            )
        )
    return bool(recon.changes)


def _seed_plan_start_scores(plan: dict[str, object], state: state_mod.StateModel) -> bool:
    """Set plan_start_scores when beginning a new queue cycle."""
    existing = plan.get("plan_start_scores")
    if existing and not isinstance(existing, dict):
        return False
    if existing and not existing.get("reset"):
        return False
    scores = state_mod.score_snapshot(state)
    if scores.strict is None:
        return False
    plan["plan_start_scores"] = {
        "strict": scores.strict,
        "overall": scores.overall,
        "objective": scores.objective,
        "verified": scores.verified,
    }
    clear_score_communicated_sentinel(plan)
    plan["scan_count_at_plan_start"] = int(state.get("scan_count", 0) or 0)
    return True


def _has_objective_cycle(
    state: state_mod.StateModel,
    plan: dict[str, object],
) -> bool | None:
    """Return True when objective queue work exists and a cycle baseline should freeze."""
    try:
        from desloppify.app.commands.helpers.queue_progress import plan_aware_queue_breakdown

        breakdown = plan_aware_queue_breakdown(state, plan)
    except PLAN_LOAD_EXCEPTIONS as exc:
        log_best_effort_failure(logger, "compute queue breakdown for plan-start seeding", exc)
        return None
    return breakdown.objective_actionable > 0


def _clear_plan_start_scores_if_queue_empty(
    state: state_mod.StateModel, plan: dict[str, object]
) -> bool:
    """Clear plan-start score snapshot once the queue is fully drained."""
    if not plan.get("plan_start_scores"):
        return False
    if WORKFLOW_COMMUNICATE_SCORE_ID in plan.get("queue_order", []):
        return False

    try:
        from desloppify.app.commands.helpers.queue_progress import (
            ScoreDisplayMode,
            plan_aware_queue_breakdown,
            score_display_mode,
        )

        breakdown = plan_aware_queue_breakdown(state, plan)
        frozen_strict = plan.get("plan_start_scores", {}).get("strict")
        queue_empty = score_display_mode(breakdown, frozen_strict) is not ScoreDisplayMode.FROZEN
    except PLAN_LOAD_EXCEPTIONS as exc:
        log_best_effort_failure(logger, "run post-scan plan reconciliation", exc)
        return False
    if not queue_empty:
        return False
    state["_plan_start_scores_for_reveal"] = dict(plan["plan_start_scores"])
    plan["plan_start_scores"] = {}
    clear_score_communicated_sentinel(plan)
    return True


def _mark_postflight_scan_completed_if_ready(
    state: state_mod.StateModel,
    plan: dict[str, object],
) -> bool:
    """Record that the cycle's post-review scan has completed."""
    if plan.get("plan_start_scores") and current_unscored_ids(state):
        return False
    if build_deferred_disposition_item(plan) is not None:
        return False
    return mark_postflight_scan_completed(
        plan,
        scan_count=int(state.get("scan_count", 0) or 0),
    )


def _sync_plan_start_scores_and_log(
    plan: dict[str, object],
    state: state_mod.StateModel,
) -> bool:
    seeded = _seed_plan_start_scores(plan, state)
    if seeded:
        append_log_entry(plan, "seed_start_scores", actor="system", detail={})
        return True
    cleared = _clear_plan_start_scores_if_queue_empty(state, plan)
    if cleared:
        append_log_entry(plan, "clear_start_scores", actor="system", detail={})
    return cleared


def _sync_postflight_scan_completion_and_log(
    plan: dict[str, object],
    state: state_mod.StateModel,
) -> bool:
    changed = _mark_postflight_scan_completed_if_ready(state, plan)
    if changed:
        append_log_entry(
            plan,
            "complete_postflight_scan",
            actor="system",
            detail={"scan_count": int(state.get("scan_count", 0) or 0)},
        )
    return changed


def _sync_post_scan_without_policy(
    *,
    plan: dict[str, object],
    state: state_mod.StateModel,
) -> bool:
    """Run post-scan sync steps that do not require subjective policy context."""
    return bool(_apply_plan_reconciliation(plan, state))


def _is_mid_cycle_scan(plan: dict[str, object], state: state_mod.StateModel) -> bool:
    """Return True when a plan cycle is active and queue items remain."""
    if not is_mid_cycle(plan):
        return False
    return not live_planned_queue_empty(plan)


def _display_reconcile_results(
    result: ReconcileResult,
    plan: dict,
    *,
    mid_cycle: bool,
) -> None:
    subjective = result.subjective
    if subjective and subjective.resurfaced:
        print(
            colorize(
                f"  Plan: {len(subjective.resurfaced)} skipped subjective dimension(s) resurfaced — never reviewed.",
                "yellow",
            )
        )
    if subjective and subjective.pruned:
        print(
            colorize(
                f"  Plan: {len(subjective.pruned)} refreshed subjective dimension(s) removed from queue.",
                "cyan",
            )
        )
    if subjective and subjective.injected:
        print(
            colorize(
                f"  Plan: {len(subjective.injected)} subjective dimension(s) queued for review.",
                "cyan",
            )
        )
    if mid_cycle and not result.auto_cluster_changes:
        print(
            colorize(
                "  Plan: mid-cycle scan — skipping cluster regeneration to preserve queue state.",
                "dim",
            )
        )
    if result.create_plan and result.create_plan.injected:
        print(
            colorize(
                "  Plan: reviews complete — `workflow::create-plan` queued.",
                "cyan",
            )
        )
    if (
        result.triage
        and result.triage.deferred
        and plan.get("epic_triage_meta", {}).get("triage_recommended")
    ):
        print(
            colorize(
                "  Plan: review work items changed — triage recommended after current work.",
                "dim",
            )
        )
    if result.triage and result.triage.injected:
        print(
            colorize(
                "  Plan: planning mode needed — review work items changed since last triage.",
                "cyan",
            )
        )


def reconcile_plan_post_scan(runtime: Any) -> None:
    """Reconcile plan queue metadata and stale subjective review dimensions."""
    plan_path = runtime.state_path.parent / "plan.json" if runtime.state_path else None
    try:
        plan = load_plan(plan_path)
    except PLAN_LOAD_EXCEPTIONS as exc:
        logger.warning("Plan reconciliation skipped (load failed): %s", exc)
        return

    force_rescan = getattr(runtime, "force_rescan", False)
    dirty = _reset_cycle_for_force_rescan(plan) if force_rescan else False
    dirty = _sync_post_scan_without_policy(plan=plan, state=runtime.state) or dirty

    boundary_crossed = live_planned_queue_empty(plan)
    if boundary_crossed:
        result = reconcile_plan(
            plan,
            runtime.state,
            target_strict=target_strict_score_from_config(runtime.config),
        )
        _display_reconcile_results(
            result,
            plan,
            mid_cycle=_is_mid_cycle_scan(plan, runtime.state) or force_rescan,
        )
        if result.lifecycle_phase_changed:
            emit_transition_message(result.lifecycle_phase)
        dirty = result.dirty or dirty

    if not force_rescan and _sync_plan_start_scores_and_log(plan, runtime.state):
        dirty = True
    if _sync_postflight_scan_completion_and_log(plan, runtime.state):
        dirty = True

    if dirty:
        try:
            save_plan(plan, plan_path)
        except PLAN_LOAD_EXCEPTIONS as exc:
            logger.warning("Plan reconciliation save failed: %s", exc)


__all__ = [
    "_clear_plan_start_scores_if_queue_empty",
    "_display_reconcile_results",
    "_has_objective_cycle",
    "_is_mid_cycle_scan",
    "_mark_postflight_scan_completed_if_ready",
    "_reset_cycle_for_force_rescan",
    "_seed_plan_start_scores",
    "_sync_plan_start_scores_and_log",
    "_sync_post_scan_without_policy",
    "_sync_postflight_scan_completion_and_log",
    "reconcile_plan_after_scan",
    "reconcile_plan_post_scan",
]
