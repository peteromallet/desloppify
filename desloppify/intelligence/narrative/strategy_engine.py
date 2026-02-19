"""Execution strategy engine for narrative lanes and parallelization hints."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from desloppify.intelligence.narrative._constants import (
    _DETECTOR_CASCADE,
    STRUCTURAL_MERGE,
)


def open_files_by_detector(findings: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    """Collect file sets of open findings by detector."""
    by_detector: dict[str, set[str]] = {}
    for finding in findings.values():
        if finding["status"] != "open":
            continue
        detector = finding.get("detector", "unknown")
        if detector in STRUCTURAL_MERGE:
            detector = "structural"
        file_path = finding.get("file", "")
        if not file_path:
            by_detector.setdefault(detector, set())
            continue
        by_detector.setdefault(detector, set()).add(file_path)
    return by_detector


def compute_fixer_leverage(
    by_detector: dict[str, int],
    actions: list[dict[str, Any]],
    phase: str,
    _lang: str | None,
) -> dict[str, float | int | str]:
    """Estimate how much value automated fixers would deliver."""
    auto_fixable = sum(
        action.get("count", 0) for action in actions if action.get("type") == "auto_fix"
    )
    total = sum(by_detector.values())
    coverage = auto_fixable / total if total > 0 else 0.0
    total_impact = sum(action.get("impact", 0) for action in actions)
    auto_impact = sum(
        action.get("impact", 0)
        for action in actions
        if action.get("type") == "auto_fix"
    )
    impact_ratio = auto_impact / total_impact if total_impact > 0 else 0.0

    if coverage == 0:
        recommendation = "none"
    elif coverage > 0.4 or impact_ratio > 0.3:
        recommendation = "strong"
    elif phase in ("first_scan", "stagnation", "regression") and coverage > 0.15:
        recommendation = "strong"
    elif coverage > 0.1:
        recommendation = "moderate"
    else:
        recommendation = "none"

    return {
        "auto_fixable_count": auto_fixable,
        "total_count": total,
        "coverage": round(coverage, 3),
        "impact_ratio": round(impact_ratio, 3),
        "recommendation": recommendation,
    }


def _cleanup_lane_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cascade_rank = {detector: idx for idx, detector in enumerate(_DETECTOR_CASCADE)}

    def sort_key(action: dict[str, Any]) -> tuple[int, float]:
        detector = action.get("detector", "")
        return (cascade_rank.get(detector, 99), -action.get("impact", 0))

    return sorted(actions, key=sort_key)


def _files_for_actions(
    actions: Iterable[dict[str, Any]], files_by_detector: dict[str, set[str]]
) -> set[str]:
    files: set[str] = set()
    for action in actions:
        detector = action.get("detector")
        if detector and detector in files_by_detector:
            files |= files_by_detector[detector]
    return files


def _group_by_file_overlap(
    action_files: list[tuple[dict[str, Any], set[str]]],
) -> list[list[tuple[dict[str, Any], set[str]]]]:
    """Group actions whose file sets overlap using union-find."""
    item_count = len(action_files)
    if item_count == 0:
        return []

    parent = list(range(item_count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[left_root] = right_root

    for left in range(item_count):
        for right in range(left + 1, item_count):
            if action_files[left][1] & action_files[right][1]:
                union(left, right)

    grouped_indices: dict[int, list[int]] = {}
    for index in range(item_count):
        grouped_indices.setdefault(find(index), []).append(index)

    return [
        [action_files[index] for index in indices]
        for indices in grouped_indices.values()
    ]


def _refactor_lanes(
    refactor_actions: list[dict[str, Any]],
    files_by_detector: dict[str, set[str]],
) -> dict[str, dict[str, Any]]:
    """Split refactor work into independent lanes by file overlap."""
    lanes: dict[str, dict] = {}
    action_files = [
        (action, files_by_detector.get(action.get("detector"), set()))
        for action in refactor_actions
    ]

    test_coverage_actions = [
        (action, files)
        for action, files in action_files
        if action.get("detector") == "test_coverage"
    ]
    other_actions = [
        (action, files)
        for action, files in action_files
        if action.get("detector") != "test_coverage"
    ]

    groups = _group_by_file_overlap(other_actions)
    for index, group in enumerate(groups):
        lane_name = f"refactor_{index}" if len(groups) > 1 else "refactor"
        lanes[lane_name] = {
            "actions": [action["priority"] for action, _ in group],
            "file_count": len(
                _files_for_actions((action for action, _ in group), files_by_detector)
            ),
            "total_impact": round(
                sum(action.get("impact", 0) for action, _ in group), 1
            ),
            "automation": "manual",
            "run_first": False,
        }

    if test_coverage_actions:
        lanes["test_coverage"] = {
            "actions": [action["priority"] for action, _ in test_coverage_actions],
            "file_count": len(
                _files_for_actions(
                    (action for action, _ in test_coverage_actions), files_by_detector
                )
            ),
            "total_impact": round(
                sum(action.get("impact", 0) for action, _ in test_coverage_actions), 1
            ),
            "automation": "manual",
            "run_first": False,
        }

    return lanes


def compute_lanes(
    actions: list[dict[str, Any]],
    files_by_detector: dict[str, set[str]],
) -> dict[str, dict[str, Any]]:
    """Partition actions into parallelizable work lanes."""
    lanes: dict[str, dict] = {}

    cleanup_actions = _cleanup_lane_actions(
        [action for action in actions if action.get("type") == "auto_fix"]
    )
    reorganize_actions = [
        action for action in actions if action.get("type") == "reorganize"
    ]
    debt_actions = [action for action in actions if action.get("type") == "debt_review"]
    refactor_actions = [
        action
        for action in actions
        if action.get("type") not in {"auto_fix", "reorganize", "debt_review"}
    ]

    if cleanup_actions:
        cleanup_files = _files_for_actions(cleanup_actions, files_by_detector)
        lanes["cleanup"] = {
            "actions": [action["priority"] for action in cleanup_actions],
            "file_count": len(cleanup_files),
            "total_impact": round(
                sum(action.get("impact", 0) for action in cleanup_actions), 1
            ),
            "automation": "full",
            "run_first": False,
        }

    if reorganize_actions:
        lanes["restructure"] = {
            "actions": [action["priority"] for action in reorganize_actions],
            "file_count": len(
                _files_for_actions(reorganize_actions, files_by_detector)
            ),
            "total_impact": round(
                sum(action.get("impact", 0) for action in reorganize_actions), 1
            ),
            "automation": "manual",
            "run_first": False,
        }

    if refactor_actions:
        lanes.update(_refactor_lanes(refactor_actions, files_by_detector))

    if debt_actions:
        lanes["debt_review"] = {
            "actions": [action["priority"] for action in debt_actions],
            "file_count": 0,
            "total_impact": 0.0,
            "automation": "manual",
            "run_first": False,
        }

    if "cleanup" in lanes:
        cleanup_files = _files_for_actions(
            (
                action
                for action in actions
                if action["priority"] in lanes["cleanup"]["actions"]
            ),
            files_by_detector,
        )
        for lane_name, lane in lanes.items():
            if lane_name == "cleanup":
                continue
            lane_files = _files_for_actions(
                (action for action in actions if action["priority"] in lane["actions"]),
                files_by_detector,
            )
            if cleanup_files & lane_files:
                lanes["cleanup"]["run_first"] = True
                break

    return lanes


def _significant_lane(lane_name: str, lane: dict[str, Any]) -> bool:
    if lane_name == "debt_review" or lane.get("run_first"):
        return False
    return lane.get("file_count", 0) >= 5 or lane.get("total_impact", 0) >= 1.0


def compute_strategy_hint(
    fixer_leverage: dict[str, Any],
    lanes: dict[str, dict[str, Any]],
    can_parallelize: bool,
    phase: str,
) -> str:
    """Generate one- or two-sentence execution strategy guidance."""
    recommendation = fixer_leverage.get("recommendation", "none")
    coverage_pct = round(fixer_leverage.get("coverage", 0) * 100)
    lane_count = sum(
        1
        for lane_name, lane in lanes.items()
        if lane_name != "debt_review" and not lane.get("run_first")
    )

    if recommendation == "strong" and can_parallelize:
        return (
            f"Run fixers first — they cover {coverage_pct}% of findings. "
            f"Then {lane_count} independent workstreams, safe to parallelize. "
            "Rescan after each phase to verify."
        )
    if recommendation == "strong":
        return (
            f"Run fixers first — they cover {coverage_pct}% of findings. "
            "Then rescan to verify."
        )
    if can_parallelize:
        return (
            f"{lane_count} independent workstreams, safe to parallelize. "
            "Rescan after each phase to verify."
        )
    if phase == "maintenance":
        return "Maintenance mode — address new findings as they appear."
    if phase == "stagnation":
        return "Try a different dimension to break the plateau."
    return "Work through actions in priority order. Rescan after each fix to track progress."


def compute_strategy(
    findings: dict[str, dict[str, Any]],
    by_detector: dict[str, int],
    actions: list[dict[str, Any]],
    phase: str,
    lang: str | None,
) -> dict[str, Any]:
    """Orchestrate strategy computation and annotate actions with lanes."""
    files_by_detector = open_files_by_detector(findings)
    fixer_leverage = compute_fixer_leverage(by_detector, actions, phase, lang)
    lanes = compute_lanes(actions, files_by_detector)

    action_lane: dict[int, str] = {}
    for lane_name, lane in lanes.items():
        for priority in lane["actions"]:
            action_lane[priority] = lane_name
    for action in actions:
        action["lane"] = action_lane.get(action["priority"])

    significant_non_blocked = [
        (lane_name, lane)
        for lane_name, lane in lanes.items()
        if _significant_lane(lane_name, lane)
    ]
    can_parallelize = len(significant_non_blocked) >= 2

    hint = compute_strategy_hint(fixer_leverage, lanes, can_parallelize, phase)
    review_action = next(
        (action for action in actions if action.get("type") == "issue_queue"), None
    )
    if review_action:
        hint += f" Review: {review_action['count']} finding(s) — `desloppify issues`."

    return {
        "fixer_leverage": fixer_leverage,
        "lanes": {name: {**lane} for name, lane in lanes.items()},
        "can_parallelize": can_parallelize,
        "hint": hint,
    }
