"""Canonical triage coverage and status snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.engine._plan.cluster_membership import cluster_issue_ids
from desloppify.engine._plan.constants import TRIAGE_IDS, is_synthetic_id
from desloppify.engine._plan.policy.stale import open_review_ids
from desloppify.engine._plan.schema import Cluster, PlanModel
from desloppify.engine._plan.triage.playbook import TriageProgress, compute_triage_progress
from desloppify.engine._state.schema import StateModel


_cluster_issue_ids = cluster_issue_ids


def _normalized_issue_id_list(raw_ids: object) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw_ids, list):
        return normalized
    for raw_id in raw_ids:
        if not isinstance(raw_id, str):
            continue
        issue_id = raw_id.strip()
        if not issue_id or issue_id in seen:
            continue
        seen.add(issue_id)
        normalized.append(issue_id)
    return normalized


def plan_review_ids(plan: PlanModel) -> list[str]:
    """Return review/concerns IDs currently represented in queue_order."""
    return [
        issue_id
        for issue_id in plan.get("queue_order", [])
        if isinstance(issue_id, str)
        and not is_synthetic_id(issue_id)
        and (issue_id.startswith("review::") or issue_id.startswith("concerns::"))
    ]


def coverage_open_ids(plan: PlanModel, state: StateModel) -> set[str]:
    """Return the frozen or live open review IDs covered by this triage run."""
    meta = plan.get("epic_triage_meta", {})
    active_ids = _normalized_issue_id_list(meta.get("active_triage_issue_ids"))
    if "active_triage_issue_ids" in meta:
        return set(active_ids)
    has_completed_scan = bool(state.get("last_scan"))
    review_ids = open_review_ids(state)
    if not has_completed_scan and not review_ids:
        return set(plan_review_ids(plan))
    return review_ids


def active_triage_issue_ids(plan: PlanModel, state: StateModel | None = None) -> set[str]:
    """Return the frozen review issue set for the current triage run."""
    meta = plan.get("epic_triage_meta", {})
    active_ids = _normalized_issue_id_list(meta.get("active_triage_issue_ids"))
    if "active_triage_issue_ids" in meta:
        return set(active_ids)
    if state is None:
        return set()
    return coverage_open_ids(plan, state)


def _explicit_active_triage_issue_ids(plan: PlanModel) -> set[str]:
    meta = plan.get("epic_triage_meta", {})
    return set(_normalized_issue_id_list(meta.get("active_triage_issue_ids")))


def live_active_triage_issue_ids(plan: PlanModel, state: StateModel | None = None) -> set[str]:
    """Return frozen triage IDs that are still open review issues in state."""
    frozen_ids = active_triage_issue_ids(plan, state)
    if state is None or not frozen_ids:
        return frozen_ids
    return frozen_ids & open_review_ids(state)


def undispositioned_triage_issue_ids(plan: PlanModel, state: StateModel | None = None) -> list[str]:
    """Return frozen triage issues still lacking cluster/skip/dismiss coverage."""
    target_ids = live_active_triage_issue_ids(plan, state)
    if not target_ids:
        return []

    covered_ids: set[str] = set()
    for cluster in plan.get("clusters", {}).values():
        if cluster.get("auto"):
            continue
        covered_ids.update(_cluster_issue_ids(cluster))

    skipped = plan.get("skipped", {})
    covered_ids.update(issue_id for issue_id in skipped if isinstance(issue_id, str))

    meta = plan.get("epic_triage_meta", {})
    covered_ids.update(_normalized_issue_id_list(meta.get("dismissed_ids")))

    dispositions = meta.get("issue_dispositions", {})
    for issue_id, disposition in dispositions.items():
        if disposition.get("decision_source") == "observe_auto" and issue_id in skipped:
            covered_ids.add(issue_id)

    return sorted(issue_id for issue_id in target_ids if issue_id not in covered_ids)


def triage_coverage(
    plan: PlanModel,
    open_review_ids: set[str] | None = None,
) -> tuple[int, int, dict[str, Cluster]]:
    """Return (organized, total, clusters) for review issues in triage."""
    clusters = plan.get("clusters", {})
    all_cluster_ids: set[str] = set()
    for cluster in clusters.values():
        all_cluster_ids.update(_cluster_issue_ids(cluster))
    review_ids = list(open_review_ids) if open_review_ids is not None else plan_review_ids(plan)
    organized = sum(1 for issue_id in review_ids if issue_id in all_cluster_ids)
    return organized, len(review_ids), clusters


def manual_clusters_with_issues(plan: PlanModel) -> list[str]:
    """Return manual clusters that currently own at least one issue."""
    return [
        name
        for name, cluster in plan.get("clusters", {}).items()
        if cluster_issue_ids(cluster) and not cluster.get("auto")
    ]


def find_cluster_for(issue_id: str, clusters: dict[str, Cluster]) -> str | None:
    """Return the owning cluster name for an issue ID, if any."""
    for name, cluster in clusters.items():
        if issue_id in cluster_issue_ids(cluster):
            return name
    return None


@dataclass(frozen=True)
class TriageSnapshot:
    """Single shared triage-status snapshot for command surfaces."""

    progress: TriageProgress
    frozen_issue_ids: frozenset[str]
    live_open_ids: frozenset[str]
    new_since_triage_ids: frozenset[str]
    undispositioned_ids: frozenset[str]
    organized_count: int
    total_in_scope: int
    has_triage_in_queue: bool
    is_triage_stale: bool
    cycle_active: bool
    triage_has_run: bool


def build_triage_snapshot(plan: PlanModel, state: StateModel) -> TriageSnapshot:
    """Build a canonical triage snapshot from plan and state."""
    meta = plan.get("epic_triage_meta", {})
    triaged_ids = set(_normalized_issue_id_list(meta.get("triaged_ids")))
    frozen_ids = _explicit_active_triage_issue_ids(plan) & open_review_ids(state)
    live_open = open_review_ids(state)
    known_ids = triaged_ids | frozen_ids
    new_since = live_open - known_ids if known_ids else set()
    in_scope_ids = coverage_open_ids(plan, state)
    organized_count, total_in_scope, _clusters = triage_coverage(
        plan,
        open_review_ids=in_scope_ids,
    )

    return TriageSnapshot(
        progress=compute_triage_progress(meta.get("triage_stages", {})),
        frozen_issue_ids=frozenset(frozen_ids),
        live_open_ids=frozenset(live_open),
        new_since_triage_ids=frozenset(new_since),
        undispositioned_ids=frozenset(undispositioned_triage_issue_ids(plan, state)),
        organized_count=organized_count,
        total_in_scope=total_in_scope,
        has_triage_in_queue=bool(set(plan.get("queue_order", [])) & TRIAGE_IDS),
        is_triage_stale=bool(new_since),
        cycle_active=bool(frozen_ids),
        triage_has_run=bool(triaged_ids),
    )


__all__ = [
    "TriageSnapshot",
    "active_triage_issue_ids",
    "build_triage_snapshot",
    "coverage_open_ids",
    "find_cluster_for",
    "live_active_triage_issue_ids",
    "manual_clusters_with_issues",
    "plan_review_ids",
    "triage_coverage",
    "undispositioned_triage_issue_ids",
]
