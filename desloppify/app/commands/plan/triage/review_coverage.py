"""Review-coverage helpers for triage planning."""

from __future__ import annotations

from desloppify.app.commands.plan.shared.cluster_membership import cluster_issue_ids
from desloppify.engine._plan.policy.stale import open_review_ids, triage_open_review_ids
from desloppify.engine._plan.triage.lifecycle import ensure_active_triage_issue_ids
from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._state.schema import StateModel
from desloppify.engine.plan_state import Cluster, PlanModel
from desloppify.engine.plan_triage import (
    active_triage_issue_ids as _active_triage_issue_ids,
)
from desloppify.engine.plan_triage import (
    coverage_open_ids as _coverage_open_ids,
)
from desloppify.engine.plan_triage import (
    find_cluster_for as _find_cluster_for,
)
from desloppify.engine.plan_triage import (
    live_active_triage_issue_ids as _live_active_triage_issue_ids,
)
from desloppify.engine.plan_triage import (
    manual_clusters_with_issues as _manual_clusters_with_issues,
)
from desloppify.engine.plan_triage import (
    plan_review_ids as _plan_review_ids,
)
from desloppify.engine.plan_triage import (
    triage_coverage as _triage_coverage,
)
from desloppify.engine.plan_triage import (
    undispositioned_triage_issue_ids as _undispositioned_triage_issue_ids,
)

from .plan_state_access import ensure_triage_meta

_ACTIVE_TRIAGE_ISSUE_IDS_KEY = "active_triage_issue_ids"
_UNDISPOSITIONED_TRIAGE_ISSUES_KEY = "undispositioned_issue_ids"
_UNDISPOSITIONED_TRIAGE_COUNT_KEY = "undispositioned_issue_count"


def open_review_ids_from_state(state: StateModel) -> set[str]:
    """Return open review IDs from the current state snapshot."""
    return open_review_ids(state)


def triage_open_review_ids_from_state(plan: PlanModel, state: StateModel) -> set[str]:
    """Return live review IDs that remain in automated triage scope."""
    return open_review_ids_from_state(state) - protected_review_issue_ids(plan)


def has_open_review_issues(
    state: StateModel | dict | None,
    plan: PlanModel | None = None,
) -> bool:
    """Return True when any review issues remain eligible for triage work."""
    state_data = state or {}
    if plan is None:
        return bool(open_review_ids_from_state(state_data))
    return bool(triage_open_review_ids(plan, state_data))


def plan_review_ids(plan: PlanModel) -> list[str]:
    """Return review/concerns IDs currently represented in queue_order."""
    return _plan_review_ids(plan)


def coverage_open_ids(plan: PlanModel, state: StateModel) -> set[str]:
    """Return the frozen or live open review IDs covered by this triage run."""
    return _coverage_open_ids(plan, state)


def active_triage_issue_ids(
    plan: PlanModel,
    state: StateModel | None = None,
) -> set[str]:
    """Return the frozen review issue set for the current triage run."""
    return _active_triage_issue_ids(plan, state)


def live_active_triage_issue_ids(
    plan: PlanModel,
    state: StateModel | None = None,
) -> set[str]:
    """Return frozen triage IDs that are still open review issues in state."""
    return _live_active_triage_issue_ids(plan, state)


def clear_active_triage_issue_tracking(meta: dict[str, object]) -> None:
    """Clear frozen triage coverage metadata after successful completion."""
    meta.pop(_ACTIVE_TRIAGE_ISSUE_IDS_KEY, None)
    meta.pop(_UNDISPOSITIONED_TRIAGE_ISSUES_KEY, None)
    meta.pop(_UNDISPOSITIONED_TRIAGE_COUNT_KEY, None)


def undispositioned_triage_issue_ids(
    plan: PlanModel,
    state: StateModel | None = None,
) -> list[str]:
    """Return frozen triage issues still lacking cluster/skip/dismiss coverage."""
    return _undispositioned_triage_issue_ids(plan, state)


def sync_undispositioned_triage_meta(
    plan: PlanModel,
    state: StateModel | None = None,
) -> list[str]:
    """Persist the current undispositioned triage issue set for recovery UX."""
    meta = ensure_triage_meta(plan)
    missing = undispositioned_triage_issue_ids(plan, state)
    if missing:
        meta[_UNDISPOSITIONED_TRIAGE_ISSUES_KEY] = missing
        meta[_UNDISPOSITIONED_TRIAGE_COUNT_KEY] = len(missing)
    else:
        meta.pop(_UNDISPOSITIONED_TRIAGE_ISSUES_KEY, None)
        meta.pop(_UNDISPOSITIONED_TRIAGE_COUNT_KEY, None)
    return missing


def triage_coverage(
    plan: PlanModel,
    open_review_ids: set[str] | None = None,
) -> tuple[int, int, dict[str, Cluster]]:
    """Return (organized, total, clusters) for review issues in triage."""
    organized, total, clusters = _triage_coverage(plan, open_review_ids=open_review_ids)
    return organized, total, clusters


def manual_clusters_with_issues(plan: PlanModel) -> list[str]:
    """Return manual clusters that currently own at least one issue."""
    return _manual_clusters_with_issues(plan)


def find_cluster_for(fid: str, clusters: dict[str, Cluster]) -> str | None:
    """Return the owning cluster name for an issue ID, if any."""
    return _find_cluster_for(fid, clusters)


__all__ = [
    "active_triage_issue_ids",
    "clear_active_triage_issue_tracking",
    "cluster_issue_ids",
    "coverage_open_ids",
    "ensure_active_triage_issue_ids",
    "find_cluster_for",
    "has_open_review_issues",
    "live_active_triage_issue_ids",
    "manual_clusters_with_issues",
    "open_review_ids_from_state",
    "plan_review_ids",
    "sync_undispositioned_triage_meta",
    "triage_open_review_ids_from_state",
    "triage_coverage",
    "undispositioned_triage_issue_ids",
]
