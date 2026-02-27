"""Action computation engine used by narrative query generation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from desloppify.intelligence.narrative._constants import DETECTOR_TOOLS
from desloppify.intelligence.narrative.action_models import ActionContext, ActionItem
from desloppify.languages import get_lang
from desloppify.scoring import (
    compute_score_impact,
    get_dimension_for_detector,
    merge_potentials,
)
from desloppify.state import StateModel


def supported_fixers(state: StateModel, lang: str | None) -> set[str] | None:
    """Return supported fixers for the active language, or None when unknown."""
    if not lang:
        return None

    capabilities = state.get("lang_capabilities", {}).get(lang, {})
    fixers = capabilities.get("fixers")
    if isinstance(fixers, list):
        return {fixer for fixer in fixers if isinstance(fixer, str)}

    try:
        return set(get_lang(lang).fixers.keys())
    except (ImportError, ValueError):
        return None


def _impact_calculator(
    dimension_scores: dict[str, dict[str, Any]],
    state: StateModel,
) -> Callable[[str, int], float]:
    """Build an impact estimator closure keyed by detector and count."""
    merged_potentials = merge_potentials(state.get("potentials", {}))
    if not merged_potentials or not dimension_scores:
        return lambda _detector, _count: 0.0

    scoring_view = {
        name: {
            "score": values["score"],
            "tier": values.get("tier", 3),
            "detectors": values.get("detectors", {}),
        }
        for name, values in dimension_scores.items()
    }

    def _impact(detector: str, count: int) -> float:
        return compute_score_impact(
            scoring_view, merged_potentials, detector, count
        )

    return _impact


def _dimension_name(detector: str) -> str:
    """Resolve user-facing dimension name for a detector."""
    dimension = get_dimension_for_detector(detector)
    return dimension.name if dimension else "Unknown"


def _fixer_has_applicable_findings(
    state: StateModel, detector: str, fixer_name: str
) -> bool:
    """For the smells detector, verify the fixer has matching open findings.

    The smells detector aggregates many smell types but each fixer only handles
    one sub-type (e.g. ``dead-useeffect`` only fixes ``dead_useeffect`` smells).
    Without this check, a React-specific fixer can be suggested to projects that
    have no React code at all, producing a confusing "Found 0 candidates" result.

    For all other detectors the fixer is considered universally applicable.
    """
    if detector != "smells":
        return True
    smell_id = fixer_name.replace("-", "_")
    return any(
        f.get("status") == "open"
        and not f.get("suppressed")
        and f.get("detector") == "smells"
        and f.get("detail", {}).get("smell_id") == smell_id
        for f in state.get("findings", {}).values()
    )


def _append_auto_fix_actions(
    actions: list[ActionItem],
    by_detector: dict[str, int],
    supported: set[str] | None,
    impact_for: Callable[[str, int], float],
    state: StateModel,
) -> None:
    """Append auto-fix/manual-fix actions for detectors with auto fixers."""
    for detector, tool_info in DETECTOR_TOOLS.items():
        if tool_info["action_type"] != "auto_fix":
            continue
        count = by_detector.get(detector, 0)
        if count == 0:
            continue

        impact = round(impact_for(detector, count), 1)
        available_fixers = [
            fixer
            for fixer in tool_info["fixers"]
            if (supported is None or fixer in supported)
            and _fixer_has_applicable_findings(state, detector, fixer)
        ]
        if not available_fixers:
            actions.append(
                {
                    "type": "manual_fix",
                    "detector": detector,
                    "count": count,
                    "description": (
                        f"{count} {detector} findings — inspect with "
                        f"`desloppify next` and fix manually"
                    ),
                    "command": f"desloppify show {detector} --status open",
                    "impact": impact,
                    "dimension": _dimension_name(detector),
                }
            )
            continue

        fixer = available_fixers[0]
        actions.append(
            {
                "type": "auto_fix",
                "detector": detector,
                "count": count,
                "description": (
                    f"{count} {detector} findings — run "
                    f"`desloppify fix {fixer} --dry-run` to preview, then apply"
                ),
                "command": f"desloppify fix {fixer} --dry-run",
                "impact": impact,
                "dimension": _dimension_name(detector),
            }
        )


def _append_reorganize_actions(
    actions: list[ActionItem],
    by_detector: dict[str, int],
    impact_for: Callable[[str, int], float],
) -> None:
    """Append structure/move oriented actions."""
    for detector, tool_info in DETECTOR_TOOLS.items():
        if tool_info["action_type"] != "reorganize":
            continue
        count = by_detector.get(detector, 0)
        if count == 0:
            continue

        guidance = tool_info.get("guidance", "restructure with move")
        actions.append(
            {
                "type": "reorganize",
                "detector": detector,
                "count": count,
                "description": f"{count} {detector} findings — {guidance}",
                "command": f"desloppify show {detector} --status open",
                "impact": round(impact_for(detector, count), 1),
                "dimension": _dimension_name(detector),
            }
        )


def _build_refactor_entry(
    detector: str,
    tool_info: dict[str, Any],
    count: int,
    impact_for: Callable[[str, int], float],
) -> ActionItem:
    """Build one refactor/manual action row."""
    guidance = tool_info.get("guidance", "manual fix")
    adjusted_info = {**tool_info, "guidance": guidance}

    if detector == "subjective_review":
        command = "desloppify review --prepare"
        description = f"{count} files need design review — run holistic review to refresh subjective scores"
    elif detector == "review":
        command = "desloppify show review --status open"
        suffix = "s" if count != 1 else ""
        description = (
            f"{count} review finding{suffix} need investigation — "
            "run `desloppify show review --status open` to see them"
        )
        adjusted_info = {**adjusted_info, "action_type": "refactor"}
    else:
        command = f"desloppify show {detector} --status open"
        description = f"{count} {detector} findings — {guidance}"

    return {
        "type": adjusted_info["action_type"],
        "detector": detector,
        "count": count,
        "description": description,
        "command": command,
        "impact": round(impact_for(detector, count), 1),
        "dimension": _dimension_name(detector),
    }


def _append_refactor_actions(
    actions: list[ActionItem],
    by_detector: dict[str, int],
    impact_for: Callable[[str, int], float],
) -> None:
    """Append refactor/manual actions after auto-fix/reorg buckets."""
    for detector, tool_info in DETECTOR_TOOLS.items():
        if tool_info["action_type"] not in {"refactor", "manual_fix"}:
            continue
        count = by_detector.get(detector, 0)
        if count == 0:
            continue
        actions.append(_build_refactor_entry(detector, tool_info, count, impact_for))


def _append_debt_action(actions: list[ActionItem], debt: dict[str, float]) -> None:
    """Append wontfix-debt callout when gap is material."""
    gap = float(debt.get("overall_gap", 0.0) or 0.0)
    if gap <= 2.0:
        return
    actions.append(
        {
            "type": "debt_review",
            "detector": None,
            "description": f"{gap} pts of wontfix debt — review stale decisions",
            "command": "desloppify show --status wontfix",
            "gap": gap,
        }
    )


def _assign_priorities(actions: list[ActionItem]) -> list[ActionItem]:
    """Sort and assign sequential priorities."""
    type_order = {
        "issue_queue": 0,
        "auto_fix": 1,
        "reorganize": 2,
        "refactor": 3,
        "manual_fix": 4,
        "debt_review": 5,
    }
    actions.sort(
        key=lambda action: (type_order.get(action["type"], 9), -action.get("impact", 0))
    )
    for index, action in enumerate(actions, start=1):
        action["priority"] = index
    return actions


def _cluster_detector(cluster: dict) -> str | None:
    """Extract the primary detector from a cluster.

    Uses the cluster_key prefix (e.g. "auto::unused" → "unused",
    "typed::dict_keys::phantom_read" → "dict_keys") or falls back
    to the first member's detector.
    """
    key = cluster.get("cluster_key", "")
    if key:
        parts = key.split("::")
        if len(parts) >= 2:
            return parts[1]
    # Fallback: parse from cluster name (auto/detector-subtype)
    name = cluster.get("name", "")
    if name.startswith("auto/"):
        rest = name[5:]
        return rest.split("-", 1)[0] if "-" in rest else rest
    return None


def _annotate_with_clusters(
    actions: list[ActionItem], clusters: dict | None
) -> None:
    """Annotate actions with matching cluster info when clusters exist."""
    if not clusters:
        return
    for action in actions:
        detector = action.get("detector")
        if not detector:
            continue
        matching = [
            name
            for name, c in clusters.items()
            if c.get("auto") and _cluster_detector(c) == detector
        ]
        if matching:
            action["clusters"] = matching
            action["cluster_count"] = len(matching)
            action["command"] = "desloppify next"
            count = action.get("count", 0)
            display = action.get("detector", "unknown")
            action["description"] = (
                f"{count} {display} findings in {len(matching)} cluster(s) — "
                f"run `desloppify next`"
            )


def compute_actions(ctx: ActionContext) -> list[ActionItem]:
    """Compute prioritized action list with tool mapping."""
    actions: list[ActionItem] = []
    impact_for = _impact_calculator(ctx.dimension_scores, ctx.state)
    supported = supported_fixers(ctx.state, ctx.lang)

    _append_auto_fix_actions(actions, ctx.by_detector, supported, impact_for, ctx.state)
    _append_reorganize_actions(actions, ctx.by_detector, impact_for)
    _append_refactor_actions(actions, ctx.by_detector, impact_for)
    _append_debt_action(actions, ctx.debt)

    prioritized = _assign_priorities(actions)
    _annotate_with_clusters(prioritized, ctx.clusters)
    return prioritized
