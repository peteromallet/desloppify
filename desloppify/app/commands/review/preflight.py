"""Preflight guards for subjective review reruns.

Blocks reruns while backlog remains (objective findings and/or subjective queue
work), unless ``--force-review-rerun`` is set. Also clears stale subjective
markers before a new cycle.
"""

from __future__ import annotations

import re
import sys

from desloppify.core.output_api import colorize
from desloppify.engine._work_queue.core import QueueBuildOptions, build_work_queue
from desloppify.state import StateModel, save_state

from .helpers import parse_dimensions


def clear_stale_subjective_entries(
    state: StateModel,
    *,
    dimensions: set[str] | None = None,
) -> list[str]:
    """Clear ``needs_review_refresh`` markers from subjective assessments.

    When *dimensions* is provided, only those dimensions are cleared;
    otherwise all stale dimensions are cleared.

    Returns the list of dimension keys that were cleared.
    """
    assessments: dict = state.get("subjective_assessments", {})
    cleared: list[str] = []
    for dim_key, assessment in assessments.items():
        if not isinstance(assessment, dict):
            continue
        if dimensions is not None and dim_key not in dimensions:
            continue
        if assessment.get("needs_review_refresh"):
            assessment.pop("needs_review_refresh", None)
            assessment.pop("stale_since", None)
            assessment.pop("refresh_reason", None)
            cleared.append(dim_key)
    return cleared


def _scored_dimensions(state: StateModel) -> list[str]:
    """Return dimension keys that already have a nonzero subjective score."""
    assessments: dict = state.get("subjective_assessments", {})
    scored: list[str] = []
    for dim_key, assessment in assessments.items():
        if isinstance(assessment, dict):
            if assessment.get("score", 0):
                scored.append(dim_key)
        elif isinstance(assessment, (int, float)) and assessment:
            scored.append(dim_key)
    return sorted(scored)


def _normalize_dimension_key(raw: object) -> str:
    """Normalize a dimension key/name to canonical snake_case."""
    text = str(raw or "").strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_")


def _count_open_subjective_queue_items(
    state: StateModel,
    *,
    dimensions: set[str] | None = None,
) -> int:
    """Count open synthetic subjective queue items for rerun gating."""
    normalized_dims = (
        {_normalize_dimension_key(dim) for dim in dimensions}
        if dimensions is not None
        else None
    )
    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            status="open",
            include_subjective=True,
            count=None,
        ),
    )
    count = 0
    for item in queue.get("items", []):
        if item.get("kind") != "subjective_dimension":
            continue
        if normalized_dims is None:
            count += 1
            continue
        detail = item.get("detail")
        raw_dim = detail.get("dimension", "") if isinstance(detail, dict) else ""
        item_dim = _normalize_dimension_key(raw_dim)
        if item_dim and item_dim in normalized_dims:
            count += 1
    return count


def _blocking_scored_dimensions(
    state: StateModel,
    *,
    dimensions: set[str] | None,
    normalized_dimensions: set[str] | None,
) -> list[str]:
    scored_dims = _scored_dimensions(state)
    if dimensions is None:
        return scored_dims
    normalized = normalized_dimensions or set()
    return sorted(
        dim
        for dim in scored_dims
        if _normalize_dimension_key(dim) in normalized
    )


def _objective_and_subjective_backlog(
    state: StateModel,
    *,
    blocking_dims: list[str],
) -> tuple[int, int]:
    objective_result = build_work_queue(
        state,
        options=QueueBuildOptions(
            status="open",
            include_subjective=False,
            count=None,
        ),
    )
    objective_total = objective_result["total"]
    subjective_total = _count_open_subjective_queue_items(
        state,
        dimensions=set(blocking_dims),
    )
    return objective_total, subjective_total


def _print_backlog_blocked_message(
    *,
    blocking_dims: list[str],
    objective_total: int,
    subjective_total: int,
    dimensions: set[str] | None,
) -> None:
    print(
        colorize(
            "  Blocked: rerun requires drained backlog "
            f"(objective: {objective_total}, subjective: {subjective_total}).",
            "red",
        ),
        file=sys.stderr,
    )
    print(
        colorize(
            f"  Scored dimensions: {', '.join(blocking_dims)}",
            "yellow",
        ),
        file=sys.stderr,
    )
    if objective_total > 0:
        print(
            colorize(
                f"  Open objective finding(s): {objective_total}",
                "yellow",
            ),
            file=sys.stderr,
        )
    if subjective_total > 0:
        print(
            colorize(
                f"  Open subjective queue item(s): {subjective_total}",
                "yellow",
            ),
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    if dimensions is not None:
        unscored = sorted(dimensions - set(blocking_dims))
        if unscored:
            print(
                colorize(
                    f"  Tip: target only unscored dimensions with "
                    f"--dimensions {','.join(unscored)}",
                    "dim",
                ),
                file=sys.stderr,
            )
    print(
        colorize(
            "  Resolve open items first, or override with --force-review-rerun",
            "dim",
        ),
        file=sys.stderr,
    )


def review_rerun_preflight(
    state: StateModel,
    args,
    *,
    state_file=None,
    save_fn=save_state,
) -> None:
    """Single entry point: gate check -> clear stale -> save.

    Exits with code 1 when open backlog exists and ``--force-review-rerun`` is
    not set. On success, clears stale subjective markers for targeted
    dimensions and persists state.
    """
    dimensions = parse_dimensions(args)
    normalized_dimensions = (
        {_normalize_dimension_key(dim) for dim in dimensions}
        if dimensions is not None
        else None
    )

    # --force-review-rerun bypasses the gate
    if getattr(args, "force_review_rerun", False):
        print(
            colorize(
                "  --force-review-rerun: bypassing rerun backlog checks.",
                "yellow",
            )
        )
    else:
        # Only gate dimensions that are actually targeted by this review run.
        blocking_dims = _blocking_scored_dimensions(
            state,
            dimensions=dimensions,
            normalized_dimensions=normalized_dimensions,
        )

        # No gate when none of the targeted dimensions have prior scores —
        # this is a first run for these dimensions, not a rerun.
        if blocking_dims:
            objective_total, subjective_total = _objective_and_subjective_backlog(
                state,
                blocking_dims=blocking_dims,
            )
            if objective_total > 0 or subjective_total > 0:
                _print_backlog_blocked_message(
                    blocking_dims=blocking_dims,
                    objective_total=objective_total,
                    subjective_total=subjective_total,
                    dimensions=dimensions,
                )
                sys.exit(1)

    # Gate passed — clear stale for targeted dims
    cleared = clear_stale_subjective_entries(state, dimensions=dimensions)
    if cleared and state_file:
        save_fn(state, state_file)
        print(
            colorize(
                f"  Cleared stale review markers: {', '.join(sorted(cleared))}",
                "cyan",
            )
        )
