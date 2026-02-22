"""Unified work-queue selection for next/show/plan views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from desloppify.state import StateModel

from desloppify.engine._work_queue.helpers import (
    ALL_STATUSES,
    ATTEST_EXAMPLE,
    build_subjective_items,
    scope_matches,
)
from desloppify.engine._work_queue.ranking import (
    build_finding_items,
    choose_fallback_tier,
    group_queue_items,
    item_explain,
    item_sort_key,
    tier_counts,
)


@dataclass(frozen=True)
class QueueBuildOptions:
    """Configuration for queue construction and tier selection behavior."""

    tier: int | None = None
    count: int | None = 1
    scan_path: str | None = None
    scope: str | None = None
    status: str = "open"
    include_subjective: bool = True
    subjective_threshold: float = 100.0
    chronic: bool = False
    no_tier_fallback: bool = False
    explain: bool = False


class WorkQueueResult(TypedDict):
    """Typed shape of the dict returned by :func:`build_work_queue`."""

    items: list[dict]
    total: int
    tier_counts: dict[int, int]
    requested_tier: int | None
    selected_tier: int | None
    fallback_reason: str | None
    available_tiers: list[int]
    grouped: dict[str, list[dict]]


def build_work_queue(
    state: StateModel,
    *,
    options: QueueBuildOptions | None = None,
) -> WorkQueueResult:
    """Build ranked queue items + tier metadata."""
    resolved_options = options or QueueBuildOptions()

    status = resolved_options.status
    if status not in ALL_STATUSES:
        raise ValueError(f"Unsupported status filter: {status}")
    try:
        subjective_threshold_value = float(resolved_options.subjective_threshold)
    except (TypeError, ValueError):
        subjective_threshold_value = 100.0
    subjective_threshold_value = max(0.0, min(100.0, subjective_threshold_value))

    finding_items = build_finding_items(
        state,
        scan_path=resolved_options.scan_path,
        status_filter=status,
        scope=resolved_options.scope,
        chronic=resolved_options.chronic,
    )

    all_items = list(finding_items)
    if (
        resolved_options.include_subjective
        and status in {"open", "all"}
        and not resolved_options.chronic
    ):
        subjective_items = build_subjective_items(
            state,
            state.get("findings", {}),
            threshold=subjective_threshold_value,
        )
        for item in subjective_items:
            if scope_matches(item, resolved_options.scope):
                all_items.append(item)

    all_items.sort(key=item_sort_key)
    counts = tier_counts(all_items)

    requested_tier = (
        int(resolved_options.tier) if resolved_options.tier is not None else None
    )
    selected_tier = requested_tier
    fallback_reason = None
    filtered = all_items

    if requested_tier is not None:
        filtered = [
            item
            for item in all_items
            if int(item.get("effective_tier", item.get("tier", 3))) == requested_tier
        ]
        if not filtered and not resolved_options.no_tier_fallback:
            chosen = choose_fallback_tier(requested_tier, counts)
            if chosen is not None:
                selected_tier = chosen
                filtered = [
                    item
                    for item in all_items
                    if int(item.get("effective_tier", item.get("tier", 3))) == chosen
                ]
                fallback_reason = (
                    f"Requested T{requested_tier} has 0 open -> showing T{chosen} "
                    "(nearest non-empty)."
                )
        elif not filtered:
            fallback_reason = f"Requested T{requested_tier} has 0 open."

    total = len(filtered)
    if resolved_options.count is not None and resolved_options.count > 0:
        filtered = filtered[: resolved_options.count]

    if resolved_options.explain:
        for item in filtered:
            item["explain"] = item_explain(item)

    available_tiers = [tier for tier, value in counts.items() if value > 0]
    return {
        "items": filtered,
        "total": total,
        "tier_counts": counts,
        "requested_tier": requested_tier,
        "selected_tier": selected_tier,
        "fallback_reason": fallback_reason,
        "available_tiers": available_tiers,
        "grouped": group_queue_items(filtered, "item"),
    }


__all__ = [
    "ATTEST_EXAMPLE",
    "QueueBuildOptions",
    "WorkQueueResult",
    "build_work_queue",
    "group_queue_items",
]
