"""Queue item selection from canonical snapshot or raw issue lists."""

from __future__ import annotations

from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._state.issue_semantics import is_review_work_item
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.helpers import scope_matches
from desloppify.engine._work_queue.inputs import gather_subjective_items
from desloppify.engine._work_queue.models import QueueBuildOptions, QueueVisibility
from desloppify.engine._work_queue.ranking import build_issue_items
from desloppify.engine._work_queue.snapshot import build_queue_snapshot
from desloppify.engine._work_queue.types import WorkQueueItem


def select_queue_items(
    state: StateModel,
    *,
    opts: QueueBuildOptions,
    plan: dict | None,
    scan_path: str | None,
    status: str,
    threshold: float,
    visibility: str,
) -> list[WorkQueueItem]:
    """Select the raw queue item list before ranking/finalization."""
    if status == "open" and not opts.chronic:
        snapshot = build_queue_snapshot(
            state,
            options=opts,
            plan=plan,
            target_strict=threshold,
        )
        return filter_snapshot_items(
            items_for_visibility(snapshot=snapshot, visibility=visibility),
            opts,
        )

    items = build_issue_items(
        state,
        scan_path=scan_path,
        status_filter=status,
        scope=opts.scope,
        chronic=opts.chronic,
    )
    if opts.include_subjective and status == "all":
        items += gather_subjective_items(state, opts, threshold)
    protected_ids = protected_review_issue_ids(plan)
    if protected_ids:
        items = [item for item in items if item.get("id", "") not in protected_ids]
    return items


def items_for_visibility(*, snapshot, visibility: str) -> list[WorkQueueItem]:
    """Select the snapshot partition for one queue surface."""
    if visibility == QueueVisibility.BACKLOG:
        source_items = snapshot.backlog_items or snapshot.execution_items
        return [
            dict(item)
            for item in source_items
            if item.get("kind") not in {"workflow_stage", "workflow_action"}
        ]
    return [dict(item) for item in snapshot.execution_items]


def filter_snapshot_items(
    items: list[WorkQueueItem],
    opts: QueueBuildOptions,
) -> list[WorkQueueItem]:
    """Apply view-local filtering after snapshot partition selection."""
    filtered = items
    if not opts.include_subjective:
        has_objective_issue = any(
            item.get("kind") in {"issue", "cluster"}
            and not is_review_work_item(item)
            for item in filtered
        )
        filtered = [
            item for item in filtered
            if item.get("kind") != "subjective_dimension"
            and not (has_objective_issue and is_review_work_item(item))
        ]
    if opts.scope:
        filtered = [
            item for item in filtered
            if item.get("kind") != "subjective_dimension" or scope_matches(item, opts.scope)
        ]
    return filtered


__all__ = [
    "filter_snapshot_items",
    "items_for_visibility",
    "select_queue_items",
]
