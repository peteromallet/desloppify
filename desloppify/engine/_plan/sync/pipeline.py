"""Shared boundary-triggered plan reconciliation pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.engine._plan.auto_cluster import auto_cluster_issues
from desloppify.engine._plan.constants import (
    PRE_REVIEW_WORKFLOW_IDS,
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_DEFERRED_DISPOSITION_ID,
    WORKFLOW_RUN_SCAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    QueueSyncResult,
    is_synthetic_id,
)
from desloppify.engine._plan.operations.meta import append_log_entry
from desloppify.engine._plan.policy.stale import triage_open_review_ids
from desloppify.engine._plan.policy.subjective import compute_subjective_visibility
from desloppify.engine._plan.refresh_lifecycle import (
    _set_lifecycle_phase,
    derive_display_phase,
    user_facing_mode,
)
from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions
from desloppify.engine._plan.sync.phase_cleanup import prune_synthetic_for_phase
from desloppify.engine._plan.sync.triage import sync_triage_needed
from desloppify.engine._plan.sync.workflow import (
    ScoreSnapshot,
    sync_communicate_score_needed,
    sync_create_plan_needed,
)
from desloppify.engine._plan.triage.protection import clear_protected_triage_artifacts
from desloppify.engine._plan.triage.snapshot import build_triage_snapshot
from desloppify.state_scoring import score_snapshot

_SCAN_PHASE_WORKFLOW_IDS = {
    WORKFLOW_DEFERRED_DISPOSITION_ID,
    WORKFLOW_RUN_SCAN_ID,
}
_POSTFLIGHT_WORKFLOW_IDS = (
    PRE_REVIEW_WORKFLOW_IDS - _SCAN_PHASE_WORKFLOW_IDS
) | {
    WORKFLOW_SCORE_CHECKPOINT_ID,
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_CREATE_PLAN_ID,
}


@dataclass
class ReconcileResult:
    """Mutation summary for one boundary-triggered reconcile pass."""

    subjective: QueueSyncResult | None = None
    auto_cluster_changes: int = 0
    communicate_score: QueueSyncResult | None = None
    create_plan: QueueSyncResult | None = None
    triage: QueueSyncResult | None = None
    lifecycle_phase: str = ""
    lifecycle_phase_changed: bool = False
    phase_cleanup_pruned: list[str] | None = None
    # Snapshot of plan_start_scores captured when communicate_score auto-resolves,
    # before post-reconcile clearing can wipe them.
    checkpoint_plan_start: dict | None = None
    checkpoint_prev_start: dict | None = None

    @property
    def dirty(self) -> bool:
        return any(
            (
                self.subjective is not None and bool(self.subjective.changes),
                self.auto_cluster_changes > 0,
                self.communicate_score is not None
                and bool(self.communicate_score.changes),
                self.create_plan is not None and bool(self.create_plan.changes),
                self.triage is not None
                and bool(
                    self.triage.changes or getattr(self.triage, "deferred", False)
                ),
                self.lifecycle_phase_changed,
                bool(self.phase_cleanup_pruned),
            )
        )

    @property
    def workflow_injected_ids(self) -> list[str]:
        injected: list[str] = []
        for result in (self.communicate_score, self.create_plan):
            if result is None:
                continue
            injected.extend(list(result.injected))
        return injected


def _current_scores(state: dict) -> ScoreSnapshot:
    snapshot = score_snapshot(state)
    return ScoreSnapshot(
        strict=snapshot.strict,
        overall=snapshot.overall,
        objective=snapshot.objective,
        verified=snapshot.verified,
    )


def _log_gate_changes(plan: dict, action: str, detail: dict[str, object]) -> None:
    append_log_entry(plan, action, actor="system", detail=detail)


def _resolve_reconcile_display_phase(
    plan: dict,
    state: dict,
    *,
    result: ReconcileResult,
    policy: object | None,
) -> str:
    """Derive the display phase from queue contents.

    Returns a SHORT display name (review, assessment, workflow, triage,
    execute, scan) — never a persisted mode.

    Keep this equivalent to ``snapshot._derive_display_phase`` for materialized
    plan states. See ``test_phase_derivation_equivalence_matrix``.
    """
    order = [item for item in plan.get("queue_order", []) if isinstance(item, str)]
    plan_start_scores = plan.get("plan_start_scores")
    fresh_boundary = not plan_start_scores or (
        isinstance(plan_start_scores, dict) and bool(plan_start_scores.get("reset"))
    )

    subjective_ids = [item for item in order if item.startswith("subjective::")]
    unscored_ids = set(getattr(policy, "unscored_ids", ()) or ())
    has_initial_review = any(item in unscored_ids for item in subjective_ids)
    has_postflight_assessment = bool(subjective_ids) and not has_initial_review
    prefer_scan = any(item in _SCAN_PHASE_WORKFLOW_IDS for item in order)
    has_workflow = bool(result.workflow_injected_ids) or any(
        item in _POSTFLIGHT_WORKFLOW_IDS for item in order
    )
    has_triage = bool(
        (result.triage and (result.triage.injected or result.triage.deferred))
        or any(item.startswith("triage::") for item in order)
    )

    triage_snapshot = build_triage_snapshot(plan, state)
    triage_gated_review = (
        triage_snapshot.triage_has_run
        and not triage_snapshot.has_triage_in_queue
        and not triage_snapshot.is_triage_stale
        and bool(triage_snapshot.live_open_ids)
    )

    # Check for objective work in the queue.
    has_real_work = any(
        not item.startswith(("subjective::", "workflow::", "triage::"))
        for item in order
        if item not in (plan.get("skipped") or {})
    )
    has_review_postflight = triage_gated_review or (
        not has_real_work and bool(triage_open_review_ids(plan, state))
    )

    return derive_display_phase(
        has_initial_review=has_initial_review,
        has_postflight_assessment=has_postflight_assessment,
        has_workflow=has_workflow,
        has_triage=has_triage,
        has_review_postflight=has_review_postflight,
        has_execution=has_real_work,
        fresh_boundary=fresh_boundary,
        prefer_scan=prefer_scan,
    )


_MIGRATION_PRUNED_KEY = "_subjective_migration_pruned"


def _migrate_prune_stale_subjective(plan: dict) -> None:
    """One-time migration: remove stale subjective:: items from queue_order.

    The old system re-injected stale subjective items on every reconcile
    (not just at boundaries).  With boundary-only sync, these won't be
    re-added, but old plan files may still have them.  Prune them so they
    don't pollute phase derivation.  Runs at most once per plan.
    """
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        return
    if refresh_state.get(_MIGRATION_PRUNED_KEY):
        return  # Already done
    queue_order = plan.get("queue_order")
    if not isinstance(queue_order, list):
        return
    cleaned = [
        item_id
        for item_id in queue_order
        if not (isinstance(item_id, str) and item_id.startswith("subjective::"))
    ]
    if len(cleaned) < len(queue_order):
        plan["queue_order"] = cleaned
    refresh_state[_MIGRATION_PRUNED_KEY] = True


def live_planned_queue_empty(plan: dict) -> bool:
    """Return True when queue_order has no remaining substantive items.

    Overrides and clusters are ownership metadata — they must never expand
    the live queue.  Only explicit ``queue_order`` entries count.
    """
    order = plan.get("queue_order", [])
    skipped = plan.get("skipped", {})
    return not any(
        isinstance(item_id, str)
        and item_id not in skipped
        and not is_synthetic_id(item_id)
        for item_id in order
    )


def reconcile_plan(
    plan: dict,
    state: dict,
    *,
    target_strict: float,
    force_rescan: bool = False,
    defer_if_subjective_queued: bool = False,
) -> ReconcileResult:
    """Run the shared boundary reconciliation pipeline."""
    result = ReconcileResult()

    # Apply user-owned holds before queue, lifecycle, or auto-cluster
    # reconciliation can turn them back into executable work.
    clear_protected_triage_artifacts(plan, state)

    # Migration cleanup: prune stale subjective items from queue_order
    # left by the old mid-cycle re-injection bug.  With boundary-only sync
    # they won't be re-added, so they just block phase resolution.
    _migrate_prune_stale_subjective(plan)

    policy = compute_subjective_visibility(
        state,
        target_strict=target_strict,
        plan=plan,
    )

    result.subjective = sync_subjective_dimensions(
        plan,
        state,
        policy=policy,
    )
    if result.subjective.changes:
        _log_gate_changes(plan, "sync_subjective", {"changes": True})

    # Auto-clustering and heavier workflow reconciliation only runs at queue boundaries.
    if live_planned_queue_empty(plan) or force_rescan:
        result.auto_cluster_changes = int(
            auto_cluster_issues(
                plan,
                state,
                target_strict=target_strict,
                policy=policy,
            )
        )
        if result.auto_cluster_changes:
            _log_gate_changes(plan, "auto_cluster", {"changes": True})

        result.communicate_score = sync_communicate_score_needed(
            plan,
            state,
            policy=policy,
            current_scores=_current_scores(state),
            defer_if_subjective_queued=defer_if_subjective_queued,
        )
        if result.communicate_score.changes:
            _log_gate_changes(plan, "sync_communicate_score", {"auto_resolved": True})
            # Snapshot rebaseline fields now, before post-reconcile clearing
            if result.communicate_score.auto_resolved:
                result.checkpoint_plan_start = dict(plan.get("plan_start_scores", {}))
                result.checkpoint_prev_start = dict(plan.get("previous_plan_start_scores", {}))

        result.create_plan = sync_create_plan_needed(
            plan,
            state,
            policy=policy,
        )
        if result.create_plan.changes:
            _log_gate_changes(plan, "sync_create_plan", {"injected": True})

        result.triage = sync_triage_needed(
            plan,
            state,
            policy=policy,
        )
        if result.triage.injected:
            _log_gate_changes(plan, "sync_triage", {"injected": True})

    result.lifecycle_phase = _resolve_reconcile_display_phase(
        plan,
        state,
        result=result,
        policy=policy,
    )
    mode = user_facing_mode(result.lifecycle_phase)
    result.lifecycle_phase_changed = _set_lifecycle_phase(plan, mode)
    if result.lifecycle_phase_changed:
        _log_gate_changes(
            plan,
            "sync_lifecycle_phase",
            {"phase": result.lifecycle_phase},
        )

    result.phase_cleanup_pruned = prune_synthetic_for_phase(
        plan, result.lifecycle_phase
    )
    if result.phase_cleanup_pruned:
        _log_gate_changes(
            plan,
            "phase_transition_cleanup",
            {
                "phase": result.lifecycle_phase,
                "pruned": list(result.phase_cleanup_pruned),
            },
        )

    return result


__all__ = ["ReconcileResult", "live_planned_queue_empty", "reconcile_plan"]
