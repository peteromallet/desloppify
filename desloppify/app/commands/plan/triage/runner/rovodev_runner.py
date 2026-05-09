"""Thin wrapper around the Rovo Dev batch runner for triage stage execution.

Mirrors :mod:`codex_runner` so the triage pipeline can swap the underlying
subprocess runner without changes to the stage orchestration logic.
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
from collections.abc import Callable
from pathlib import Path

from desloppify.app.commands.review.runner_rovodev import (
    rovodev_batch_command,
    run_rovodev_batch,
)
from desloppify.app.commands.runner.codex_batch import CodexBatchRunnerDeps
from desloppify.base.discovery.file_paths import safe_write_text

from .codex_runner import TriageStageRunResult, _output_file_has_text


def run_triage_stage_rovodev(
    *,
    prompt: str,
    repo_root: Path,
    output_file: Path,
    log_file: Path,
    timeout_seconds: int = 1800,
    validate_output_fn: Callable[[Path], bool] | None = None,
) -> TriageStageRunResult:
    """Execute one triage stage via ``acli rovodev`` and return a typed result.

    Shape-compatible with :func:`codex_runner.run_triage_stage` so the
    surrounding pipeline can dispatch on a per-runner basis without any
    pipeline-side awareness of the runner backend.
    """
    normalized_prompt = str(prompt).strip()
    if not normalized_prompt:
        safe_write_text(log_file, "Empty triage prompt — skipping execution.\n")
        return TriageStageRunResult(exit_code=2, reason="empty_prompt")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if validate_output_fn is None:
        validate_output_fn = _output_file_has_text
    timeout = timeout_seconds if timeout_seconds > 0 else 1800
    preview = " ".join(
        rovodev_batch_command(
            prompt=normalized_prompt,
            repo_root=repo_root,
        )
    )
    safe_write_text(log_file, f"RUNNER COMMAND PREVIEW:\n{preview}\n")
    deps = CodexBatchRunnerDeps(
        timeout_seconds=timeout,
        subprocess_run=subprocess.run,
        timeout_error=subprocess.TimeoutExpired,
        safe_write_text_fn=safe_write_text,
        use_popen_runner=True,
        subprocess_popen=subprocess.Popen,
        live_log_interval_seconds=10.0,
        stall_after_output_seconds=120,
        max_retries=1,
        retry_backoff_seconds=5.0,
        sleep_fn=time.sleep,
        validate_output_fn=validate_output_fn,
    )
    exit_code = run_rovodev_batch(
        prompt=normalized_prompt,
        repo_root=repo_root,
        output_file=output_file,
        log_file=log_file,
        deps=deps,
    )
    reason = None if exit_code == 0 else f"runner_exit_{exit_code}"
    return TriageStageRunResult(exit_code=exit_code, reason=reason)


__all__ = ["run_triage_stage_rovodev"]
