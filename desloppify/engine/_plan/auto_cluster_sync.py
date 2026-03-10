"""Internal sync helpers for auto-cluster regeneration."""

from __future__ import annotations

from desloppify.engine._plan.policy import stale as stale_policy_mod
from desloppify.engine._plan.sync.context import (
    has_objective_backlog as _has_objective_backlog,
)
from desloppify.engine._plan.sync.defer_policy import (
    DeferEscalationOptions,
    DeferUpdateOptions,
    should_escalate_defer_state,
    update_defer_state,
)
from desloppify.engine._plan.auto_cluster_sync_issue import (
    _sync_auto_cluster,
    sync_issue_clusters,
)
from desloppify.engine._plan.constants import SUBJECTIVE_PREFIX
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility
from desloppify.engine._plan.sync.auto_prune import prune_stale_clusters
from desloppify.engine._plan.sync.dimensions import (
    current_under_target_ids,
    current_unscored_ids,
)
from desloppify.engine._state.schema import StateModel

_MIN_CLUSTER_SIZE = 2
_STALE_KEY = "subjective::stale"
_STALE_NAME = "auto/stale-review"
_UNSCORED_KEY = "subjective::unscored"
_UNSCORED_NAME = "auto/initial-review"
_UNDER_TARGET_KEY = "subjective::under-target"
_UNDER_TARGET_NAME = "auto/under-target-review"
_MIN_UNSCORED_CLUSTER_SIZE = 1
_SUBJECTIVE_DEFER_META_KEY = "subjective_defer_meta"
_SUBJECTIVE_DEFER_IDS_FIELD = "deferred_review_ids"
_SUBJECTIVE_FORCE_IDS_KEY = "force_visible_ids"


def _subjective_state_sets(
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None,
    target_strict: float,
) -> tuple[set, set, set]:
    """Return (stale_ids, under_target_ids, unscored_ids) for subjective cluster logic."""
    if policy is not None:
        unscored_ids = policy.unscored_ids
        stale_ids = policy.stale_ids
        under_target_ids = policy.under_target_ids
    else:
        unscored_ids = current_unscored_ids(state)
        stale_ids = stale_policy_mod.current_stale_ids(
            state, subjective_prefix=SUBJECTIVE_PREFIX
        )
        under_target_ids = current_under_target_ids(state, target_strict=target_strict)
    return stale_ids, under_target_ids, unscored_ids


def _skipped_subjective_ids(plan: dict) -> set[str]:
    """Return skipped subjective IDs so auto-clusters don't re-queue them."""
    skipped = plan.get("skipped", {})
    if not isinstance(skipped, dict):
        return set()
    return {
        str(fid)
        for fid in skipped
        if isinstance(fid, str) and fid.startswith(SUBJECTIVE_PREFIX)
    }


def _clear_subjective_defer_meta(plan: dict) -> None:
    plan.pop(_SUBJECTIVE_DEFER_META_KEY, None)


def _promote_subjective_ids(order: list[str], ids: list[str]) -> int:
    """Move subjective IDs ahead of objective backlog while preserving order."""
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
        if not (
            current.startswith("workflow::") or current.startswith("triage::")
        ):
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


def sync_subjective_clusters(
    plan: dict,
    state: StateModel,
    issues: dict,
    clusters: dict,
    existing_by_key: dict[str, str],
    active_auto_keys: set[str],
    now: str,
    *,
    target_strict: float,
    policy: SubjectiveVisibility | None = None,
    cycle_just_completed: bool = False,
) -> int:
    """Sync unscored, stale, and under-target subjective dimension clusters."""
    changes = 0
    skipped_subjective_ids = _skipped_subjective_ids(plan)
    order = plan.get("queue_order", [])
    if skipped_subjective_ids and isinstance(order, list):
        overlap = [fid for fid in order if fid in skipped_subjective_ids]
        for fid in overlap:
            order.remove(fid)
            changes += 1

    all_subjective_ids = sorted(
        fid
        for fid in order
        if fid.startswith(SUBJECTIVE_PREFIX)
    )

    stale_state_ids, under_target_ids, unscored_state_ids = _subjective_state_sets(
        state, policy=policy, target_strict=target_strict
    )

    unscored_queue_ids = sorted(
        fid for fid in all_subjective_ids if fid in unscored_state_ids
    )
    stale_queue_ids = sorted(
        fid
        for fid in all_subjective_ids
        if fid in stale_state_ids and fid not in unscored_state_ids
    )

    if len(unscored_queue_ids) >= _MIN_UNSCORED_CLUSTER_SIZE:
        active_auto_keys.add(_UNSCORED_KEY)
        cli_keys = [fid.removeprefix(SUBJECTIVE_PREFIX) for fid in unscored_queue_ids]
        description = (
            f"Initial review of {len(unscored_queue_ids)} unscored subjective dimensions"
        )
        action = f"desloppify review --prepare --dimensions {','.join(cli_keys)}"
        sync_result = _sync_auto_cluster(
            plan,
            clusters,
            existing_by_key,
            cluster_key=_UNSCORED_KEY,
            cluster_name=_UNSCORED_NAME,
            member_ids=unscored_queue_ids,
            description=description,
            action=action,
            now=now,
        )
        changes += int(sync_result.changed)

    if len(stale_queue_ids) >= _MIN_CLUSTER_SIZE:
        active_auto_keys.add(_STALE_KEY)
        cli_keys = [fid.removeprefix(SUBJECTIVE_PREFIX) for fid in stale_queue_ids]
        description = f"Re-review {len(stale_queue_ids)} stale subjective dimensions"
        action = "desloppify review --prepare --dimensions " + ",".join(cli_keys)
        sync_result = _sync_auto_cluster(
            plan,
            clusters,
            existing_by_key,
            cluster_key=_STALE_KEY,
            cluster_name=_STALE_NAME,
            member_ids=stale_queue_ids,
            description=description,
            action=action,
            now=now,
        )
        changes += int(sync_result.changed)

    under_target_queue_ids = sorted(
        fid for fid in under_target_ids if fid not in skipped_subjective_ids
    )
    stale_candidate_ids = sorted(
        fid
        for fid in stale_state_ids
        if fid not in unscored_state_ids and fid not in skipped_subjective_ids
    )
    deferred_subjective_ids = sorted(
        set(stale_candidate_ids) | set(under_target_queue_ids)
    )

    prev_ut_cluster = clusters.get(_UNDER_TARGET_NAME, {})
    prev_ut_ids = set(prev_ut_cluster.get("issue_ids", []))
    ut_prune = [
        fid
        for fid in prev_ut_ids
        if fid not in under_target_ids
        and fid not in stale_state_ids
        and fid not in unscored_state_ids
        and fid in order
    ]
    for fid in ut_prune:
        order.remove(fid)
        changes += 1

    has_objective_items = _has_objective_backlog(issues, policy)

    if not has_objective_items and len(under_target_queue_ids) >= _MIN_CLUSTER_SIZE:
        active_auto_keys.add(_UNDER_TARGET_KEY)
        cli_keys = [fid.removeprefix(SUBJECTIVE_PREFIX) for fid in under_target_queue_ids]
        description = (
            f"Consider re-reviewing {len(under_target_queue_ids)} "
            f"dimensions under target score"
        )
        action = "desloppify review --prepare --dimensions " + ",".join(cli_keys)
        sync_result = _sync_auto_cluster(
            plan,
            clusters,
            existing_by_key,
            cluster_key=_UNDER_TARGET_KEY,
            cluster_name=_UNDER_TARGET_NAME,
            member_ids=under_target_queue_ids,
            description=description,
            action=action,
            now=now,
            optional=True,
        )
        changes += int(sync_result.changed)

        existing_order = set(order)
        for fid in under_target_queue_ids:
            if fid not in existing_order:
                order.append(fid)

    if has_objective_items and not cycle_just_completed:
        if deferred_subjective_ids:
            defer_state = update_defer_state(
                plan.get(_SUBJECTIVE_DEFER_META_KEY),
                state=state,
                deferred_ids=set(deferred_subjective_ids),
                options=DeferUpdateOptions(
                    deferred_ids_field=_SUBJECTIVE_DEFER_IDS_FIELD,
                    now=now,
                ),
            )
            escalated = should_escalate_defer_state(
                defer_state,
                state=state,
                options=DeferEscalationOptions(
                    deferred_ids_field=_SUBJECTIVE_DEFER_IDS_FIELD,
                    now=now,
                ),
            )
            if escalated:
                defer_state[_SUBJECTIVE_FORCE_IDS_KEY] = list(deferred_subjective_ids)
                plan[_SUBJECTIVE_DEFER_META_KEY] = defer_state
                changes += _promote_subjective_ids(order, deferred_subjective_ids)
            else:
                defer_state.pop(_SUBJECTIVE_FORCE_IDS_KEY, None)
                plan[_SUBJECTIVE_DEFER_META_KEY] = defer_state
                objective_evict = [
                    fid
                    for fid in order
                    if fid in under_target_ids or fid in stale_state_ids
                ]
                for fid in objective_evict:
                    order.remove(fid)
                    changes += 1
        else:
            _clear_subjective_defer_meta(plan)
    else:
        _clear_subjective_defer_meta(plan)

    return changes


__all__ = ["prune_stale_clusters", "sync_issue_clusters", "sync_subjective_clusters"]
