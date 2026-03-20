"""Shared boundary-triggered plan reconciliation pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.state_scoring import score_snapshot
from desloppify.engine._plan.auto_cluster import auto_cluster_issues
from desloppify.engine._plan.constants import QueueSyncResult, is_synthetic_id
from desloppify.engine._plan.operations.meta import append_log_entry
from desloppify.engine._plan.policy.subjective import compute_subjective_visibility
from desloppify.engine._plan.policy.stale import open_review_ids
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT,
    LIFECYCLE_PHASE_REVIEW_INITIAL,
    LIFECYCLE_PHASE_REVIEW_POSTFLIGHT,
    LIFECYCLE_PHASE_SCAN,
    LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT,
    LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT,
    current_lifecycle_phase,
    set_lifecycle_phase,
)
from desloppify.engine._plan.sync.dimensions import sync_subjective_dimensions
from desloppify.engine._plan.sync.phase_cleanup import prune_synthetic_for_phase
from desloppify.engine._plan.sync.triage import sync_triage_needed
from desloppify.engine._plan.triage.snapshot import build_triage_snapshot
from desloppify.engine._plan.sync.workflow import (
    ScoreSnapshot,
    _subjective_review_current_for_cycle,
    sync_communicate_score_needed,
    sync_create_plan_needed,
)


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

    @property
    def dirty(self) -> bool:
        return any(
            (
                self.subjective is not None and bool(self.subjective.changes),
                self.auto_cluster_changes > 0,
                self.communicate_score is not None
                and bool(self.communicate_score.changes),
                self.create_plan is not None
                and bool(self.create_plan.changes),
                self.triage is not None
                and bool(
                    self.triage.changes
                    or getattr(self.triage, "deferred", False)
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


def _resolve_reconcile_phase(
    plan: dict,
    state: dict,
    *,
    result: ReconcileResult,
    policy: object | None,
) -> str:
    order = [item for item in plan.get("queue_order", []) if isinstance(item, str)]
    if result.workflow_injected_ids or any(item.startswith("workflow::") for item in order):
        return LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT

    if result.triage and (result.triage.injected or result.triage.deferred):
        return LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT
    if any(item.startswith("triage::") for item in order):
        return LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT

    subjective_ids = [item for item in order if item.startswith("subjective::")]
    if subjective_ids:
        unscored_ids = set(getattr(policy, "unscored_ids", ()) or ())
        if any(item in unscored_ids for item in subjective_ids):
            return LIFECYCLE_PHASE_REVIEW_INITIAL
        return LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT

    triage_snapshot = build_triage_snapshot(plan, state)
    if (
        triage_snapshot.triage_has_run
        and not triage_snapshot.has_triage_in_queue
        and not triage_snapshot.is_triage_stale
        and bool(triage_snapshot.live_open_ids)
    ):
        return LIFECYCLE_PHASE_REVIEW_POSTFLIGHT

    persisted = current_lifecycle_phase(plan)
    if persisted:
        return persisted
    if open_review_ids(state):
        return LIFECYCLE_PHASE_REVIEW_POSTFLIGHT
    return LIFECYCLE_PHASE_SCAN


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
) -> ReconcileResult:
    """Run the shared boundary reconciliation pipeline."""
    result = ReconcileResult()
    if not live_planned_queue_empty(plan) and not force_rescan:
        return result

    policy = compute_subjective_visibility(
        state,
        target_strict=target_strict,
        plan=plan,
    )
    cycle_just_completed = not plan.get("plan_start_scores") or force_rescan

    # Skip subjective sync when workflow will supersede it: all dims are
    # scored and communicate-score hasn't fired yet this cycle.  The phase
    # cleanup safety net still prunes if this peek is wrong.
    will_inject_workflow = (
        not force_rescan
        and "previous_plan_start_scores" not in plan
        and _subjective_review_current_for_cycle(
            plan,
            state,
            policy=policy,
        )
    )
    if will_inject_workflow:
        result.subjective = QueueSyncResult()
    else:
        result.subjective = sync_subjective_dimensions(
            plan,
            state,
            policy=policy,
            cycle_just_completed=cycle_just_completed,
        )
        if result.subjective.changes:
            _log_gate_changes(plan, "sync_subjective", {"changes": True})

    if will_inject_workflow:
        result.auto_cluster_changes = 0
    else:
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
    )
    if result.communicate_score.changes:
        _log_gate_changes(plan, "sync_communicate_score", {"injected": True})

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

    result.lifecycle_phase = _resolve_reconcile_phase(
        plan,
        state,
        result=result,
        policy=policy,
    )
    result.lifecycle_phase_changed = set_lifecycle_phase(plan, result.lifecycle_phase)
    if result.lifecycle_phase_changed:
        _log_gate_changes(
            plan,
            "sync_lifecycle_phase",
            {"phase": result.lifecycle_phase},
        )

    result.phase_cleanup_pruned = prune_synthetic_for_phase(plan, result.lifecycle_phase)
    if result.phase_cleanup_pruned:
        _log_gate_changes(
            plan,
            "phase_transition_cleanup",
            {"phase": result.lifecycle_phase, "pruned": list(result.phase_cleanup_pruned)},
        )

    return result


__all__ = ["ReconcileResult", "live_planned_queue_empty", "reconcile_plan"]
