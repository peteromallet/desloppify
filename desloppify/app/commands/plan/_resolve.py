"""Pattern → finding-ID resolution for plan commands."""

from __future__ import annotations

from desloppify.engine._plan.schema import PlanModel
from desloppify.engine._state.resolution import match_findings
from desloppify.engine._state.schema import StateModel


def resolve_ids_from_patterns(
    state: StateModel,
    patterns: list[str],
    *,
    plan: PlanModel | None = None,
    status_filter: str = "open",
) -> list[str]:
    """Resolve one or more patterns to a deduplicated list of finding IDs.

    When *plan* is provided, literal IDs that exist only in the plan
    (e.g. ``subjective::*`` synthetic items) are included even if they
    have no corresponding entry in ``state["findings"]``.
    """
    seen: set[str] = set()
    result: list[str] = []

    # Collect all plan IDs for literal-match fallback
    plan_ids: set[str] = set()
    if plan is not None:
        plan_ids.update(plan.get("queue_order", []))
        plan_ids.update(plan.get("skipped", {}).keys())
        for cluster in plan.get("clusters", {}).values():
            plan_ids.update(cluster.get("finding_ids", []))

    for pattern in patterns:
        matches = match_findings(state, pattern, status_filter=status_filter)
        if matches:
            for finding in matches:
                fid = finding["id"]
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)
        elif pattern in plan_ids and pattern not in seen:
            # Literal plan ID (e.g. subjective::foo) not in state findings
            seen.add(pattern)
            result.append(pattern)
    return result


__all__ = ["resolve_ids_from_patterns"]
