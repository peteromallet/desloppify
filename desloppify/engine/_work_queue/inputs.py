"""Queue input resolution and non-open item gathering."""

from __future__ import annotations

from desloppify.engine._work_queue.helpers import ALL_STATUSES, scope_matches
from desloppify.engine._work_queue.models import QueueBuildOptions
from desloppify.engine._work_queue.synthetic import build_subjective_items
from desloppify.engine._work_queue.types import WorkQueueItem
from desloppify.engine._state.schema import StateModel


def resolve_queue_inputs(
    opts: QueueBuildOptions,
    state: StateModel,
) -> tuple[dict | None, str | None, str, float]:
    """Resolve plan, scan path, status, and subjective threshold."""
    ctx = opts.context
    plan = ctx.plan if ctx is not None else opts.plan

    scan_path: str | None = (
        state.get("scan_path")
        if opts.scan_path.__class__.__name__ == "_ScanPathFromState"
        else opts.scan_path
    )

    status = opts.status
    if status not in ALL_STATUSES:
        raise ValueError(f"Unsupported status filter: {status}")

    try:
        # The shared context owns the resolved target, just as it owns the plan.
        threshold = float(ctx.target_strict if ctx is not None else opts.subjective_threshold)
    except (TypeError, ValueError):
        threshold = 100.0
    threshold = max(0.0, min(100.0, threshold))
    return plan, scan_path, status, threshold


def gather_subjective_items(
    state: StateModel,
    opts: QueueBuildOptions,
    threshold: float,
) -> list[WorkQueueItem]:
    """Build subjective dimension candidates for non-open issue list views."""
    if not opts.include_subjective:
        return []
    if opts.status not in {"open", "all"}:
        return []
    if opts.chronic:
        return []

    candidates = build_subjective_items(
        state,
        (state.get("work_items") or state.get("issues", {})),
        threshold=threshold,
        plan=opts.context.plan if opts.context is not None else opts.plan,
    )
    return [item for item in candidates if scope_matches(item, opts.scope)]


__all__ = ["gather_subjective_items", "resolve_queue_inputs"]
