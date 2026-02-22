"""Ranking and grouping helpers for work queue selection."""

from __future__ import annotations

from desloppify.engine.planning.common import CONFIDENCE_ORDER
from desloppify.state import path_scoped_findings
from desloppify.engine._work_queue.helpers import (
    is_review_finding,
    is_subjective_finding,
    primary_command_for_finding,
    review_finding_weight,
    scope_matches,
    slugify,
    status_matches,
    subjective_strict_scores,
    supported_fixers_for_item,
)


def subjective_score_value(item: dict) -> float:
    if item.get("kind") == "subjective_dimension":
        detail = item.get("detail", {})
        return float(detail.get("strict_score", item.get("subjective_score", 100.0)))
    return float(item.get("subjective_score", 100.0))


def build_finding_items(
    state: dict,
    *,
    scan_path: str | None,
    status_filter: str,
    scope: str | None,
    chronic: bool,
) -> list[dict]:
    scoped = path_scoped_findings(state.get("findings", {}), scan_path)
    subjective_scores = subjective_strict_scores(state)
    out: list[dict] = []

    for finding_id, finding in scoped.items():
        if finding.get("suppressed"):
            continue
        if not status_matches(finding.get("status", "open"), status_filter):
            continue
        if chronic and not (
            finding.get("status") == "open" and finding.get("reopen_count", 0) >= 2
        ):
            continue

        item = dict(finding)
        item["id"] = finding_id
        item["kind"] = "finding"
        item["is_review"] = is_review_finding(item)
        item["is_subjective"] = is_subjective_finding(item)
        item["effective_tier"] = (
            1
            if item["is_review"]
            else (4 if item["is_subjective"] else int(finding.get("tier", 3)))
        )
        item["review_weight"] = (
            review_finding_weight(item) if item["is_review"] else None
        )
        subjective_score = None
        if item["is_subjective"]:
            detail = finding.get("detail", {})
            dim_name = detail.get("dimension_name", "")
            dim_key = detail.get("dimension", "") or slugify(dim_name)
            subjective_score = subjective_scores.get(
                dim_key, subjective_scores.get(dim_name.lower(), 100.0)
            )
        item["subjective_score"] = subjective_score
        supported_fixers = supported_fixers_for_item(state, item)
        item["primary_command"] = primary_command_for_finding(
            item,
            supported_fixers=supported_fixers,
        )

        if not scope_matches(item, scope):
            continue
        out.append(item)

    return out


def item_sort_key(item: dict) -> tuple:
    if item.get("is_review"):
        # Review queue is always highest priority in `next`.
        return (
            0,
            -float(item.get("review_weight", 0.0) or 0.0),
            CONFIDENCE_ORDER.get(item.get("confidence", "low"), 9),
            item.get("id", ""),
        )

    if item.get("kind") == "subjective_dimension" or item.get("is_subjective"):
        return (
            int(item.get("effective_tier", 4)),
            1,  # Subjective items sort after mechanical items within T4.
            subjective_score_value(item),
            item.get("id", ""),
        )

    detail = item.get("detail", {})
    return (
        int(item.get("effective_tier", item.get("tier", 3))),
        0,
        CONFIDENCE_ORDER.get(item.get("confidence", "low"), 9),
        -int(detail.get("count", 0) or 0),
        item.get("id", ""),
    )


def item_explain(item: dict) -> dict:
    effective_tier = int(item.get("effective_tier", item.get("tier", 3)))
    if item.get("is_review"):
        return {
            "kind": "finding",
            "effective_tier": effective_tier,
            "confidence": item.get("confidence", "low"),
            "review_weight": float(item.get("review_weight", 0.0) or 0.0),
            "id": item.get("id", ""),
            "policy": (
                "Open review findings are always ranked first and shown before "
                "mechanical or synthetic subjective queue items."
            ),
            "ranking_factors": [
                "review_priority",
                "review_weight desc",
                "confidence asc",
                "id asc",
            ],
        }

    if item.get("kind") == "subjective_dimension":
        return {
            "kind": "subjective_dimension",
            "effective_tier": effective_tier,
            "subjective_score": subjective_score_value(item),
            "policy": (
                "Subjective dimensions are always queued as T4 and do not outrank "
                "mechanical T1/T2/T3 items."
            ),
            "ranking_factors": ["tier asc", "subjective_score asc", "id asc"],
        }

    detail = item.get("detail", {})
    confidence = item.get("confidence", "low")
    is_subjective = bool(item.get("is_subjective"))
    ranking_factors = (
        ["tier fixed to T4", "subjective_score asc", "id asc"]
        if is_subjective
        else ["tier asc", "confidence asc", "count desc", "id asc"]
    )
    explain = {
        "kind": "finding",
        "effective_tier": effective_tier,
        "confidence": confidence,
        "confidence_rank": CONFIDENCE_ORDER.get(confidence, 9),
        "count": int(detail.get("count", 0) or 0),
        "id": item.get("id", ""),
        "ranking_factors": ranking_factors,
    }
    if is_subjective:
        explain["policy"] = (
            "Subjective findings are forced to T4 and do not outrank "
            "mechanical T1/T2/T3 items."
        )
        explain["subjective_score"] = subjective_score_value(item)
    return explain


def tier_counts(items: list[dict]) -> dict[int, int]:
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for item in items:
        tier = int(item.get("effective_tier", item.get("tier", 3)))
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def choose_fallback_tier(requested_tier: int, counts: dict[int, int]) -> int | None:
    available = [tier for tier, count in counts.items() if count > 0]
    if not available:
        return None
    return min(available, key=lambda tier: (abs(tier - requested_tier), tier))


def group_queue_items(items: list[dict], group: str) -> dict[str, list[dict]]:
    """Group queue items for alternate output modes."""
    grouped: dict[str, list[dict]] = {}
    for item in items:
        if group == "file":
            key = item.get("file", "")
        elif group == "detector":
            key = item.get("detector", "")
        elif group == "tier":
            key = f"T{int(item.get('effective_tier', item.get('tier', 3)))}"
        else:
            key = "items"
        grouped.setdefault(key, []).append(item)
    return grouped


__all__ = [
    "build_finding_items",
    "choose_fallback_tier",
    "item_explain",
    "item_sort_key",
    "tier_counts",
    "subjective_score_value",
    "group_queue_items",
]
