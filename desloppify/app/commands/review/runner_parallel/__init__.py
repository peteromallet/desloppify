"""Parallel execution and progress-callback helpers for review batches."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from desloppify.base.discovery.file_paths import safe_write_text

from .execution import (
    _drain_parallel_completions,
    _execute_serial,
    _queue_parallel_tasks,
    _resolve_parallel_runtime,
)
from .progress import _coerce_batch_execution_options
from .types import (
    BatchExecutionOptions,
    BatchProgressEvent,
    BatchResult,
    BatchTask,
)
from ..runner_process_impl.io import extract_payload_from_log

logger = logging.getLogger(__name__)


def execute_batches(
    *,
    tasks: dict[int, BatchTask],
    options: BatchExecutionOptions | None = None,
    progress_fn=None,
    error_log_fn=None,
) -> list[int]:
    """Run indexed tasks and return failed index list.

    Each value in *tasks* is a zero-arg callable returning an int exit code.
    All domain knowledge (files, prompts, etc.) is pre-bound by the caller.
    """
    resolved_options = _coerce_batch_execution_options(options)
    contract_cache: dict[int, str] = {}
    indexes = sorted(tasks)
    if resolved_options.run_parallel:
        max_workers, heartbeat = _resolve_parallel_runtime(
            indexes=indexes,
            max_parallel_workers=resolved_options.max_parallel_workers,
            heartbeat_seconds=resolved_options.heartbeat_seconds,
        )
        failures: set[int] = set()
        progress_failures: set[int] = set()
        started_at: dict[int, float] = {}
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = _queue_parallel_tasks(
                executor=executor,
                indexes=indexes,
                tasks=tasks,
                progress_fn=progress_fn,
                error_log_fn=error_log_fn,
                contract_cache=contract_cache,
                max_workers=max_workers,
                failures=failures,
                progress_failures=progress_failures,
                started_at=started_at,
                lock=lock,
                clock_fn=resolved_options.clock_fn,
            )
            pending = set(futures.keys())
            _drain_parallel_completions(
                pending=pending,
                futures=futures,
                heartbeat=heartbeat,
                indexes=indexes,
                progress_fn=progress_fn,
                error_log_fn=error_log_fn,
                contract_cache=contract_cache,
                failures=failures,
                progress_failures=progress_failures,
                started_at=started_at,
                lock=lock,
                clock_fn=resolved_options.clock_fn,
            )
        return sorted(failures)
    return _execute_serial(
        tasks=tasks,
        indexes=indexes,
        progress_fn=progress_fn,
        error_log_fn=error_log_fn,
        clock_fn=resolved_options.clock_fn,
        contract_cache=contract_cache,
    )


def collect_batch_results(
    *,
    selected_indexes: list[int],
    failures: list[int],
    output_files: dict[int, Path],
    allowed_dims: set[str],
    extract_payload_fn,
    normalize_result_fn,
) -> tuple[list[BatchResult], list[int]]:
    """Parse and normalize batch outputs, preserving prior failures."""
    batch_results: list[BatchResult] = []
    failure_set = set(failures)
    for idx in selected_indexes:
        had_execution_failure = idx in failure_set
        raw_path = output_files[idx]
        payload = None
        parsed_from_log = False
        if raw_path.exists():
            try:
                payload = extract_payload_fn(raw_path.read_text())
            except OSError as exc:
                logger.warning("Failed reading batch payload %s: %s", raw_path, exc)
                payload = None
        if payload is None:
            payload = extract_payload_from_log(idx, raw_path, extract_payload_fn)
            parsed_from_log = payload is not None
        if payload is None:
            failure_set.add(idx)
            continue
        if parsed_from_log:
            try:
                safe_write_text(raw_path, json.dumps(payload, indent=2) + "\n")
            except OSError as exc:
                logger.warning("Failed writing normalized batch payload %s: %s", raw_path, exc)
        try:
            (
                assessments,
                issues,
                dimension_notes,
                dimension_judgment,
                quality,
            ) = normalize_result_fn(payload, allowed_dims)
        except ValueError as exc:
            logger.debug("Invalid batch payload at index %s (%s): %s", idx, raw_path, exc)
            failure_set.add(idx)
            continue
        if had_execution_failure:
            failure_set.discard(idx)
            logger.info(
                "Batch #%d recovered: execution exited non-zero but raw payload parsed successfully",
                idx + 1,
            )
        batch_results.append(
            BatchResult(
                batch_index=idx + 1,
                assessments=assessments,
                dimension_notes=dimension_notes,
                dimension_judgment=dimension_judgment,
                issues=issues,
                quality=quality,
            )
        )
    return batch_results, sorted(failure_set)


__all__ = [
    "BatchResult",
    "BatchExecutionOptions",
    "BatchProgressEvent",
    "collect_batch_results",
    "execute_batches",
]
