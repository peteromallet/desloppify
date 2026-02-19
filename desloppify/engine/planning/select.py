"""Finding prioritization/selection helpers for next items."""

from __future__ import annotations

from desloppify.engine.planning.types import PlanItem, PlanState
from desloppify.engine.work_queue_internal.core import (
    QueueBuildOptions,
    build_work_queue,
)


def get_next_items(
    state: PlanState,
    tier: int | None = None,
    count: int = 1,
    scan_path: str | None = None,
) -> list[PlanItem]:
    """Get the N highest-priority open findings.

    Legacy plan API intentionally returns only finding items (not synthetic
    subjective queue items) so existing planner consumers stay stable.
    """
    result = build_work_queue(
        state,
        options=QueueBuildOptions(
            tier=tier,
            count=count,
            scan_path=scan_path,
            status="open",
            include_subjective=False,
            no_tier_fallback=True,
        ),
    )
    return [item for item in result["items"] if item.get("kind") == "finding"]


def get_next_item(
    state: PlanState,
    tier: int | None = None,
    scan_path: str | None = None,
) -> PlanItem | None:
    """Get the highest-priority open finding."""
    items = get_next_items(state, tier=tier, count=1, scan_path=scan_path)
    return items[0] if items else None
