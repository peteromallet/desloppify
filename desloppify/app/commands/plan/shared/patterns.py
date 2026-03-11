"""Pattern -> issue-ID resolution shared across plan command capabilities."""

from __future__ import annotations

import fnmatch

from desloppify.engine.plan_state import PlanModel
from desloppify.engine._work_queue.core import QueueBuildOptions, build_work_queue
from desloppify.engine._state.resolution import match_issues
from desloppify.state_io import StateModel


def _append_unique(issue_id: str, seen: set[str], result: list[str]) -> None:
    if issue_id in seen:
        return
    seen.add(issue_id)
    result.append(issue_id)


def _collect_plan_ids(plan: PlanModel | None) -> set[str]:
    plan_ids: set[str] = set()
    if plan is None:
        return plan_ids
    plan_ids.update(plan.get("queue_order", []))
    plan_ids.update(plan.get("skipped", {}).keys())
    for cluster in plan.get("clusters", {}).values():
        plan_ids.update(cluster.get("issue_ids", []))
    return plan_ids


def _collect_queue_ids(state: StateModel, plan: PlanModel | None) -> set[str]:
    """Return IDs currently visible in the active queue (including synthetic IDs)."""
    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            plan=plan,
        ),
    )
    out: set[str] = set()
    for item in queue.get("items", []):
        issue_id = item.get("id")
        if isinstance(issue_id, str) and issue_id:
            out.add(issue_id)
    return out


def _queue_pattern_matches(queue_ids: set[str], pattern: str) -> list[str]:
    """Match a plan pattern against queue IDs (supports literals + globs)."""
    matches: list[str] = []
    for issue_id in queue_ids:
        if issue_id == pattern:
            matches.append(issue_id)
            continue
        if "*" in pattern and fnmatch.fnmatch(issue_id, pattern):
            matches.append(issue_id)
            continue
        if issue_id.startswith(pattern):
            matches.append(issue_id)
    return sorted(set(matches))


def resolve_ids_from_patterns(
    state: StateModel,
    patterns: list[str],
    *,
    plan: PlanModel | None = None,
    status_filter: str = "open",
) -> list[str]:
    """Resolve one or more patterns to a deduplicated list of issue IDs.

    When *plan* is provided, literal IDs that exist only in the plan
    (e.g. ``subjective::*`` synthetic items) are included even if they
    have no corresponding entry in ``state["issues"]``.
    """
    seen: set[str] = set()
    result: list[str] = []
    plan_ids = _collect_plan_ids(plan)
    queue_ids: set[str] | None = None

    for pattern in patterns:
        # Cascading match: state issues → plan IDs → plan globs → queue IDs → cluster names
        matches = match_issues(state, pattern, status_filter="open")
        if matches:
            for issue in matches:
                _append_unique(issue["id"], seen, result)
            continue

        if pattern in plan_ids:
            _append_unique(pattern, seen, result)
            continue

        plan_matches = _queue_pattern_matches(plan_ids, pattern)
        if plan_matches:
            for issue_id in plan_matches:
                _append_unique(issue_id, seen, result)
            continue

        # Lazy-load queue IDs only when needed
        if queue_ids is None:
            queue_ids = _collect_queue_ids(state, plan)
        queue_matches = _queue_pattern_matches(queue_ids, pattern)
        if queue_matches:
            for issue_id in queue_matches:
                _append_unique(issue_id, seen, result)
            continue

        # Fall back to cluster name expansion
        if plan is not None and pattern in plan.get("clusters", {}):
            for issue_id in plan["clusters"][pattern].get("issue_ids", []):
                _append_unique(issue_id, seen, result)

    return result


__all__ = ["resolve_ids_from_patterns"]
