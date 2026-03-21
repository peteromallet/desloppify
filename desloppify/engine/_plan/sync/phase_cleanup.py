"""Cleanup helpers for stale synthetic queue items across lifecycle phases."""

from __future__ import annotations

from collections.abc import Iterable

from desloppify.engine._plan.constants import (
    TRIAGE_PREFIX,
    WORKFLOW_PREFIX,
)
from desloppify.engine._plan.refresh_lifecycle import (
    LIFECYCLE_PHASE_EXECUTE,
    LIFECYCLE_PHASE_REVIEW_POSTFLIGHT,
    LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT,
    LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT,
)
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults


def _phase_prefixes(phase: str) -> tuple[str, ...]:
    if phase == LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT:
        return ()
    if phase in {LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT, LIFECYCLE_PHASE_REVIEW_POSTFLIGHT}:
        return (WORKFLOW_PREFIX,)
    if phase == LIFECYCLE_PHASE_EXECUTE:
        return (WORKFLOW_PREFIX, TRIAGE_PREFIX)
    return ()


def _matches_any_prefix(issue_id: str, prefixes: Iterable[str]) -> bool:
    return any(issue_id.startswith(prefix) for prefix in prefixes)


def prune_synthetic_for_phase(plan: PlanModel, phase: str) -> list[str]:
    """Remove synthetic IDs that should not survive into ``phase``."""
    ensure_plan_defaults(plan)
    prefixes = _phase_prefixes(phase)
    if not prefixes:
        return []

    pruned: list[str] = []
    seen: set[str] = set()

    queue_order = plan.get("queue_order", [])
    kept_order: list[str] = []
    for raw_id in queue_order:
        if not isinstance(raw_id, str) or not _matches_any_prefix(raw_id, prefixes):
            kept_order.append(raw_id)
            continue
        if raw_id not in seen:
            pruned.append(raw_id)
            seen.add(raw_id)
    plan["queue_order"] = kept_order

    overrides = plan.get("overrides")
    if isinstance(overrides, dict):
        for issue_id in list(overrides):
            if isinstance(issue_id, str) and _matches_any_prefix(issue_id, prefixes):
                overrides.pop(issue_id, None)

    clusters = plan.get("clusters")
    if isinstance(clusters, dict):
        for cluster in clusters.values():
            if not isinstance(cluster, dict):
                continue
            issue_ids = cluster.get("issue_ids")
            if not isinstance(issue_ids, list):
                continue
            cluster["issue_ids"] = [
                issue_id
                for issue_id in issue_ids
                if not (
                    isinstance(issue_id, str)
                    and _matches_any_prefix(issue_id, prefixes)
                )
            ]

    return pruned


__all__ = ["prune_synthetic_for_phase"]
