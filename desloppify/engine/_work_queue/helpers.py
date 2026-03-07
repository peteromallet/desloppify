"""Predicates and small utilities for work queue items."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any

from desloppify.base.enums import issue_status_tokens
from desloppify.base.registry import ACTION_TYPE_PRIORITY, DETECTORS
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.types import WorkQueueItem

ALL_STATUSES = set(issue_status_tokens(include_all=True))
ATTEST_EXAMPLE = (
    "I have actually [DESCRIBE THE CONCRETE CHANGE YOU MADE] "
    "and I am not gaming the score by resolving without fixing."
)


def detail_dict(item: WorkQueueItem | dict[str, Any]) -> dict[str, Any]:
    """Return issue detail as a dict; tolerate legacy/non-dict payloads."""
    detail = item.get("detail")
    return detail if isinstance(detail, dict) else {}


def status_matches(item_status: str, status_filter: str) -> bool:
    return status_filter == "all" or item_status == status_filter


def is_subjective_issue(item: WorkQueueItem | dict[str, Any]) -> bool:
    detector = item.get("detector")
    if detector in {"subjective_assessment"}:
        return True
    if detector == "holistic_review":
        return True
    return False


def is_review_issue(item: WorkQueueItem | dict[str, Any]) -> bool:
    return item.get("detector") == "review"


def is_subjective_queue_item(item: WorkQueueItem | dict[str, Any]) -> bool:
    """True for subjective work items, including collapsed subjective clusters."""
    if item.get("kind") == "subjective_dimension":
        return True
    if item.get("kind") == "cluster":
        members = item.get("members", [])
        return bool(members) and all(
            m.get("kind") == "subjective_dimension" for m in members
        )
    return False


def review_issue_weight(item: WorkQueueItem | dict[str, Any]) -> float:
    """Return review issue weight aligned with issues list ordering."""
    confidence = str(item.get("confidence", "low")).lower()
    weight_by_confidence = {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.3,
    }
    weight = weight_by_confidence.get(confidence, 0.3)
    if detail_dict(item).get("holistic"):
        weight *= 10.0
    return float(weight)


def scope_matches(item: WorkQueueItem | dict[str, Any], scope: str | None) -> bool:
    """Apply show-style pattern matching against a queue item."""
    if not scope:
        return True

    item_id = item.get("id", "")
    detector = item.get("detector", "")
    filepath = item.get("file", "")
    summary = item.get("summary", "")
    dimension = detail_dict(item).get("dimension_name", "")
    kind = item.get("kind", "")

    if "*" in scope:
        return any(
            fnmatch(candidate, scope)
            for candidate in (item_id, filepath, detector, dimension, summary)
        )

    if "::" in scope:
        return item_id.startswith(scope)

    lowered = scope.lower()
    if kind == "subjective_dimension":
        return (
            lowered in item_id.lower()
            or lowered in dimension.lower()
            or lowered in summary.lower()
        )

    # Hash suffix: 8+ hex chars matches the tail segment of a issue ID.
    if len(lowered) >= 8 and re.fullmatch(r"[0-9a-f]+", lowered):
        return item_id.lower().endswith("::" + lowered)

    return (
        detector == scope
        or filepath == scope
        or filepath.startswith(scope.rstrip("/") + "/")
    )


def workflow_stage_name(item: WorkQueueItem | dict[str, Any]) -> str:
    """Resolve the triage stage name from an item, with fallbacks."""
    stage_name = str(item.get("stage_name", "")).strip()
    if stage_name:
        return stage_name

    stage_name = str(detail_dict(item).get("stage", "")).strip()
    if stage_name:
        return stage_name

    item_id = str(item.get("id", "")).strip()
    if item_id.startswith("triage::"):
        return item_id.split("::", 1)[1]
    return ""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


def supported_fixers_for_item(
    state: StateModel, item: WorkQueueItem
) -> set[str] | None:
    """Return supported fixers for an item's language when known."""
    lang = str(item.get("lang", "") or "").strip()
    if not lang:
        return None

    caps_obj = state.get("lang_capabilities")
    if not isinstance(caps_obj, dict):
        return None
    lang_caps_obj = caps_obj.get(lang)
    if not isinstance(lang_caps_obj, dict):
        return None

    fixers = lang_caps_obj.get("fixers")
    if not isinstance(fixers, list):
        return None
    return {fixer for fixer in fixers if isinstance(fixer, str)}


def primary_command_for_issue(
    item: WorkQueueItem, *, supported_fixers: set[str] | None = None
) -> str:
    detector = item.get("detector", "")
    meta = DETECTORS.get(detector)
    if meta and meta.action_type == "auto_fix" and meta.fixers:
        available_fixers = [
            fixer
            for fixer in meta.fixers
            if supported_fixers is not None and fixer in supported_fixers
        ]
        if available_fixers:
            return f"desloppify autofix {available_fixers[0]} --dry-run"
    if detector == "subjective_review":
        from desloppify.intelligence.integrity import (
            is_holistic_subjective_issue,  # cycle-break: helpers.py ↔ integrity.py
        )

        if is_holistic_subjective_issue(item):
            return "desloppify review --prepare"
        return "desloppify show subjective"
    return f'desloppify plan resolve "{item.get("id", "")}" --note "<what you did>" --confirm'


__all__ = [
    "ALL_STATUSES",
    "ATTEST_EXAMPLE",
    "detail_dict",
    "is_review_issue",
    "is_subjective_issue",
    "is_subjective_queue_item",
    "primary_command_for_issue",
    "review_issue_weight",
    "scope_matches",
    "slugify",
    "status_matches",
    "supported_fixers_for_item",
    "workflow_stage_name",
]
