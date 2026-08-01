"""Review-import-specific queue sync helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from desloppify.engine._plan.promoted_ids import prune_promoted_ids
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._plan.sync.triage import (
    compute_new_issue_ids,
    compute_open_issue_ids,
    sync_triage_needed,
)
from desloppify.engine._plan.triage.protection import (
    clear_protected_triage_artifacts,
    protected_review_issue_ids,
)
from desloppify.engine._state.issue_semantics import is_triage_finding
from desloppify.engine._state.schema import StateModel


@dataclass
class ReviewImportSyncResult:
    """Summary of plan changes after a review import."""

    new_ids: set[str]
    added_to_queue: list[str]
    triage_injected: bool
    stale_pruned_from_queue: list[str] = field(default_factory=list)
    covered_subjective_pruned_from_queue: list[str] = field(default_factory=list)
    triage_injected_ids: list[str] = field(default_factory=list)
    triage_deferred: bool = False


def _has_triage_baseline(plan: PlanModel) -> bool:
    """Return True when triage has recorded at least one baseline issue ID."""
    meta = plan.get("epic_triage_meta", {})
    triaged_ids = meta.get("triaged_ids", [])
    return bool(triaged_ids)


def _review_issue_ids_for_import_sync(
    plan: PlanModel,
    state: StateModel,
    *,
    open_review_ids: set[str] | None = None,
) -> set[str]:
    """Return review IDs that should be synced into queue_order after import.

    No triage baseline yet: include all currently-open review IDs so the
    first import cannot drop follow-up work.
    Existing triage baseline: include only IDs that are new since triage.
    """
    if _has_triage_baseline(plan):
        return compute_new_issue_ids(plan, state)
    current_ids = set(open_review_ids) if open_review_ids is not None else compute_open_issue_ids(state)
    return current_ids - protected_review_issue_ids(plan)


def _is_review_queue_id(issue_id: str, state: StateModel) -> bool:
    """Return True for queue IDs representing triage findings.

    Falls back to known review queue ID prefixes only when the issue payload
    is absent.
    """
    issue = (state.get("work_items") or state.get("issues", {})).get(issue_id)
    if isinstance(issue, dict):
        return is_triage_finding(issue)
    return issue_id.startswith("review::") or issue_id.startswith("concerns::")


def _prune_stale_triage_meta(
    plan: PlanModel,
    *,
    stale_ids: set[str],
) -> None:
    """Drop stale review IDs from triage recovery metadata."""
    meta = plan.get("epic_triage_meta")
    if not isinstance(meta, dict) or not stale_ids:
        return

    active_ids = meta.get("active_triage_issue_ids")
    if isinstance(active_ids, list):
        filtered_active = [
            issue_id for issue_id in active_ids
            if isinstance(issue_id, str) and issue_id not in stale_ids
        ]
        if filtered_active:
            meta["active_triage_issue_ids"] = filtered_active
        else:
            meta.pop("active_triage_issue_ids", None)

    undispositioned_ids = meta.get("undispositioned_issue_ids")
    if isinstance(undispositioned_ids, list):
        filtered_undispositioned = [
            issue_id for issue_id in undispositioned_ids
            if isinstance(issue_id, str) and issue_id not in stale_ids
        ]
        if filtered_undispositioned:
            meta["undispositioned_issue_ids"] = filtered_undispositioned
            meta["undispositioned_issue_count"] = len(filtered_undispositioned)
        else:
            meta.pop("undispositioned_issue_ids", None)
            meta.pop("undispositioned_issue_count", None)


def _prune_stale_review_ids_from_plan(
    plan: PlanModel,
    state: StateModel,
    *,
    live_open_review_ids: set[str],
) -> list[str]:
    """Remove stale review IDs from queue-related plan containers.

    Review imports can auto-resolve prior review IDs. These IDs must be removed
    from queue_order (and linked queue metadata) or the queue can drift from
    state reality.
    """
    order: list[str] = plan["queue_order"]
    stale_ids = sorted(
        {
            issue_id
            for issue_id in order
            if _is_review_queue_id(issue_id, state) and issue_id not in live_open_review_ids
        }
    )
    if not stale_ids:
        return []

    stale_set = set(stale_ids)
    order[:] = [issue_id for issue_id in order if issue_id not in stale_set]
    prune_promoted_ids(plan, stale_set)
    _prune_stale_triage_meta(plan, stale_ids=stale_set)

    deferred = plan.get("deferred")
    if isinstance(deferred, list):
        plan["deferred"] = [issue_id for issue_id in deferred if issue_id not in stale_set]

    skipped = plan.get("skipped")
    if isinstance(skipped, dict):
        for issue_id in stale_set:
            skipped.pop(issue_id, None)

    for cluster in plan.get("clusters", {}).values():
        issue_ids = cluster.get("issue_ids")
        if not isinstance(issue_ids, list):
            continue
        cluster["issue_ids"] = [
            issue_id for issue_id in issue_ids if issue_id not in stale_set
        ]

    return stale_ids


def sync_plan_after_review_import(
    plan: PlanModel,
    state: StateModel,
    *,
    policy=None,
    inject_triage: bool = True,
) -> ReviewImportSyncResult | None:
    """Sync plan queue after review import. Pure engine function — no I/O.

    Appends new issue IDs to queue_order, prunes stale review IDs from queue
    containers, and injects triage stages if needed (respects mid-cycle guard
    — defers when objective work remains). Returns ``None`` when no queue
    changes are required.
    """
    ensure_plan_defaults(plan)
    clear_protected_triage_artifacts(plan, state)
    open_review_ids = compute_open_issue_ids(state)
    stale_pruned_from_queue = _prune_stale_review_ids_from_plan(
        plan,
        state,
        live_open_review_ids=open_review_ids,
    )
    new_ids = _review_issue_ids_for_import_sync(
        plan,
        state,
        open_review_ids=open_review_ids,
    )
    if not new_ids and not stale_pruned_from_queue:
        return None

    # Add new issue IDs to end of queue_order so they have position
    order: list[str] = plan["queue_order"]
    existing = set(order)
    added: list[str] = []
    for issue_id in sorted(new_ids):
        if issue_id not in existing:
            order.append(issue_id)
            added.append(issue_id)

    triage_injected_ids: list[str] = []
    triage_injected = False
    triage_deferred = False
    if inject_triage:
        triage_result = sync_triage_needed(plan, state, policy=policy)
        triage_injected_ids = list(getattr(triage_result, "injected", []) or [])
        triage_injected = bool(triage_injected_ids)
        triage_deferred = bool(triage_result and getattr(triage_result, "deferred", False))

    return ReviewImportSyncResult(
        new_ids=new_ids,
        added_to_queue=added,
        stale_pruned_from_queue=stale_pruned_from_queue,
        triage_injected=triage_injected,
        triage_injected_ids=triage_injected_ids,
        triage_deferred=triage_deferred,
    )


__all__ = ["ReviewImportSyncResult", "sync_plan_after_review_import"]
