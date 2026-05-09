"""Rovo Dev (acli rovodev) batch runner for review batch execution.

Rovo Dev's CLI (``acli rovodev``) enters non-interactive single-prompt
mode automatically whenever a positional ``message`` argument is
provided. The runner invokes::

    acli rovodev --yolo "<instruction>"

``--yolo`` disables permission prompts so the agent can write the
per-batch output file unattended; opt out by setting
``DESLOPPIFY_ROVODEV_NO_YOLO=1`` (only useful in interactive review work
since batch runs cannot answer prompts).

Unlike codex/opencode the CLI does not stream a structured NDJSON envelope
of the model's reply; instead, the agent operates inside the workspace and
follows the prompt's own instructions. Our review prompt explicitly tells
the agent to ``write ONLY valid JSON to <output_file>``, so the file
written by the agent is the canonical payload.

The runner mirrors :mod:`runner_opencode` for stdout-payload recovery so
that callers still get a usable file when the agent emits the JSON
inline (e.g. when permission checks block the file write but the JSON
is still in the agent's reply).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from desloppify.app.commands.runner.codex_batch import (
    CodexBatchRunnerDeps,
    _resolve_executable,
    _wrap_cmd_c,
)

from .runner_process_impl.attempts import (
    handle_early_attempt_return as _handle_early_attempt_return,
    handle_failed_attempt as _handle_failed_attempt,
    handle_successful_attempt as _handle_successful_attempt,
    handle_timeout_or_stall as _handle_timeout_or_stall,
    resolve_retry_config as _resolve_retry_config,
    run_batch_attempt as _run_batch_attempt,
)
from .runner_process_impl.io import _output_file_has_json_payload


def rovodev_batch_command(*, prompt: str, repo_root: Path) -> list[str]:
    """Build one ``acli rovodev`` command line for a batch prompt.

    ``acli rovodev`` enters non-interactive mode automatically whenever a
    positional ``message`` is provided, so no explicit ``--non-interactive``
    flag is needed. Permission checks are disabled by default via ``--yolo``
    so the agent can write the per-batch output file without prompting; set
    ``DESLOPPIFY_ROVODEV_NO_YOLO=1`` to opt out.

    Honours optional environment overrides:

    - ``DESLOPPIFY_ROVODEV_EXECUTABLE`` overrides the ``acli`` executable
      name (useful when the binary is shipped under a different name in CI).
    - ``DESLOPPIFY_ROVODEV_NO_YOLO=1`` disables the default ``--yolo`` flag
      so the agent will request per-tool permission (only useful in
      interactive review work — batch runs cannot answer prompts).
    - ``DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA`` may be either an inline JSON
      schema string or a path to a schema file; when set, it's passed via
      ``--output-schema`` so the agent's reply is constrained to the
      schema. Combine with the desloppify review JSON contract for
      strictly-shaped batch results.
    - ``DESLOPPIFY_ROVODEV_EXTRA_ARGS`` is shell-split and appended verbatim
      before the prompt, allowing power users to pass ``--config-override``,
      ``--restore``, ``--worktree``, etc. without code changes.

    The repo root is set as the subprocess working directory by the
    surrounding ``run_batch_attempt`` infrastructure (Rovo Dev operates
    on the current working directory).
    """
    del repo_root  # cwd is set by the caller via the deps subprocess machinery
    executable = os.environ.get("DESLOPPIFY_ROVODEV_EXECUTABLE", "").strip() or "acli"
    prefix = _resolve_executable(executable)
    cmd: list[str] = [*prefix, "rovodev"]
    if os.environ.get("DESLOPPIFY_ROVODEV_NO_YOLO", "").strip() not in {"1", "true", "yes"}:
        cmd.append("--yolo")
    schema = os.environ.get("DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA", "").strip()
    if schema:
        cmd.extend(["--output-schema", schema])
    extra = os.environ.get("DESLOPPIFY_ROVODEV_EXTRA_ARGS", "").strip()
    if extra:
        import shlex

        cmd.extend(shlex.split(extra))
    cmd.append(prompt)
    return _wrap_cmd_c(cmd)


def _capture_rovodev_stdout_payload(
    *, result, output_file: Path, deps: CodexBatchRunnerDeps
) -> str | None:
    """Persist a recoverable JSON payload found in Rovo Dev stdout text."""
    return _persist_rovodev_payload_text(
        extracted_text=result.stdout_text,
        output_file=output_file,
        deps=deps,
    )


def _extract_json_object(text: str) -> str | None:
    """Return the last brace-balanced JSON object substring in ``text``.

    Rovo Dev does not emit NDJSON like OpenCode; the model's reply is
    plain text that may contain narration around the JSON payload. We
    walk the text and return the *last* fully balanced object so the
    final answer wins over any earlier draft inside the same response.
    """
    if not text:
        return None
    last: str | None = None
    depth = 0
    start = -1
    in_string = False
    escape = False
    for idx, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : idx + 1]
                try:
                    parsed = json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    start = -1
                    continue
                if isinstance(parsed, dict):
                    last = candidate
                start = -1
    return last


def _persist_rovodev_payload_text(
    *, extracted_text: str, output_file: Path, deps: CodexBatchRunnerDeps
) -> str | None:
    """Persist a Rovo Dev JSON payload to ``output_file`` if recoverable."""
    if not extracted_text:
        return None
    candidate = _extract_json_object(extracted_text)
    if candidate is None:
        return None
    try:
        deps.safe_write_text_fn(output_file, candidate)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return candidate


def _build_live_rovodev_stdout_observer(
    *, output_file: Path, deps: CodexBatchRunnerDeps
):
    """Persist recoverable Rovo Dev payloads while stdout is still streaming."""
    last_persisted_text: str | None = None

    def _observe(stdout_text: str) -> None:
        nonlocal last_persisted_text
        if not stdout_text or stdout_text == last_persisted_text:
            return
        persisted_text = _persist_rovodev_payload_text(
            extracted_text=stdout_text,
            output_file=output_file,
            deps=deps,
        )
        if persisted_text is not None:
            last_persisted_text = stdout_text

    return _observe


def _restore_rovodev_recoverable_payload(
    *, recoverable_text: str | None, output_file: Path, deps: CodexBatchRunnerDeps
) -> None:
    """Restore the last known-good Rovo Dev payload for downstream recovery."""
    if not recoverable_text or _output_file_has_json_payload(output_file):
        return
    try:
        deps.safe_write_text_fn(output_file, recoverable_text)
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def run_rovodev_batch(
    *,
    prompt: str,
    repo_root: Path,
    output_file: Path,
    log_file: Path,
    deps: CodexBatchRunnerDeps,
    rovodev_batch_command_fn=None,
) -> int:
    """Execute one Rovo Dev batch and return a stable CLI-style status code.

    Mirrors :func:`run_opencode_batch` to reuse the shared retry/stall/
    timeout infrastructure. The Rovo Dev agent is expected to follow the
    prompt's instruction to write JSON to ``output_file``; if it instead
    emits JSON inline, the runner recovers the payload from stdout.
    """
    if rovodev_batch_command_fn is None:
        rovodev_batch_command_fn = rovodev_batch_command
    cmd = rovodev_batch_command_fn(
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

        stdout_text_observer = _build_live_rovodev_stdout_observer(
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

        current_payload_text = _capture_rovodev_stdout_payload(
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
            _restore_rovodev_recoverable_payload(
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
            _restore_rovodev_recoverable_payload(
                recoverable_text=recoverable_output_text,
                output_file=output_file,
                deps=deps,
            )
            return failure_code

    _restore_rovodev_recoverable_payload(
        recoverable_text=recoverable_output_text,
        output_file=output_file,
        deps=deps,
    )
    deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
    return 1


__all__ = [
    "rovodev_batch_command",
    "run_rovodev_batch",
]
