"""Preflight guards for subjective review reruns.

Blocks reruns while backlog remains (objective issues and/or subjective queue
work), unless ``--force-review-rerun`` is set. Also clears stale subjective
markers before a new cycle.
"""

from __future__ import annotations

import re
import sys

from desloppify.app.commands.helpers.query import load_query_result
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.engine._work_queue.context import queue_context
from desloppify.state_io import StateModel, save_state

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
        elif isinstance(assessment, int | float) and assessment:
            scored.append(dim_key)
    return sorted(scored)


def _normalize_dimension_key(raw: object) -> str:
    """Normalize a dimension key/name to canonical snake_case."""
    text = str(raw or "").strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_")


def _prepared_query_dimensions() -> set[str] | None:
    """Return prepared review dimensions from query.json when available."""
    query_result = load_query_result()
    if not query_result.ok:
        if query_result.error_kind in {"query_parse_error", "query_invalid_shape"}:
            detail = query_result.message or query_result.error_kind
            print(
                colorize(
                    f"  Warning: ignoring invalid query artifact ({detail}).",
                    "yellow",
                ),
                file=sys.stderr,
            )
        return None
    query = query_result.payload or {}
    if not isinstance(query, dict):
        return None
    if query.get("command") != "review" or query.get("mode") != "holistic":
        return None
    if not isinstance(query.get("investigation_batches"), list):
        return None
    dims = query.get("dimensions")
    if not isinstance(dims, list):
        return None
    resolved = {dim.strip() for dim in dims if isinstance(dim, str) and dim.strip()}
    return resolved or None


def _target_dimensions(args: object) -> set[str] | None:
    """Resolve review target dimensions from CLI args or prepared query state."""
    dimensions = parse_dimensions(args)
    if dimensions is not None:
        return dimensions
    if getattr(args, "run_batches", False) or getattr(args, "external_start", False):
        return _prepared_query_dimensions()
    return None


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
    ctx = queue_context(state)
    if not blocking_dims:
        return ctx.snapshot.objective_execution_count, 0

    normalized_blocking_dims = {_normalize_dimension_key(dim) for dim in blocking_dims}

    def _item_dimension_key(item: dict) -> str | None:
        detail = item.get("detail")
        if not isinstance(detail, dict):
            return None
        dimension = detail.get("dimension")
        if not isinstance(dimension, str) or not dimension.strip():
            return None
        return _normalize_dimension_key(dimension)

    subjective_total = sum(
        1
        for item in ctx.snapshot.all_postflight_review_items
        if item.get("kind") != "subjective_dimension"
        if (dim_key := _item_dimension_key(item)) is not None
        and dim_key in normalized_blocking_dims
    )
    return ctx.snapshot.objective_execution_count, subjective_total


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
                f"  Open objective issue(s): {objective_total}",
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
    dimensions = _target_dimensions(args)
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
                raise CommandError(
                    f"rerun blocked: open backlog (objective: {objective_total}, "
                    f"subjective: {subjective_total})",
                    exit_code=1,
                )

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
