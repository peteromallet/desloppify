"""Triage sync — inject/prune triage stage IDs based on review issue changes."""

from __future__ import annotations

from desloppify.engine._plan.policy import stale as stale_policy_mod
from desloppify.engine._plan.constants import (
    TRIAGE_IDS,
    TRIAGE_STAGE_IDS,
    QueueSyncResult,
    confirmed_triage_stage_names,
    normalize_queue_workflow_and_triage_prefix,
    recorded_unconfirmed_triage_stage_names,
)
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility
from desloppify.engine._state.schema import StateModel

from .defer_policy import (
    DeferEscalationOptions,
    DeferUpdateOptions,
    should_escalate_defer_state,
    update_defer_state,
)
from .triage_start_policy import decide_triage_start

_TRIAGE_DEFER_META_KEY = "triage_defer_state"
_TRIAGE_DEFER_IDS_FIELD = "deferred_review_ids"
_TRIAGE_FORCE_VISIBLE_KEY = "triage_force_visible"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_review_ids_since_triage(
    state: StateModel,
    meta: dict,
) -> set[str]:
    """Return review issue IDs that are new since the last triage."""
    triaged_ids = set(meta.get("triaged_ids", []))
    active_ids = set(meta.get("active_triage_issue_ids", []))
    known_ids = triaged_ids | active_ids
    return stale_policy_mod.open_review_ids(state) - known_ids if known_ids else set()


def _baseline_triage_issue_ids(meta: dict) -> set[str]:
    triaged_ids = set(meta.get("triaged_ids", []))
    active_ids = set(meta.get("active_triage_issue_ids", []))
    return triaged_ids | active_ids


def _prune_all_triage_stages(order: list[str]) -> None:
    """Remove all ``triage::*`` stage IDs from *order*."""
    for sid in TRIAGE_STAGE_IDS:
        while sid in order:
            order.remove(sid)


def _inject_pending_triage_stages(
    order: list[str],
    confirmed: set[str],
    *,
    skipped: dict[str, object] | None = None,
) -> list[str]:
    """Inject triage stages for pending (unconfirmed) items.

    Always appends to the back — new items never reorder existing queue.
    Returns list of injected stage IDs.
    """
    stage_names = (
        "strategize",
        "observe",
        "reflect",
        "organize",
        "enrich",
        "sense-check",
        "commit",
    )
    existing = set(order)
    injected: list[str] = []
    for sid, name in zip(TRIAGE_STAGE_IDS, stage_names, strict=False):
        if name not in confirmed and sid not in existing:
            if skipped is not None:
                skipped.pop(sid, None)
            order.append(sid)
            injected.append(sid)
            existing.add(sid)
    return injected


def _clear_triage_defer_tracking(meta: dict) -> None:
    """Clear defer metadata once triage is no longer deferred."""
    meta.pop(_TRIAGE_DEFER_META_KEY, None)
    meta.pop(_TRIAGE_FORCE_VISIBLE_KEY, None)


def _store_triage_meta(plan: PlanModel, meta: dict) -> None:
    plan["epic_triage_meta"] = meta


def _inject_triage_result(
    order: list[str],
    confirmed: set[str],
    *,
    skipped: dict[str, object] | None = None,
    normalize: bool = False,
) -> QueueSyncResult:
    injected = _inject_pending_triage_stages(order, confirmed, skipped=skipped)
    if not injected:
        return QueueSyncResult()
    if normalize:
        normalize_queue_workflow_and_triage_prefix(order)
    return QueueSyncResult(injected=injected)


def _mark_triage_deferred(
    plan: PlanModel,
    meta: dict,
    *,
    defer_state: dict,
) -> QueueSyncResult:
    meta[_TRIAGE_DEFER_META_KEY] = defer_state
    meta["triage_recommended"] = True
    meta.pop(_TRIAGE_FORCE_VISIBLE_KEY, None)
    _store_triage_meta(plan, meta)
    return QueueSyncResult(deferred=True)


def _mark_triage_escalated(plan: PlanModel, meta: dict) -> None:
    meta[_TRIAGE_FORCE_VISIBLE_KEY] = True
    meta.pop("triage_recommended", None)
    _store_triage_meta(plan, meta)


def _mark_triage_ready(plan: PlanModel, meta: dict) -> None:
    _clear_triage_defer_tracking(meta)
    meta.pop("triage_recommended", None)
    _store_triage_meta(plan, meta)


def _prune_stale_present_stages(
    *,
    plan: PlanModel,
    state: StateModel,
    order: list[str],
    meta: dict,
    last_hash: str,
    confirmed: set[str],
    recorded_unconfirmed: set[str],
) -> QueueSyncResult:
    result = QueueSyncResult()
    if not last_hash or confirmed or recorded_unconfirmed:
        return result
    if not _baseline_triage_issue_ids(meta) and stale_policy_mod.open_review_ids(state):
        return result
    new_since_triage = _new_review_ids_since_triage(state, meta)
    if new_since_triage:
        return result
    _prune_all_triage_stages(order)
    _clear_triage_defer_tracking(meta)
    current_hash = stale_policy_mod.review_issue_snapshot_hash(state)
    if current_hash:
        meta["issue_snapshot_hash"] = current_hash
        plan["epic_triage_meta"] = meta
    result.pruned = list(TRIAGE_STAGE_IDS)
    return result


def _backfill_partial_triage_snapshot(
    *,
    plan: PlanModel,
    state: StateModel,
    meta: dict,
    last_hash: str,
) -> None:
    stages = meta.get("triage_stages", {})
    has_completed_stage = any(
        isinstance(v, dict) and v.get("confirmed_at")
        for v in stages.values()
    )
    if not has_completed_stage or meta.get("triaged_ids") or last_hash:
        return
    current_review = sorted(stale_policy_mod.open_review_ids(state))
    if current_review:
        meta["triaged_ids"] = current_review
        meta["issue_snapshot_hash"] = stale_policy_mod.review_issue_snapshot_hash(state)
        plan["epic_triage_meta"] = meta


def _defer_or_inject_triage(
    *,
    plan: PlanModel,
    state: StateModel,
    order: list[str],
    meta: dict,
    confirmed: set[str],
    policy: SubjectiveVisibility | None,
    new_since_triage: set[str],
) -> QueueSyncResult:
    decision = decide_triage_start(
        plan,
        state,
        policy=policy,
        explicit_start=False,
        attested_override=False,
    )
    if decision.action == "defer":
        defer_state = update_defer_state(
            meta.get(_TRIAGE_DEFER_META_KEY),
            state=state,
            deferred_ids=new_since_triage,
            options=DeferUpdateOptions(
                deferred_ids_field=_TRIAGE_DEFER_IDS_FIELD,
            ),
        )
        meta[_TRIAGE_DEFER_META_KEY] = defer_state
        escalated = should_escalate_defer_state(
            defer_state,
            state=state,
            options=DeferEscalationOptions(
                deferred_ids_field=_TRIAGE_DEFER_IDS_FIELD,
            ),
        )
        if not escalated:
            return _mark_triage_deferred(plan, meta, defer_state=defer_state)
        _mark_triage_escalated(plan, meta)
        return _inject_triage_result(
            order,
            confirmed,
            skipped=plan.get("skipped", {}),
            normalize=True,
        )

    _mark_triage_ready(plan, meta)
    return _inject_triage_result(
        order,
        confirmed,
        skipped=plan.get("skipped", {}),
    )


def _sync_hash_change(
    *,
    plan: PlanModel,
    state: StateModel,
    order: list[str],
    meta: dict,
    confirmed: set[str],
    policy: SubjectiveVisibility | None,
    current_hash: str,
) -> QueueSyncResult:
    new_since_triage = _new_review_ids_since_triage(state, meta)
    if not new_since_triage and not _baseline_triage_issue_ids(meta):
        new_since_triage = stale_policy_mod.open_review_ids(state)
    if new_since_triage:
        return _defer_or_inject_triage(
            plan=plan,
            state=state,
            order=order,
            meta=meta,
            confirmed=confirmed,
            policy=policy,
            new_since_triage=new_since_triage,
        )

    meta["issue_snapshot_hash"] = current_hash
    meta.pop("triage_recommended", None)
    _clear_triage_defer_tracking(meta)
    plan["epic_triage_meta"] = meta
    return QueueSyncResult()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_triage_stale(plan: PlanModel, state: StateModel) -> bool:
    """Side-effect-free check: is triage needed?

    Returns True when genuinely *new* review issues appeared since the
    last triage.  Triage stage IDs being in the queue alone is not
    sufficient — the new issues that triggered injection may have been
    resolved since then.

    When issues are merely resolved (current IDs are a subset of
    previously triaged IDs), triage is NOT stale — the user is working
    through the plan.
    """
    ensure_plan_defaults(plan)
    return stale_policy_mod.is_triage_stale(plan, state)


def compute_open_issue_ids(state: StateModel) -> set[str]:
    """Return the set of currently-open review/concerns issue IDs."""
    return stale_policy_mod.open_review_ids(state)


def compute_new_issue_ids(plan: PlanModel, state: StateModel) -> set[str]:
    """Return the set of open review/concerns issue IDs added since last triage.

    Returns an empty set when no prior triage has recorded ``triaged_ids``.
    """
    return stale_policy_mod.compute_new_issue_ids(plan, state)


def sync_triage_needed(
    plan: PlanModel,
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None = None,
) -> QueueSyncResult:
    """Append triage stage IDs to back of queue when review issues change.

    Only injects stages not already confirmed in ``epic_triage_meta``.

    **Mid-cycle guard**: when the objective backlog still has work, triage
    stages are NOT injected.  Instead, ``epic_triage_meta["triage_recommended"]``
    is set so the UI can show a non-blocking banner.  Stages are injected
    once the objective backlog drains (or on manual ``plan triage``). If
    deferral repeats for multiple scans/days, triage escalates and stages are
    injected in workflow/triage priority order with a forced-visibility marker.

    When stages are already present but all new issues have been resolved
    since injection, auto-prunes the stale stages and updates the hash.

    When issues are *resolved* (current IDs are a subset of previously
    triaged IDs), the snapshot hash is updated silently — no re-triage
    is needed since the user is working through the plan.
    """
    ensure_plan_defaults(plan)
    result = QueueSyncResult()
    order: list[str] = plan["queue_order"]
    meta = plan.get("epic_triage_meta", {})
    confirmed = confirmed_triage_stage_names(meta)
    recorded_unconfirmed = recorded_unconfirmed_triage_stage_names(meta)

    # Check if any triage stage is already in queue
    already_present = any(sid in order for sid in TRIAGE_IDS)

    current_hash = stale_policy_mod.review_issue_snapshot_hash(state)
    last_hash = meta.get("issue_snapshot_hash", "")

    if already_present:
        return _prune_stale_present_stages(
            plan=plan,
            state=state,
            order=order,
            meta=meta,
            last_hash=last_hash,
            confirmed=confirmed,
            recorded_unconfirmed=recorded_unconfirmed,
        )

    _backfill_partial_triage_snapshot(
        plan=plan,
        state=state,
        meta=meta,
        last_hash=last_hash,
    )

    if current_hash and current_hash != last_hash:
        return _sync_hash_change(
            plan=plan,
            state=state,
            order=order,
            meta=meta,
            confirmed=confirmed,
            policy=policy,
            current_hash=current_hash,
        )

    return result


__all__ = [
    "compute_open_issue_ids",
    "compute_new_issue_ids",
    "is_triage_stale",
    "sync_triage_needed",
]
