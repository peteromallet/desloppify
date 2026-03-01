"""Shared queue-construction policy for next/plan command surfaces."""

from __future__ import annotations

from typing import Any

from desloppify.core.enums import Status, canonical_status_filter
from desloppify.engine.work_queue import QueueBuildOptions, build_work_queue


def build_plan_queue(
    state: dict[str, Any],
    *,
    tier: int | None = None,
    count: int | None = None,
    scope: str | None = None,
    status: str = Status.OPEN.value,
    target_strict: float = 95.0,
    no_tier_fallback: bool = False,
    explain: bool = False,
    plan: dict[str, Any] | None = None,
    include_skipped: bool = False,
    cluster: str | None = None,
    collapse_clusters: bool = False,
) -> dict[str, Any]:
    """Build one queue with consistent policy defaults used by CLI surfaces."""
    normalized_status = canonical_status_filter(status, default=Status.OPEN.value)
    return build_work_queue(
        state,
        options=QueueBuildOptions(
            tier=tier,
            count=count,
            scan_path=state.get("scan_path"),
            scope=scope,
            status=normalized_status,
            include_subjective=True,
            subjective_threshold=target_strict,
            no_tier_fallback=no_tier_fallback,
            explain=explain,
            plan=plan,
            include_skipped=include_skipped,
            cluster=cluster,
            collapse_clusters=collapse_clusters,
        ),
    )


__all__ = ["build_plan_queue"]
