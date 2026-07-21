"""Helpers for tracking user-promoted queue IDs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


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
    for issue_id in issue_ids:
        if issue_id in existing:
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


def has_promoted_execution_candidate(
    plan: dict[str, Any] | None,
    candidate_ids: Iterable[str],
) -> bool:
    """Return whether a live execution candidate was explicitly promoted."""
    if not isinstance(plan, dict):
        return False
    promoted = plan.get("promoted_ids")
    if not isinstance(promoted, list) or not promoted:
        return False
    candidates = set(candidate_ids)
    return any(issue_id in candidates for issue_id in promoted)


__all__ = [
    "add_promoted_ids",
    "has_promoted_execution_candidate",
    "promoted_insertion_index",
    "prune_promoted_ids",
]
