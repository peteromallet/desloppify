"""Queue-policy helpers shared by planning render/select modules."""

from __future__ import annotations

from dataclasses import replace

from desloppify.base.config import DEFAULT_TARGET_STRICT_SCORE
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    QueueVisibility,
    WorkQueueResult,
    _build_work_queue_with_visibility,
    build_work_queue,
)


def _subjective_threshold(state: StateModel, *, default: float = DEFAULT_TARGET_STRICT_SCORE) -> float:
    config = state.get("config", {})
    raw_target = default
    if isinstance(config, dict):
        raw_target = config.get("target_strict_score", default)
    try:
        value = float(raw_target)
    except (TypeError, ValueError):
        value = default
    return max(0.0, min(100.0, value))


def _queue_plan_from_options(options: QueueBuildOptions) -> dict | None:
    if options.context is not None:
        return options.context.plan
    return options.plan


def _resolved_subjective_threshold(
    state: StateModel,
    options: QueueBuildOptions,
) -> float:
    """Return the effective subjective threshold for queue builders.

    When callers pass a precomputed QueueContext, the queue builder must honor
    the context's resolved target_strict value; otherwise open-queue surfaces
    can disagree about whether review findings or subjective dimensions should
    be visible. Falling back to the state/config-derived target preserves the
    legacy behavior for plan-only callers.
    """
    if options.context is not None:
        return float(options.context.target_strict)
    return _subjective_threshold(state)


def build_open_plan_queue(
    state: StateModel,
    *,
    options: QueueBuildOptions | None = None,
) -> WorkQueueResult:
    """Build one open-status queue with consistent planning policy defaults."""
    opts = replace(options) if options is not None else QueueBuildOptions(count=None)
    if options is None:
        opts = replace(opts, status="open", include_subjective=True)
    elif opts.status == QueueBuildOptions().status:
        opts = replace(opts, status="open")
    if opts.subjective_threshold == QueueBuildOptions().subjective_threshold:
        opts = replace(opts, subjective_threshold=_resolved_subjective_threshold(state, opts))
    return build_work_queue(
        state,
        options=opts,
    )


def build_execution_queue(
    state: StateModel,
    *,
    options: QueueBuildOptions | None = None,
) -> WorkQueueResult:
    """Build the execution queue that follows the living plan when present."""
    options = options or QueueBuildOptions()
    ctx = options.context or queue_context(
        state,
        plan=_queue_plan_from_options(options),
        target_strict=_subjective_threshold(state),
    )
    if options.subjective_threshold == QueueBuildOptions().subjective_threshold:
        options = replace(options, subjective_threshold=ctx.target_strict)
    return _build_work_queue_with_visibility(
        state,
        options=replace(options, context=ctx),
        visibility=QueueVisibility.EXECUTION,
    )


def build_backlog_queue(
    state: StateModel,
    *,
    options: QueueBuildOptions | None = None,
) -> WorkQueueResult:
    """Build the broader backlog, excluding work already tracked in the plan."""
    options = options or QueueBuildOptions()
    ctx = options.context or queue_context(
        state,
        plan=_queue_plan_from_options(options),
        target_strict=_subjective_threshold(state),
    )
    if options.subjective_threshold == QueueBuildOptions().subjective_threshold:
        options = replace(options, subjective_threshold=ctx.target_strict)
    return _build_work_queue_with_visibility(
        state,
        options=replace(options, context=ctx),
        visibility=QueueVisibility.BACKLOG,
    )


__all__ = [
    "build_backlog_queue",
    "build_execution_queue",
    "build_open_plan_queue",
]
