"""Attempt execution and retry orchestration for review batch runner."""

from __future__ import annotations

from collections.abc import Callable
import subprocess  # nosec
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from desloppify.app.commands.review.runner_failures import (
    TRANSIENT_RUNNER_PHRASES as _TRANSIENT_RUNNER_PHRASES,
)

from .attempt_success import handle_successful_attempt_core
from .io import (
    _check_stall,
    _drain_stream,
    _output_file_has_json_payload,
    _start_live_writer,
    _terminate_process,
    _write_live_snapshot,
)
from .types import (
    CodexBatchRunnerDeps,
    _AttemptContext,
    _ExecutionResult,
    _RetryConfig,
    _RunnerState,
)


@contextmanager
def _managed_live_writer(
    state: _RunnerState,
    ctx: _AttemptContext,
    interval: float,
):
    """Start/stop the live-writer thread around one runner attempt."""
    writer_thread = _start_live_writer(state, ctx, interval)
    try:
        yield
    finally:
        state.stop_event.set()
        writer_thread.join(timeout=2)


def _runner_error_result(
    *,
    ctx: _AttemptContext,
    heading: str,
    exc: Exception,
    exit_code: int,
) -> _ExecutionResult:
    """Build a consistent error result for runner invocation failures."""
    ctx.log_sections.append(f"{ctx.header}\n\n{heading}:\n{exc}\n")
    ctx.safe_write_text_fn(ctx.log_file, "\n\n".join(ctx.log_sections))
    return _ExecutionResult(
        code=exit_code,
        stdout_text="",
        stderr_text="",
        early_return=exit_code,
    )


def _run_via_popen(
    cmd: list[str],
    deps: CodexBatchRunnerDeps,
    state: _RunnerState,
    ctx: _AttemptContext,
    interval: float,
    stall_seconds: int,
    stdout_text_observer: Callable[[str], None] | None = None,
) -> _ExecutionResult:
    with _managed_live_writer(state, ctx, interval):
        process_or_error = _start_runner_process(cmd, deps, ctx)
        if isinstance(process_or_error, _ExecutionResult):
            return process_or_error
        process = process_or_error
        stdout_thread, stderr_thread = _start_stream_threads(
            process,
            state,
            stdout_text_observer=stdout_text_observer,
        )
        timed_out, stalled, recovered_from_stall = _monitor_runner_process(
            process,
            deps=deps,
            state=state,
            ctx=ctx,
            interval=interval,
            stall_seconds=stall_seconds,
        )
        _finalize_runner_process(process, stdout_thread, stderr_thread)
        _write_live_snapshot(state, ctx)
        return _ExecutionResult(
            code=int(process.returncode or 0),
            stdout_text="".join(state.stdout_chunks),
            stderr_text="".join(state.stderr_chunks),
            timed_out=timed_out,
            stalled=stalled,
            recovered_from_stall=recovered_from_stall,
        )


def _start_runner_process(
    cmd: list[str],
    deps: CodexBatchRunnerDeps,
    ctx: _AttemptContext,
) -> subprocess.Popen[str] | _ExecutionResult:
    try:
        return deps.subprocess_popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return _runner_error_result(
            ctx=ctx,
            heading="RUNNER ERROR",
            exc=exc,
            exit_code=127,
        )
    except (
        RuntimeError,
        ValueError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:  # pragma: no cover - defensive boundary
        return _runner_error_result(
            ctx=ctx,
            heading="UNEXPECTED RUNNER ERROR",
            exc=exc,
            exit_code=1,
        )


def _start_stream_threads(
    process: subprocess.Popen[str],
    state: _RunnerState,
    *,
    stdout_text_observer: Callable[[str], None] | None = None,
) -> tuple[threading.Thread, threading.Thread]:
    stdout_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stdout, state.stdout_chunks, state),
        kwargs={"stdout_text_observer": stdout_text_observer},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, state.stderr_chunks, state),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    return stdout_thread, stderr_thread


def _timed_out_runner_attempt(
    process: subprocess.Popen[str],
    *,
    deps: CodexBatchRunnerDeps,
    state: _RunnerState,
    ctx: _AttemptContext,
) -> bool:
    elapsed = int(max(0.0, time.monotonic() - ctx.started_monotonic))
    if elapsed < deps.timeout_seconds:
        return False
    with state.lock:
        state.runner_note = f"timeout after {deps.timeout_seconds}s"
    _terminate_process(process)
    return True


def _check_runner_stall(
    process: subprocess.Popen[str],
    *,
    state: _RunnerState,
    ctx: _AttemptContext,
    stall_seconds: int,
    output_signature: tuple[int, int] | None,
    output_stable_since: float | None,
) -> tuple[bool, bool, tuple[int, int] | None, float | None]:
    with state.lock:
        last_activity = state.last_stream_activity
    stalled, output_signature, output_stable_since = _check_stall(
        ctx.output_file,
        output_signature,
        output_stable_since,
        time.monotonic(),
        last_activity,
        stall_seconds,
    )
    if not stalled:
        return False, False, output_signature, output_stable_since
    with state.lock:
        state.runner_note = (
            f"stall recovery triggered after {stall_seconds}s "
            "with stable output state"
        )
    recovered_from_stall = _output_file_has_json_payload(ctx.output_file)
    _terminate_process(process)
    return True, recovered_from_stall, output_signature, output_stable_since


def _monitor_runner_process(
    process: subprocess.Popen[str],
    *,
    deps: CodexBatchRunnerDeps,
    state: _RunnerState,
    ctx: _AttemptContext,
    interval: float,
    stall_seconds: int,
) -> tuple[bool, bool, bool]:
    timed_out = False
    stalled = False
    recovered_from_stall = False
    output_signature: tuple[int, int] | None = None
    output_stable_since: float | None = None

    while process.poll() is None:
        if _timed_out_runner_attempt(process, deps=deps, state=state, ctx=ctx):
            timed_out = True
            break
        if stall_seconds > 0:
            (
                stalled,
                recovered_from_stall,
                output_signature,
                output_stable_since,
            ) = _check_runner_stall(
                process,
                state=state,
                ctx=ctx,
                stall_seconds=stall_seconds,
                output_signature=output_signature,
                output_stable_since=output_stable_since,
            )
            if stalled:
                break
        deps.sleep_fn(min(interval, 1.0))
    return timed_out, stalled, recovered_from_stall


def _finalize_runner_process(
    process: subprocess.Popen[str],
    stdout_thread: threading.Thread,
    stderr_thread: threading.Thread,
) -> None:
    if process.poll() is None:
        _terminate_process(process)
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)


def _run_via_subprocess(
    cmd: list[str],
    deps: CodexBatchRunnerDeps,
    state: _RunnerState,
    ctx: _AttemptContext,
    interval: float,
) -> _ExecutionResult:
    with _managed_live_writer(state, ctx, interval):
        try:
            result = deps.subprocess_run(
                cmd,
                capture_output=True,
                text=True,
                timeout=deps.timeout_seconds,
            )
        except deps.timeout_error:
            return _ExecutionResult(code=124, stdout_text="", stderr_text="", timed_out=True)
        except OSError as exc:
            return _runner_error_result(
                ctx=ctx,
                heading="RUNNER ERROR",
                exc=exc,
                exit_code=127,
            )
        except (RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover - defensive boundary
            return _runner_error_result(
                ctx=ctx,
                heading="UNEXPECTED RUNNER ERROR",
                exc=exc,
                exit_code=1,
            )

        return _ExecutionResult(
            code=int(result.returncode),
            stdout_text=result.stdout or "",
            stderr_text=result.stderr or "",
        )


def resolve_retry_config(deps: CodexBatchRunnerDeps) -> _RetryConfig:
    retries_raw = deps.max_retries if isinstance(deps.max_retries, int) else 0
    max_retries = max(0, retries_raw)
    max_attempts = max_retries + 1
    backoff_raw = (
        float(deps.retry_backoff_seconds)
        if isinstance(deps.retry_backoff_seconds, int | float)
        else 0.0
    )
    retry_backoff_seconds = max(0.0, backoff_raw)
    live_log_interval = (
        float(deps.live_log_interval_seconds)
        if isinstance(deps.live_log_interval_seconds, int | float)
        and float(deps.live_log_interval_seconds) > 0
        else 5.0
    )
    stall_seconds = (
        int(deps.stall_after_output_seconds)
        if isinstance(deps.stall_after_output_seconds, int | float)
        and int(deps.stall_after_output_seconds) > 0
        else 0
    )
    use_popen = bool(deps.use_popen_runner) and callable(
        getattr(deps, "subprocess_popen", None)
    )
    return _RetryConfig(
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        live_log_interval=live_log_interval,
        stall_seconds=stall_seconds,
        use_popen=use_popen,
    )


def run_batch_attempt(
    *,
    cmd: list[str],
    deps: CodexBatchRunnerDeps,
    output_file: Path,
    log_file: Path,
    log_sections: list[str],
    attempt: int,
    max_attempts: int,
    use_popen: bool,
    live_log_interval: float,
    stall_seconds: int,
    stdout_text_observer: Callable[[str], None] | None = None,
) -> tuple[str, _ExecutionResult]:
    header = f"ATTEMPT {attempt}/{max_attempts}\n$ {' '.join(cmd)}"
    started_monotonic = time.monotonic()
    state = _RunnerState(last_stream_activity=started_monotonic)
    ctx = _AttemptContext(
        header=header,
        started_at_iso=datetime.now(UTC).isoformat(timespec="seconds"),
        started_monotonic=started_monotonic,
        output_file=output_file,
        log_file=log_file,
        log_sections=log_sections,
        safe_write_text_fn=deps.safe_write_text_fn,
    )
    _write_live_snapshot(state, ctx)
    if use_popen:
        result = _run_via_popen(
            cmd,
            deps,
            state,
            ctx,
            live_log_interval,
            stall_seconds,
            stdout_text_observer,
        )
    else:
        result = _run_via_subprocess(cmd, deps, state, ctx, live_log_interval)
    return header, result


def handle_early_attempt_return(result: _ExecutionResult) -> int | None:
    return result.early_return


def handle_timeout_or_stall(
    *,
    header: str,
    result: _ExecutionResult,
    deps: CodexBatchRunnerDeps,
    output_file: Path,
    log_file: Path,
    log_sections: list[str],
    stall_seconds: int,
) -> int | None:
    if not result.timed_out and not result.stalled:
        return None
    if result.timed_out:
        log_sections.append(
            f"{header}\n\nTIMEOUT after {deps.timeout_seconds}s\n\n"
            f"STDOUT:\n{result.stdout_text}\n\nSTDERR:\n{result.stderr_text}\n"
        )
    else:
        log_sections.append(
            f"{header}\n\nSTALL RECOVERY after {stall_seconds}s "
            "of stable output and no stream activity.\n\n"
            f"STDOUT:\n{result.stdout_text}\n\nSTDERR:\n{result.stderr_text}\n"
        )
    if _output_file_has_json_payload(output_file):
        recovery_message = (
            "Recovered timed-out batch from JSON output file; "
            "continuing as success."
            if result.timed_out
            else "Recovered stalled batch from JSON output file; "
            "continuing as success."
        )
        log_sections.append(recovery_message)
        deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
        return 0
    deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
    return 124


def handle_successful_attempt(
    *,
    result: _ExecutionResult,
    output_file: Path,
    log_file: Path,
    deps: CodexBatchRunnerDeps,
    log_sections: list[str],
) -> int | None:
    if result.code != 0:
        return None
    if not output_file.exists():
        log_sections.append("Runner returned 0 but output file is missing.")
    validate_fn = _resolved_validate_output_fn(deps)
    return handle_successful_attempt_core(
        result=result,
        output_file=output_file,
        log_file=log_file,
        deps=deps,
        log_sections=log_sections,
        default_validate_fn=validate_fn,
        monotonic_fn=time.monotonic,
    )


def _resolved_validate_output_fn(deps: CodexBatchRunnerDeps):
    if deps.validate_output_fn is not None:
        return deps.validate_output_fn
    return _output_file_has_json_payload


def handle_failed_attempt(
    *,
    result: _ExecutionResult,
    deps: CodexBatchRunnerDeps,
    attempt: int,
    max_attempts: int,
    retry_backoff_seconds: float,
    log_file: Path,
    log_sections: list[str],
) -> int | None:
    combined = f"{result.stdout_text}\n{result.stderr_text}".lower()
    is_transient = any(needle in combined for needle in _TRANSIENT_RUNNER_PHRASES)
    if not is_transient or attempt >= max_attempts:
        deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
        return result.code
    delay_seconds = _retry_delay_seconds(
        retry_backoff_seconds,
        attempt=attempt,
    )
    log_sections.append(
        "Transient runner failure detected; "
        f"retrying in {delay_seconds:.1f}s (attempt {attempt + 1}/{max_attempts})."
    )
    try:
        if delay_seconds > 0:
            deps.sleep_fn(delay_seconds)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        log_sections.append(
            f"Retry delay hook failed: {exc} — aborting remaining retries."
        )
        deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
        return 1
    return None


def _retry_delay_seconds(
    retry_backoff_seconds: float,
    *,
    attempt: int,
) -> float:
    return retry_backoff_seconds * (2 ** (attempt - 1))


__all__ = [
    "handle_early_attempt_return",
    "handle_failed_attempt",
    "handle_successful_attempt",
    "handle_timeout_or_stall",
    "resolve_retry_config",
    "run_batch_attempt",
    "_run_via_popen",
    "_run_via_subprocess",
]
