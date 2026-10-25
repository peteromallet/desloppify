"""Queue-policy helpers shared by planning render/select modules."""

from __future__ import annotations

from dataclasses import replace

from desloppify.base.config import DEFAULT_TARGET_STRICT_SCORE
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.context import QueueContext, queue_context
from desloppify.engine._work_queue.core import (
    QueueBuildOptions,
    QueueVisibility,
    WorkQueueResult,
    _build_work_queue_with_visibility,
    build_work_queue,
)
from desloppify.engine._work_queue.inputs import resolve_queue_inputs


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


def _queue_context_from_options(state: StateModel, options: QueueBuildOptions) -> QueueContext:
    """Keep one target authoritative without discarding explicit legacy options."""
    if options.context is not None:
        return options.context
    threshold_options = options
    if options.subjective_threshold == QueueBuildOptions().subjective_threshold:
        threshold_options = replace(options, subjective_threshold=_subjective_threshold(state))
    _, _, _, threshold = resolve_queue_inputs(threshold_options, state)
    return queue_context(
        state,
        plan=_queue_plan_from_options(options),
        target_strict=threshold,
    )


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
        opts = replace(opts, subjective_threshold=_subjective_threshold(state))
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
    ctx = _queue_context_from_options(state, options)
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
    ctx = _queue_context_from_options(state, options)
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
