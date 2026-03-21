"""Sync subjective dimensions into the plan queue.

Single-pass sync for all three subjective categories:

- **unscored** — placeholder dimensions never yet reviewed.  Injected at cycle
  boundaries only; pruned mid-cycle.
- **stale** — dimensions whose assessment needs a review refresh.
- **under_target** — scored below target but not stale.

Invariant: stale reviews are non-deferrable. If a stale dimension is not
skipped, its ``subjective::`` ID stays in ``queue_order`` and is promoted to
the subjective lane immediately after workflow/triage items. Under-target
dimensions retain deferral and escalation behavior.
"""

from __future__ import annotations

from desloppify.base.config import DEFAULT_TARGET_STRICT_SCORE
from desloppify.engine._plan.policy import stale as stale_policy_mod
from desloppify.engine._plan.constants import (
    SUBJECTIVE_PREFIX,
    QueueSyncResult,
    is_triage_id,
    is_workflow_id,
)
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility
from desloppify.engine._state.schema import StateModel

from .context import has_objective_backlog, is_mid_cycle
from .defer_policy import (
    DeferEscalationOptions,
    DeferUpdateOptions,
    should_escalate_defer_state,
    update_defer_state,
)


# ---------------------------------------------------------------------------
# Defer-meta keys (shared with work_queue readers via plan dict)
# ---------------------------------------------------------------------------

_DEFER_META_KEY = "subjective_defer_meta"
_DEFER_IDS_FIELD = "deferred_review_ids"
_FORCE_IDS_KEY = "force_visible_ids"


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def current_unscored_ids(state: StateModel) -> set[str]:
    """Return the set of ``subjective::<slug>`` IDs that are currently unscored (placeholder).

    Checks ``subjective_assessments`` first; when that dict is empty
    (common before any reviews have been run), falls through to
    ``dimension_scores`` which carries placeholder metadata from scan.
    """
    return stale_policy_mod.current_unscored_ids(
        state,
        subjective_prefix=SUBJECTIVE_PREFIX,
    )


def current_under_target_ids(
    state: StateModel,
    *,
    target_strict: float = DEFAULT_TARGET_STRICT_SCORE,
) -> set[str]:
    """Return ``subjective::<slug>`` IDs that are under target but not stale or unscored.

    These are dimensions whose assessment is still current (not needing refresh)
    but whose score hasn't reached the target yet.
    """
    return stale_policy_mod.current_under_target_ids(
        state,
        target_strict=target_strict,
        subjective_prefix=SUBJECTIVE_PREFIX,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prune_subjective_ids(
    order: list[str],
    *,
    keep_ids: set[str],
    pruned: list[str],
) -> None:
    """Remove subjective IDs from *order* that are not in *keep_ids*, appending removed to *pruned*."""
    to_remove = [
        fid for fid in order
        if fid.startswith(SUBJECTIVE_PREFIX)
        and fid not in keep_ids
    ]
    for fid in to_remove:
        order.remove(fid)
        pruned.append(fid)


def _skipped_subjective_ids(plan: PlanModel) -> set[str]:
    """Return subjective IDs that are currently skipped in the plan."""
    skipped = plan.get("skipped", {})
    if not isinstance(skipped, dict):
        return set()
    return {
        str(fid)
        for fid in skipped
        if isinstance(fid, str) and fid.startswith(SUBJECTIVE_PREFIX)
    }


def _prune_skipped_subjective_ids(
    order: list[str],
    *,
    skipped_ids: set[str],
    pruned: list[str],
) -> None:
    """Repair invalid overlap by removing skipped subjective IDs from queue order."""
    if not skipped_ids:
        return
    to_remove = [fid for fid in order if fid in skipped_ids]
    for fid in to_remove:
        order.remove(fid)
        pruned.append(fid)


def _inject_subjective_ids(
    order: list[str],
    *,
    inject_ids: set[str],
    injected: list[str],
) -> None:
    """Inject subjective IDs into *order* if not already present.

    Always appends to the back — new items never reorder existing queue.
    """
    existing = set(order)
    for sid in sorted(inject_ids):
        if sid not in existing:
            order.append(sid)
            injected.append(sid)


# ---------------------------------------------------------------------------
# Deferral tracking and escalation
# ---------------------------------------------------------------------------

def _clear_defer_meta(plan: PlanModel) -> None:
    plan.pop(_DEFER_META_KEY, None)


def _promote_subjective_ids(order: list[str], ids: list[str]) -> int:
    """Move subjective IDs ahead of objective backlog while preserving order.

    Inserts after any workflow/triage items at the front of the queue.
    """
    target_ids: list[str] = []
    seen: set[str] = set()
    for fid in ids:
        sid = str(fid).strip()
        if not sid or sid in seen:
            continue
        target_ids.append(sid)
        seen.add(sid)
    if not target_ids:
        return 0

    insert_at = 0
    while insert_at < len(order):
        current = str(order[insert_at])
        if not (is_workflow_id(current) or is_triage_id(current)):
            break
        insert_at += 1

    changes = 0
    for sid in target_ids:
        existing_idx = order.index(sid) if sid in order else None
        target_idx = min(insert_at, len(order))
        if existing_idx is not None:
            if existing_idx == target_idx:
                insert_at += 1
                continue
            order.pop(existing_idx)
            if existing_idx < target_idx:
                target_idx -= 1
        order.insert(target_idx, sid)
        insert_at = target_idx + 1
        changes += 1
    return changes


def _update_deferral(
    plan: PlanModel,
    state: StateModel,
    *,
    injectable_ids: set[str],
    stale_ids: set[str],
    under_target_ids: set[str],
    skipped_ids: set[str],
) -> bool:
    """Update defer-meta and return True if escalation threshold is reached."""
    stale_deferred = sorted(stale_ids - skipped_ids)
    under_target_deferred = sorted(under_target_ids - skipped_ids)

    defer_state = update_defer_state(
        plan.get(_DEFER_META_KEY),
        state=state,
        deferred_ids=injectable_ids,
        options=DeferUpdateOptions(deferred_ids_field=_DEFER_IDS_FIELD),
    )
    defer_state["deferred_stale_ids"] = stale_deferred
    defer_state["deferred_under_target_ids"] = under_target_deferred

    escalated = should_escalate_defer_state(
        defer_state,
        state=state,
        options=DeferEscalationOptions(deferred_ids_field=_DEFER_IDS_FIELD),
    )

    if escalated:
        defer_state[_FORCE_IDS_KEY] = sorted(injectable_ids)
    else:
        defer_state.pop(_FORCE_IDS_KEY, None)

    plan[_DEFER_META_KEY] = defer_state
    return escalated


# ---------------------------------------------------------------------------
# Unified subjective dimension sync
# ---------------------------------------------------------------------------

def sync_subjective_dimensions(
    plan: PlanModel,
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None = None,
) -> QueueSyncResult:
    """Single-pass sync for all subjective dimensions in the plan queue.

    Handles three categories with unified prune/inject logic:

    - **unscored**: placeholder dimensions not yet reviewed.  Injected at cycle
      boundaries; pruned mid-cycle.
    - **stale**: dimensions needing review refresh.
    - **under_target**: scored below target but not stale.

    Stale/under-target paths diverge:

    1. **stale** — never deferred; always promoted after workflow/triage and
       before objective items unless explicitly skipped.
    2. **under_target** — deferred mid-cycle while objective backlog exists,
       then force-promoted after repeated deferrals.

    Unscored injection is unconditional at cycle boundaries, independent of
    backlog state.
    """
    ensure_plan_defaults(plan)
    result = QueueSyncResult()
    order: list[str] = plan["queue_order"]
    mid_cycle = is_mid_cycle(plan)

    # --- Compute all ID sets once -----------------------------------------
    unscored_ids = current_unscored_ids(state)
    stale_ids = stale_policy_mod.current_stale_ids(
        state, subjective_prefix=SUBJECTIVE_PREFIX,
    )
    under_target_ids = current_under_target_ids(state)
    skipped_ids = _skipped_subjective_ids(plan)
    stale_injectable = stale_ids - skipped_ids
    under_target_injectable = under_target_ids - skipped_ids

    # --- Resurface: clear skips for never-reviewed dimensions -------------
    if not mid_cycle:
        skipped_dict = plan.get("skipped", {})
        if isinstance(skipped_dict, dict):
            for sid in sorted(unscored_ids & skipped_ids):
                skipped_dict.pop(sid, None)
                result.resurfaced.append(sid)
            skipped_ids -= unscored_ids

    # --- Repair: remove skipped IDs from queue_order ----------------------
    _prune_skipped_subjective_ids(order, skipped_ids=skipped_ids, pruned=result.pruned)

    # --- Backlog and deferral ---------------------------------------------
    objective_backlog = has_objective_backlog(state, policy)
    should_defer_under_target = objective_backlog and mid_cycle
    escalated = False
    if should_defer_under_target and under_target_injectable:
        escalated = _update_deferral(
            plan, state,
            injectable_ids=under_target_injectable,
            stale_ids=set(),
            under_target_ids=under_target_ids,
            skipped_ids=skipped_ids,
        )
    else:
        _clear_defer_meta(plan)

    # --- Single prune pass ------------------------------------------------
    evicting_under_target = should_defer_under_target and not escalated
    if evicting_under_target:
        keep_ids = stale_injectable if mid_cycle else (unscored_ids | stale_injectable)
    else:
        keep_ids = stale_injectable | under_target_injectable
        if not mid_cycle:
            keep_ids |= unscored_ids
    _prune_subjective_ids(order, keep_ids=keep_ids, pruned=result.pruned)

    # --- Inject unscored (cycle boundaries only) --------------------------
    if not mid_cycle:
        _inject_subjective_ids(
            order,
            inject_ids=unscored_ids - skipped_ids,
            injected=result.injected,
        )

    # --- Inject or promote stale/under_target -----------------------------
    existing_before = set(order)
    if stale_injectable:
        _promote_subjective_ids(order, sorted(stale_injectable))
        for sid in sorted(stale_injectable):
            if sid not in existing_before:
                result.injected.append(sid)

    if escalated:
        _promote_subjective_ids(order, sorted(under_target_injectable))
    elif not evicting_under_target and under_target_injectable:
        _inject_subjective_ids(
            order,
            inject_ids=under_target_injectable,
            injected=result.injected,
        )

    return result


__all__ = [
    "current_under_target_ids",
    "current_unscored_ids",
    "sync_subjective_dimensions",
]
