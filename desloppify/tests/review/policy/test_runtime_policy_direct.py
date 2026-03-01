"""Direct tests for review runtime batch policy resolution."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.app.commands.review.orchestration.runtime_defaults import (
    DEFAULT_BATCH_STALL_KILL_SECONDS,
)
from desloppify.app.commands.review.runtime.policy import resolve_batch_run_policy


def test_resolve_batch_run_policy_uses_cli_values() -> None:
    args = SimpleNamespace(
        parallel=True,
        max_parallel_batches="4",
        batch_heartbeat_seconds="2.5",
        batch_timeout_seconds="300",
        batch_max_retries="2",
        batch_retry_backoff_seconds="1.5",
        batch_stall_warning_seconds="30",
        batch_stall_kill_seconds="45",
    )

    policy = resolve_batch_run_policy(args)

    assert policy.run_parallel is True
    assert policy.max_parallel_batches == 4
    assert policy.heartbeat_seconds == 2.5
    assert policy.batch_timeout_seconds == 300
    assert policy.batch_max_retries == 2
    assert policy.batch_retry_backoff_seconds == 1.5
    assert policy.stall_warning_seconds == 30
    assert policy.stall_kill_seconds == 45
    assert policy.max_parallel_workers(10) == 4
    assert policy.max_parallel_workers(0) == 1
    assert policy.worst_case_minutes(10) == 15


def test_resolve_batch_run_policy_falls_back_for_invalid_values() -> None:
    args = SimpleNamespace(
        parallel=False,
        max_parallel_batches=0,
        batch_heartbeat_seconds=0,
        batch_timeout_seconds=0,
        batch_max_retries=-1,
        batch_retry_backoff_seconds=-1,
        batch_stall_warning_seconds=-1,
        batch_stall_kill_seconds=-1,
    )

    policy = resolve_batch_run_policy(args)

    assert policy.run_parallel is False
    assert policy.max_parallel_batches == 3
    assert policy.heartbeat_seconds == 15.0
    assert policy.batch_timeout_seconds == 2 * 60 * 60
    assert policy.batch_max_retries == 1
    assert policy.batch_retry_backoff_seconds == 2.0
    assert policy.stall_warning_seconds == 0
    assert policy.stall_kill_seconds == DEFAULT_BATCH_STALL_KILL_SECONDS
    assert policy.max_parallel_workers(7) == 1
    assert policy.worst_case_minutes(0) == 1
