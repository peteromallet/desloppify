"""Helpers for tracking user-promoted queue IDs."""

from __future__ import annotations

from typing import Any

from desloppify.engine._plan.triage.protection import protected_review_issue_ids


def _promoted_ids(plan: dict[str, Any]) -> list[str]:
    promoted = plan.get("promoted_ids")
    if isinstance(promoted, list):
        return promoted
    promoted = []
    plan["promoted_ids"] = promoted
    return promoted


def add_promoted_ids(plan: dict[str, Any], issue_ids: list[str]) -> None:
    """Append issue IDs to promoted_ids preserving existing order."""
    promoted = _promoted_ids(plan)
    existing = set(promoted)
    protected_ids = protected_review_issue_ids(plan)
    for issue_id in issue_ids:
        if issue_id in existing or issue_id in protected_ids:
            continue
        promoted.append(issue_id)
        existing.add(issue_id)


def prune_promoted_ids(plan: dict[str, Any], issue_ids: set[str] | list[str]) -> None:
    """Remove issue IDs from promoted_ids if present."""
    remove_set = set(issue_ids)
    if not remove_set:
        return
    promoted = _promoted_ids(plan)
    plan["promoted_ids"] = [issue_id for issue_id in promoted if issue_id not in remove_set]


def promoted_insertion_index(order: list[str], plan: dict[str, Any]) -> int:
    """Return insertion index immediately after the last promoted item."""
    promoted = set(_promoted_ids(plan))
    if not promoted:
        return 0
    last_idx = -1
    for idx, issue_id in enumerate(order):
        if issue_id in promoted:
            last_idx = idx
    return last_idx + 1 if last_idx >= 0 else 0


__all__ = [
    "add_promoted_ids",
    "promoted_insertion_index",
    "prune_promoted_ids",
]
