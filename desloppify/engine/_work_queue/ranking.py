"""Ranking and grouping helpers for work queue selection."""

from __future__ import annotations

import logging
from typing import Any, cast

from desloppify.base.registry import DETECTORS
from desloppify.engine._scoring.results.health import compute_health_breakdown
from desloppify.engine._scoring.results.impact import get_dimension_for_detector
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.helpers import (
    ACTION_TYPE_PRIORITY,
    detail_dict,
    is_review_issue,
    is_subjective_issue,
    workflow_stage_name,
    primary_command_for_issue,
    review_issue_weight,
    scope_matches,
    slugify,
    status_matches,
    supported_fixers_for_item,
)
from desloppify.engine._work_queue.ranking_output import (
    group_queue_items,
    item_explain,
    subjective_score_value,
)
from desloppify.engine._work_queue.synthetic import subjective_strict_scores
from desloppify.engine._work_queue.types import WorkQueueItem
from desloppify.engine.planning.helpers import CONFIDENCE_ORDER
from desloppify.state import path_scoped_issues

logger = logging.getLogger(__name__)

# Plan-aware sort tiers (item_sort_key)
_TIER_PLANNED = 0   # Items with explicit plan position
_TIER_EXISTING = 1  # Known items, natural ranking
_TIER_NEW = 2       # Newly discovered items

# Natural ranking groups (_natural_sort_key)
_RANK_INITIAL_REVIEW = -3  # Unassessed subjective dimensions
_RANK_WORKFLOW = -2         # Score checkpoints, create-plan
_RANK_TRIAGE_STAGE = -1     # Epic triage workflow stages
_RANK_CLUSTER = 0           # Auto-clustered issues
_RANK_ISSUE = 1           # Individual issues + assessed subjective

_TRIAGE_STAGE_ORDER = {
    "observe": 0,
    "reflect": 1,
    "organize": 2,
    "commit": 3,
}


def _workflow_stage_index(item: WorkQueueItem) -> int:
    raw_index = item.get("stage_index")
    if raw_index is not None:
        try:
            return int(raw_index)
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid workflow stage index %r: %s", raw_index, exc)
    return _TRIAGE_STAGE_ORDER.get(workflow_stage_name(item).lower(), 0)


def enrich_with_impact(
    items: list[WorkQueueItem], dimension_scores: dict[str, Any]
) -> None:
    """Stamp ``estimated_impact`` on each item based on dimension-level headroom.

    Impact = ``overall_per_point * headroom`` where headroom = ``100 - score``.
    Items in dimensions with more score headroom sort first.
    """
    if not dimension_scores:
        for item in items:
            item["estimated_impact"] = 0.0
        return

    breakdown = compute_health_breakdown(dimension_scores)
    entries = breakdown.get("entries", [])

    # Build lookup: normalized dimension name -> {per_point, headroom}
    dim_impact: dict[str, dict[str, float]] = {}
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        per_point = float(entry.get("overall_per_point", 0.0))
        score = float(entry.get("score", 0.0))
        headroom = 100.0 - score
        dim_impact[name.lower()] = {"per_point": per_point, "headroom": headroom}

    for item in items:
        impact = _compute_item_impact(item, dim_impact, get_dimension_for_detector)
        item["estimated_impact"] = impact


def _compute_item_impact(
    item: WorkQueueItem,
    dim_impact: dict[str, dict[str, float]],
    get_dimension_for_detector,
) -> float:
    """Compute impact value for a single queue item."""
    kind = item.get("kind", "issue")

    # Subjective items (synthetic dimensions or subjective issues):
    # look up by detail.dimension_name
    if kind == "subjective_dimension" or item.get("is_subjective"):
        dim_name = detail_dict(item).get("dimension_name", "")
        entry = dim_impact.get(dim_name.lower())
        if entry:
            return entry["per_point"] * entry["headroom"]
        return 0.0

    # Mechanical issues: use detector -> dimension mapping
    detector = item.get("detector", "")
    if detector:
        dimension = get_dimension_for_detector(detector)
        if dimension:
            entry = dim_impact.get(dimension.name.lower())
            if entry:
                return entry["per_point"] * entry["headroom"]

    return 0.0


def build_issue_items(
    state: StateModel,
    *,
    scan_path: str | None,
    status_filter: str,
    scope: str | None,
    chronic: bool,
) -> list[WorkQueueItem]:
    scoped = path_scoped_issues(state.get("issues", {}), scan_path)
    subjective_scores = subjective_strict_scores(state)
    out: list[WorkQueueItem] = []

    for issue_id, issue in scoped.items():
        if issue.get("suppressed"):
            continue
        if not status_matches(issue.get("status", "open"), status_filter):
            continue
        if chronic and not (
            issue.get("status") == "open" and issue.get("reopen_count", 0) >= 2
        ):
            continue

        # Evidence-only: skip issues below standalone confidence threshold
        detector = issue.get("detector", "")
        meta = DETECTORS.get(detector)
        if meta and meta.standalone_threshold:
            threshold_rank = CONFIDENCE_ORDER.get(meta.standalone_threshold, 9)
            issue_rank = CONFIDENCE_ORDER.get(issue.get("confidence", "low"), 9)
            if issue_rank > threshold_rank:
                continue

        item = cast(WorkQueueItem, dict(issue))
        item["id"] = issue_id
        item["kind"] = "issue"
        item["is_review"] = is_review_issue(item)
        item["is_subjective"] = is_subjective_issue(item)
        item["review_weight"] = (
            review_issue_weight(item) if item["is_review"] else None
        )
        subjective_score = None
        if item["is_subjective"]:
            detail = detail_dict(issue)
            dim_name = detail.get("dimension_name", "")
            dim_key = detail.get("dimension", "") or slugify(dim_name)
            subjective_score = subjective_scores.get(
                dim_key, subjective_scores.get(dim_name.lower(), 100.0)
            )
        item["subjective_score"] = subjective_score
        supported_fixers = supported_fixers_for_item(state, item)
        item["primary_command"] = primary_command_for_issue(
            item,
            supported_fixers=supported_fixers,
        )

        if not scope_matches(item, scope):
            continue
        out.append(item)

    return out


def _natural_sort_key(item: WorkQueueItem) -> tuple:
    """Compute natural (non-plan-aware) ranking for queue items."""
    kind = item.get("kind", "issue")

    # Initial-review subjective items: highest priority
    if kind == "subjective_dimension" and item.get("initial_review"):
        return (_RANK_INITIAL_REVIEW, 0, subjective_score_value(item), item.get("id", ""))

    # Triage stage items: stage order, blocked after unblocked
    if kind == "workflow_stage":
        blocked_penalty = 1 if item.get("is_blocked") else 0
        stage_index = _workflow_stage_index(item)
        return (_RANK_TRIAGE_STAGE, blocked_penalty, stage_index, item.get("id", ""))

    # Workflow action items (e.g. create-plan)
    if kind == "workflow_action":
        return (_RANK_WORKFLOW, 0, 0, item.get("id", ""))

    if kind == "cluster":
        # Clusters sort before individual issues, ordered by action type
        action_pri = ACTION_TYPE_PRIORITY.get(
            item.get("action_type", "manual_fix"), 3
        )
        return (
            _RANK_CLUSTER,
            action_pri,
            -int(item.get("member_count", 0)),
            item.get("id", ""),
        )

    impact = item.get("estimated_impact", 0.0)

    if kind == "subjective_dimension" or item.get("is_subjective"):
        return (
            _RANK_ISSUE,
            -impact,
            subjective_score_value(item),
            0.0,
            0,
            item.get("id", ""),
        )

    detail = detail_dict(item)
    review_weight = float(item.get("review_weight", 0.0) or 0.0)
    return (
        _RANK_ISSUE,
        -impact,
        CONFIDENCE_ORDER.get(item.get("confidence", "low"), 9),
        -review_weight,
        -int(detail.get("count", 0) or 0),
        item.get("id", ""),
    )


def item_sort_key(item: WorkQueueItem) -> tuple:
    """Unified sort key: plan position first, then natural ranking.

    When ``_plan_position`` is stamped (by :func:`stamp_plan_sort_keys`),
    planned items sort first in plan order, then existing items by natural
    ranking, then newly-discovered items by natural ranking.

    When no plan fields are stamped, falls back to pure natural ranking.
    """
    plan_pos = item.get("_plan_position")

    if plan_pos is not None:
        kind = item.get("kind", "issue")
        # Triage stages: even when explicitly planned, maintain the
        # blocked-before-unblocked invariant for correctness.
        if kind == "workflow_stage":
            blocked = 1 if item.get("is_blocked") else 0
            stage_idx = _workflow_stage_index(item)
            return (_TIER_PLANNED, plan_pos, blocked, stage_idx, item.get("id", ""))
        return (_TIER_PLANNED, 0, plan_pos, item.get("id", ""))

    is_new = item.get("_is_new", False)
    group = _TIER_NEW if is_new else _TIER_EXISTING
    return (group, *_natural_sort_key(item))


__all__ = [
    "build_issue_items",
    "enrich_with_impact",
    "item_explain",
    "item_sort_key",
    "subjective_score_value",
    "group_queue_items",
]
