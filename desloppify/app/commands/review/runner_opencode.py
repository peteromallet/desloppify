"""OpenCode batch runner for review batch execution."""

from __future__ import annotations

import json
import os
from pathlib import Path

from desloppify.app.commands.runner.codex_batch import CodexBatchRunnerDeps

from .runner_process_impl.attempts import (
    handle_early_attempt_return as _handle_early_attempt_return,
    handle_failed_attempt as _handle_failed_attempt,
    handle_successful_attempt as _handle_successful_attempt,
    handle_timeout_or_stall as _handle_timeout_or_stall,
    resolve_retry_config as _resolve_retry_config,
    run_batch_attempt as _run_batch_attempt,
)
from .runner_process_impl.io import (
    _extract_text_from_opencode_json_stream,
    _output_file_has_json_payload,
)


def opencode_batch_command(*, prompt: str, repo_root: Path) -> list[str]:
    """Build one ``opencode run`` command line for a batch prompt."""
    cmd = ["opencode", "run", "--format", "json"]
    model = os.environ.get("DESLOPPIFY_OPENCODE_MODEL", "").strip()
    if model:
        cmd.extend(["--model", model])
    variant = os.environ.get("DESLOPPIFY_OPENCODE_VARIANT", "").strip()
    if variant:
        cmd.extend(["--variant", variant])
    attach_url = os.environ.get("DESLOPPIFY_OPENCODE_ATTACH", "").strip()
    if attach_url:
        cmd.extend(["--attach", attach_url])
    cmd.extend(["--dir", str(repo_root)])
    cmd.append(prompt)
    return cmd


def _capture_opencode_stdout_payload(
    *, result, output_file: Path, deps: CodexBatchRunnerDeps
) -> str | None:
    """Extract and persist a recoverable OpenCode payload from NDJSON stdout."""
    extracted_text = _extract_text_from_opencode_json_stream(result.stdout_text)
    return _persist_opencode_payload_text(
        extracted_text=extracted_text,
        output_file=output_file,
        deps=deps,
    )


def _persist_opencode_payload_text(
    *, extracted_text: str, output_file: Path, deps: CodexBatchRunnerDeps
) -> str | None:
    """Persist OpenCode output only when it is a complete JSON object."""
    normalized_text = extracted_text.strip()
    if not normalized_text:
        return None
    try:
        payload = json.loads(normalized_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        deps.safe_write_text_fn(output_file, normalized_text)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return normalized_text


def _build_live_opencode_stdout_observer(
    *, output_file: Path, deps: CodexBatchRunnerDeps
):
    """Persist recoverable OpenCode payloads while stdout is still streaming."""
    last_persisted_text: str | None = None

    def _observe(stdout_text: str) -> None:
        nonlocal last_persisted_text
        extracted_text = _extract_text_from_opencode_json_stream(stdout_text)
        normalized_text = extracted_text.strip()
        if not normalized_text or normalized_text == last_persisted_text:
            return
        persisted_text = _persist_opencode_payload_text(
            extracted_text=normalized_text,
            output_file=output_file,
            deps=deps,
        )
        if persisted_text is not None:
            last_persisted_text = persisted_text

    return _observe


def _restore_opencode_recoverable_payload(
    *, recoverable_text: str | None, output_file: Path, deps: CodexBatchRunnerDeps
) -> None:
    """Restore the last known-good OpenCode payload for downstream recovery."""
    if not recoverable_text or _output_file_has_json_payload(output_file):
        return
    try:
        deps.safe_write_text_fn(output_file, recoverable_text)
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def run_opencode_batch(
    *,
    prompt: str,
    repo_root: Path,
    output_file: Path,
    log_file: Path,
    deps: CodexBatchRunnerDeps,
    opencode_batch_command_fn=None,
) -> int:
    """Execute one OpenCode batch and return a stable CLI-style status code."""
    if opencode_batch_command_fn is None:
        opencode_batch_command_fn = opencode_batch_command
    cmd = opencode_batch_command_fn(
        prompt=prompt,
        repo_root=repo_root,
    )
    config = _resolve_retry_config(deps)
    log_sections: list[str] = []
    recoverable_output_text: str | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            if output_file.exists():
                output_file.unlink()
        except OSError:
            pass

        stdout_text_observer = _build_live_opencode_stdout_observer(
            output_file=output_file,
            deps=deps,
        )

        header, result = _run_batch_attempt(
            cmd=cmd,
            deps=deps,
            output_file=output_file,
            log_file=log_file,
            log_sections=log_sections,
            attempt=attempt,
            max_attempts=config.max_attempts,
            use_popen=config.use_popen,
            live_log_interval=config.live_log_interval,
            stall_seconds=config.stall_seconds,
            stdout_text_observer=stdout_text_observer,
        )
        early_return = _handle_early_attempt_return(result)
        if early_return is not None:
            return early_return

        current_payload_text = _capture_opencode_stdout_payload(
            result=result,
            output_file=output_file,
            deps=deps,
        )
        if current_payload_text is not None:
            recoverable_output_text = current_payload_text

        timeout_or_stall = _handle_timeout_or_stall(
            header=header,
            result=result,
            deps=deps,
            output_file=output_file,
            log_file=log_file,
            log_sections=log_sections,
            stall_seconds=config.stall_seconds,
        )
        if timeout_or_stall is not None:
            if timeout_or_stall == 0:
                return 0
            if attempt < config.max_attempts:
                delay = config.retry_backoff_seconds * (2 ** (attempt - 1))
                log_sections.append(
                    f"Timeout/stall on attempt {attempt}/{config.max_attempts}; "
                    f"retrying in {delay:.1f}s."
                )
                if delay > 0:
                    deps.sleep_fn(delay)
                continue
            _restore_opencode_recoverable_payload(
                recoverable_text=recoverable_output_text,
                output_file=output_file,
                deps=deps,
            )
            return timeout_or_stall

        log_sections.append(
            f"{header}\n\nSTDOUT:\n{result.stdout_text}\n\nSTDERR:\n{result.stderr_text}\n"
        )

        success_code = _handle_successful_attempt(
            result=result,
            output_file=output_file,
            log_file=log_file,
            deps=deps,
            log_sections=log_sections,
        )
        if success_code is not None:
            return success_code

        failure_code = _handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=attempt,
            max_attempts=config.max_attempts,
            retry_backoff_seconds=config.retry_backoff_seconds,
            log_file=log_file,
            log_sections=log_sections,
        )
        if failure_code is not None:
            _restore_opencode_recoverable_payload(
                recoverable_text=recoverable_output_text,
                output_file=output_file,
                deps=deps,
            )
            return failure_code

    _restore_opencode_recoverable_payload(
        recoverable_text=recoverable_output_text,
        output_file=output_file,
        deps=deps,
    )
    deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
    return 1


__all__ = [
    "opencode_batch_command",
    "run_opencode_batch",
]
