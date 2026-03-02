"""Centralized execution policy for review batch orchestration."""

from __future__ import annotations

import math
from dataclasses import dataclass

from desloppify.core._internal.coercions import (
    coerce_non_negative_float as _coerce_non_negative_float,
)
from desloppify.core._internal.coercions import (
    coerce_non_negative_int as _coerce_non_negative_int,
)
from desloppify.core._internal.coercions import (
    coerce_positive_float as _coerce_positive_float,
)
from desloppify.core._internal.coercions import (
    coerce_positive_int as _coerce_positive_int,
)

DEFAULT_BATCH_STALL_KILL_SECONDS = 120


@dataclass(frozen=True)
class BatchRunPolicy:
    """Resolved runtime knobs for `review --run-batches` execution."""

    run_parallel: bool
    max_parallel_batches: int
    heartbeat_seconds: float
    batch_timeout_seconds: int
    batch_max_retries: int
    batch_retry_backoff_seconds: float
    stall_warning_seconds: int
    stall_kill_seconds: int

    def max_parallel_workers(self, total_batches: int) -> int:
        if total_batches <= 0:
            return 1
        if self.run_parallel:
            return min(total_batches, self.max_parallel_batches)
        return 1

    def worst_case_minutes(self, total_batches: int) -> int:
        waves = math.ceil(total_batches / self.max_parallel_workers(total_batches))
        return max(1, math.ceil((waves * self.batch_timeout_seconds) / 60))


def resolve_batch_run_policy(args) -> BatchRunPolicy:
    """Build one canonical policy object from CLI args."""
    return BatchRunPolicy(
        run_parallel=bool(getattr(args, "parallel", False)),
        max_parallel_batches=_coerce_positive_int(
            getattr(args, "max_parallel_batches", None),
            default=3,
            minimum=1,
        ),
        heartbeat_seconds=_coerce_positive_float(
            getattr(args, "batch_heartbeat_seconds", None),
            default=15.0,
            minimum=0.1,
        ),
        batch_timeout_seconds=_coerce_positive_int(
            getattr(args, "batch_timeout_seconds", None),
            default=2 * 60 * 60,
            minimum=1,
        ),
        batch_max_retries=_coerce_positive_int(
            getattr(args, "batch_max_retries", None),
            default=1,
            minimum=0,
        ),
        batch_retry_backoff_seconds=_coerce_non_negative_float(
            getattr(args, "batch_retry_backoff_seconds", None),
            default=2.0,
        ),
        stall_warning_seconds=_coerce_non_negative_int(
            getattr(args, "batch_stall_warning_seconds", None),
            default=0,
        ),
        stall_kill_seconds=_coerce_non_negative_int(
            getattr(args, "batch_stall_kill_seconds", None),
            default=DEFAULT_BATCH_STALL_KILL_SECONDS,
        ),
    )


__all__ = ["BatchRunPolicy", "resolve_batch_run_policy"]
