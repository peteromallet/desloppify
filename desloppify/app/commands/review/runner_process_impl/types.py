"""Typed contracts for review batch process execution."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CodexBatchRunnerDeps:
    timeout_seconds: int
    subprocess_run: Callable[..., object]
    timeout_error: type[BaseException]
    safe_write_text_fn: Callable[[Path, str], None]
    use_popen_runner: bool = False
    subprocess_popen: Callable[..., object] | None = None
    live_log_interval_seconds: float = 5.0
    stall_after_output_seconds: int = 90
    max_retries: int = 0
    retry_backoff_seconds: float = 0.0
    sleep_fn: Callable[[float], None] = time.sleep
    validate_output_fn: Callable[[Path], bool] | None = None
    output_validation_grace_seconds: float = 2.0
    output_validation_poll_seconds: float = 0.1


@dataclass(frozen=True)
class FollowupScanDeps:
    project_root: Path
    timeout_seconds: int
    python_executable: str
    subprocess_run: Callable[..., object]
    timeout_error: type[BaseException]
    colorize_fn: Callable[[str, str], str]


@dataclass
class _RunnerState:
    """Mutable state shared between threads during a batch run."""

    stdout_chunks: list[str] = field(default_factory=list)
    stderr_chunks: list[str] = field(default_factory=list)
    runner_note: str = ""
    last_stream_activity: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True)
class _AttemptContext:
    """Immutable per-attempt context bundling values that closures captured."""

    header: str
    started_at_iso: str
    started_monotonic: float
    output_file: Path
    log_file: Path
    log_sections: list[str]
    safe_write_text_fn: Callable[[Path, str], None]


@dataclass
class _ExecutionResult:
    """Unified return from both execution paths."""

    code: int
    stdout_text: str
    stderr_text: str
    timed_out: bool = False
    stalled: bool = False
    recovered_from_stall: bool = False
    early_return: int | None = None


@dataclass(frozen=True)
class _RetryConfig:
    """Normalized retry/runtime policy for batch attempts."""

    max_attempts: int
    retry_backoff_seconds: float
    live_log_interval: float
    stall_seconds: int
    use_popen: bool


BatchRunnerDeps = CodexBatchRunnerDeps


__all__ = [
    "CodexBatchRunnerDeps",
    "BatchRunnerDeps",
    "FollowupScanDeps",
    "_AttemptContext",
    "_ExecutionResult",
    "_RetryConfig",
    "_RunnerState",
]
