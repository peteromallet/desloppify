"""Canonical queue mutation helpers for plan operations."""

from __future__ import annotations

from desloppify.engine._plan.promoted_ids import add_promoted_ids
from desloppify.engine._plan.schema import PlanModel, SkipEntry, ensure_plan_defaults
from desloppify.engine._plan.triage.protection import protected_review_issue_ids


def _remove_id_from_lists(plan: PlanModel, issue_id: str) -> None:
    """Remove an issue ID from queue_order and skipped."""
    order: list[str] = plan["queue_order"]
    skipped: dict[str, SkipEntry] = plan.get("skipped", {})
    if issue_id in order:
        order.remove(issue_id)
    skipped.pop(issue_id, None)


def _resolve_position(
    order: list[str],
    position: str,
    target: str | None = None,
    offset: int | None = None,
    issue_ids: list[str] | None = None,
) -> int:
    """Resolve a position specifier to an insertion index.

    ``issue_ids`` are the IDs being moved — used to calculate relative
    positions when they already exist in the list.
    """
    moving = set(issue_ids or [])

    if position == "top":
        return 0
    if position == "bottom":
        return len(order)

    if position in {"before", "after"} and target:
        return _resolve_relative_position(order, moving, position=position, target=target)

    if position in {"up", "down"} and offset is not None:
        return _resolve_offset_position(
            order,
            moving,
            position=position,
            offset=offset,
            issue_ids=issue_ids,
        )

    return len(order)


def _resolve_relative_position(
    order: list[str],
    moving: set[str],
    *,
    position: str,
    target: str,
) -> int:
    for i, item_id in enumerate(order):
        if item_id == target and item_id not in moving:
            return i if position == "before" else i + 1
    return 0 if position == "before" else len(order)


def _find_index(items: list[str], target: str) -> int | None:
    for i, item_id in enumerate(items):
        if item_id == target:
            return i
    return None


def _resolve_offset_position(
    order: list[str],
    moving: set[str],
    *,
    position: str,
    offset: int,
    issue_ids: list[str] | None,
) -> int:
    if not issue_ids:
        return 0 if position == "up" else len(order)
    first_id = issue_ids[0]
    clean_order = [x for x in order if x not in moving]
    current_idx = _find_index(clean_order, first_id)
    if current_idx is None:
        if position == "up":
            return max(0, len(clean_order) - offset)
        return len(clean_order)
    if position == "up":
        return max(0, current_idx - offset)
    return min(len(clean_order), current_idx + offset)


def move_items(
    plan: PlanModel,
    issue_ids: list[str],
    position: str,
    target: str | None = None,
    offset: int | None = None,
) -> int:
    """Move issue IDs to a position in queue_order. Returns count moved."""
    ensure_plan_defaults(plan)

    # Triage stage IDs are workflow-managed and cannot be manually reordered.
    from desloppify.engine._plan.constants import TRIAGE_IDS

    protected_ids = protected_review_issue_ids(plan)
    issue_ids = [
        fid for fid in issue_ids if fid not in TRIAGE_IDS and fid not in protected_ids
    ]
    if not issue_ids:
        return 0

    order: list[str] = plan["queue_order"]

    # Remove from skipped if present.
    skipped: dict[str, SkipEntry] = plan.get("skipped", {})
    for fid in issue_ids:
        skipped.pop(fid, None)

    # Remove from current position in order.
    for fid in issue_ids:
        if fid in order:
            order.remove(fid)

    # Resolve insertion point.
    idx = _resolve_position(order, position, target, offset, issue_ids)

    # Insert in original order.
    for i, fid in enumerate(issue_ids):
        order.insert(idx + i, fid)

    # Track user-promoted IDs only when explicitly moved to the front.
    # Moving to bottom/down/after should not create a promotion barrier.
    if position == "top":
        add_promoted_ids(plan, issue_ids)

    return len(issue_ids)


__all__ = ["move_items", "_remove_id_from_lists"]
