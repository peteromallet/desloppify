"""OpenCode batch runner for review batch execution."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
    extract_text_from_opencode_json_stream,
    _output_file_has_json_payload,
)


def _resolve_opencode_prefix() -> tuple[list[str], bool]:
    """Resolve the opencode executable, handling Windows .cmd/.bat shims.

    On Windows, npm-installed CLIs are ``.cmd`` batch scripts that cannot be
    executed directly by ``subprocess`` without ``shell=True``.  They must be
    run through ``cmd /c``.  Because cmd.exe re-parses its arguments with its
    own tokeniser (breaking prompts that contain quotes, ``<``, ``>``, or
    ``&``), prompts are sent through stdin whenever the ``cmd /c`` wrapper is
    used — the second return value is True in that case.

    ``.exe`` binaries are invoked directly so their argv survives intact.
    """
    resolved = shutil.which("opencode")
    if sys.platform == "win32":
        if resolved is not None:
            if resolved.lower().endswith((".cmd", ".bat")):
                return (["cmd", "/c", resolved], True)
            return ([resolved], False)
        # shutil.which missed it — let cmd.exe resolve .cmd/.bat wrappers
        return (["cmd", "/c", "opencode"], True)
    return ([resolved or "opencode"], False)


def opencode_batch_command(*, prompt: str, repo_root: Path) -> list[str]:
    """Build one ``opencode run`` command line for a batch prompt."""
    prefix, prompt_via_stdin = _resolve_opencode_prefix()
    cmd = [*prefix, "run", "--format", "json"]
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
    if not prompt_via_stdin:
        cmd.append(prompt)
    if len(cmd) >= 3 and cmd[0].lower() == "cmd" and cmd[1].lower() == "/c":
        cmd = ["cmd", "/c", subprocess.list2cmdline(cmd[2:])]
    return cmd


def opencode_prompt_via_stdin(cmd: list[str]) -> bool:
    """Return True when the built command expects the prompt on stdin.

    The prompt is only omitted from argv when the ``cmd /c`` wrapper is in
    use (see :func:`_resolve_opencode_prefix`), so wrapper presence is the
    reliable marker.
    """
    return len(cmd) >= 3 and cmd[0].lower() == "cmd" and cmd[1].lower() == "/c"


def _capture_opencode_stdout_payload(
    *, result, output_file: Path, deps: CodexBatchRunnerDeps
) -> str | None:
    """Extract and persist a recoverable OpenCode payload from NDJSON stdout."""
    extracted_text = extract_text_from_opencode_json_stream(result.stdout_text)
    return _persist_opencode_payload_text(
        extracted_text=extracted_text,
        output_file=output_file,
        deps=deps,
    )


def _extract_json_payload_text(raw_text: str) -> str | None:
    """Normalise model output into a bare JSON object string, or None.

    Models frequently wrap the requested JSON in markdown fences or prefix it
    with a sentence of prose.  Strip fences first, then fall back to the
    outermost ``{...}`` slice of the text.
    """
    normalized_text = raw_text.strip()
    if not normalized_text:
        return None
    if normalized_text.startswith("```") and normalized_text.endswith("```"):
        first_newline = normalized_text.find("\n")
        if first_newline != -1:
            normalized_text = normalized_text[first_newline + 1 : -3].strip()
    try:
        json.loads(normalized_text)
        return normalized_text
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    first_brace = normalized_text.find("{")
    last_brace = normalized_text.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        return None
    candidate = normalized_text[first_brace : last_brace + 1]
    try:
        json.loads(candidate)
        return candidate
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _persist_opencode_payload_text(
    *, extracted_text: str, output_file: Path, deps: CodexBatchRunnerDeps
) -> str | None:
    """Persist OpenCode output only when it is a complete JSON object."""
    payload_text = _extract_json_payload_text(extracted_text)
    if payload_text is None:
        return None
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        return None
    try:
        deps.safe_write_text_fn(output_file, payload_text)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return payload_text


def _build_live_opencode_stdout_observer(
    *, output_file: Path, deps: CodexBatchRunnerDeps
):
    """Persist recoverable OpenCode payloads while stdout is still streaming."""
    last_persisted_text: str | None = None

    def _observe(stdout_text: str) -> None:
        nonlocal last_persisted_text
        extracted_text = extract_text_from_opencode_json_stream(stdout_text)
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
    stdin_text = prompt if opencode_prompt_via_stdin(cmd) else None
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
            stdin_text=stdin_text,
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
    "opencode_prompt_via_stdin",
    "run_opencode_batch",
]
