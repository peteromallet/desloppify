"""I/O and log helpers for review batch process execution."""

from __future__ import annotations

import json
import logging
import subprocess  # nosec
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from desloppify.base.output.fallbacks import log_best_effort_failure

from .types import _AttemptContext, _RunnerState

logger = logging.getLogger(__name__)


def _output_file_status_text(output_file: Path) -> str:
    """Describe output file state for live log snapshots."""
    if not output_file.exists():
        return f"{output_file} (missing)"
    try:
        stat = output_file.stat()
    except OSError as exc:
        return f"{output_file} (exists; stat failed: {exc})"
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(
        timespec="seconds"
    )
    return f"{output_file} (exists; bytes={stat.st_size}; modified={modified_at})"


def _output_file_has_json_payload(output_file: Path) -> bool:
    """Return True when the output file contains a valid JSON object."""
    if not output_file.exists():
        return False
    try:
        payload = json.loads(output_file.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict)


def extract_payload_from_log(
    batch_index: int,
    raw_path: Path,
    extract_fn,
) -> dict[str, object] | None:
    """Try to recover a batch payload from the runner log file."""
    log_path = raw_path.parent.parent / "logs" / f"batch-{batch_index + 1}.log"
    if not log_path.exists():
        return None
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    stdout_marker = "\nSTDOUT:\n"
    stderr_marker = "\n\nSTDERR:\n"
    stdout_start = log_text.rfind(stdout_marker)
    if stdout_start == -1 and log_text.startswith("STDOUT:\n"):
        stdout_start = 0
        stdout_offset = len("STDOUT:\n")
    elif stdout_start >= 0:
        stdout_offset = len(stdout_marker)
    else:
        stdout_offset = 0
    if stdout_start >= 0:
        start_idx = stdout_start + stdout_offset
        stdout_end = log_text.find(stderr_marker, start_idx)
        stdout_text = (
            log_text[start_idx:] if stdout_end == -1 else log_text[start_idx:stdout_end]
        )
        payload = extract_fn(stdout_text)
        if payload is not None:
            return payload
        # If the batch log has a concrete STDOUT section but it contains no parseable
        # payload, do not fallback to parsing the whole log. Full logs include the
        # prompt template (often with JSON examples), which can hide true STDERR failures.
        return None

    return extract_fn(log_text)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    """Terminate (then kill) a subprocess that may still be running."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
        return
    except (OSError, subprocess.SubprocessError) as exc:
        log_best_effort_failure(
            logger,
            "terminate review subprocess before kill fallback",
            exc,
        )
    try:
        process.kill()
        process.wait(timeout=3)
    except (OSError, subprocess.SubprocessError):
        return


def _drain_stream(stream, sink: list[str], state: _RunnerState) -> None:
    """Read lines from *stream* into *sink*, updating activity timestamp."""
    if stream is None:
        return
    try:
        for chunk in iter(stream.readline, ""):
            if not chunk:
                break
            with state.lock:
                sink.append(chunk)
                state.last_stream_activity = time.monotonic()
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive boundary
        with state.lock:
            sink.append(f"\n[stream read error: {exc}]\n")
    finally:
        try:
            stream.close()
        except (OSError, ValueError) as exc:
            log_best_effort_failure(logger, "close review batch stream", exc)


def _write_live_snapshot(state: _RunnerState, ctx: _AttemptContext) -> None:
    """Write a point-in-time log snapshot while the runner is active."""
    elapsed_seconds = int(max(0.0, time.monotonic() - ctx.started_monotonic))
    with state.lock:
        stdout_preview = "".join(state.stdout_chunks)
        stderr_preview = "".join(state.stderr_chunks)
        note = state.runner_note
    note_block = f"\nRUNNER NOTE: {note}" if note else ""
    ctx.safe_write_text_fn(
        ctx.log_file,
        "\n\n".join(
            ctx.log_sections
            + [
                (
                    f"{ctx.header}\n\n"
                    "STATUS: running\n"
                    f"STARTED AT: {ctx.started_at_iso}\n"
                    f"ELAPSED: {elapsed_seconds}s\n"
                    f"OUTPUT FILE: {_output_file_status_text(ctx.output_file)}"
                    f"{note_block}\n\n"
                    f"STDOUT (live):\n{stdout_preview}\n\n"
                    f"STDERR (live):\n{stderr_preview}\n"
                )
            ]
        ),
    )


def _start_live_writer(
    state: _RunnerState,
    ctx: _AttemptContext,
    interval: float,
) -> threading.Thread:
    """Spawn a daemon thread that periodically writes live log snapshots."""

    def _loop() -> None:
        while not state.stop_event.wait(interval):
            _write_live_snapshot(state, ctx)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread


def _check_stall(
    output_file: Path,
    prev_sig: tuple[int, int] | None,
    prev_stable: float | None,
    now: float,
    last_activity: float,
    threshold: int,
) -> tuple[bool, tuple[int, int] | None, float | None]:
    """Check for runner stall. Returns (stalled, new_sig, new_stable_since).

    When no output artifact exists yet the batch is still initialising — the
    stall detector must not declare a stall.  The caller already enforces the
    real timeout, so batches that never produce output will still be killed;
    they just won't be killed *early* by the stall heuristic.
    """
    try:
        stat = output_file.stat()
        current_signature: tuple[int, int] | None = (
            int(stat.st_size),
            int(stat.st_mtime),
        )
    except OSError:
        current_signature = None
    if current_signature is None:
        # No output file yet — the batch hasn't started writing.  Never
        # declare a stall in this state; just carry forward the baseline
        # timestamp so that once the file *does* appear, we start fresh.
        baseline = prev_stable if isinstance(prev_stable, int | float) else now
        return False, None, baseline
    if current_signature != prev_sig:
        return False, current_signature, now
    if prev_stable is None:
        return False, prev_sig, prev_stable
    output_age = now - prev_stable
    stream_idle = now - last_activity
    if output_age >= threshold and stream_idle >= threshold:
        return True, prev_sig, prev_stable
    return False, prev_sig, prev_stable


__all__ = [
    "_check_stall",
    "_drain_stream",
    "extract_payload_from_log",
    "_output_file_has_json_payload",
    "_output_file_status_text",
    "_start_live_writer",
    "_terminate_process",
    "_write_live_snapshot",
]
