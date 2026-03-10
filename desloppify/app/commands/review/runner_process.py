"""Subprocess-oriented runner helpers for review batch execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .runner_process_impl.attempts import (
    handle_early_attempt_return,
    handle_failed_attempt,
    handle_successful_attempt,
    handle_timeout_or_stall,
    resolve_retry_config,
    run_batch_attempt,
)
from .runner_process_impl.types import (
    CodexBatchRunnerDeps,
    FollowupScanDeps,
)


def codex_batch_command(*, prompt: str, repo_root: Path, output_file: Path) -> list[str]:
    """Build one codex exec command line for a batch prompt."""
    effort = os.environ.get("DESLOPPIFY_CODEX_REASONING_EFFORT", "low").strip().lower()
    if effort not in {"low", "medium", "high", "xhigh"}:
        effort = "low"
    return [
        "codex",
        "exec",
        "--ephemeral",
        "-C",
        str(repo_root),
        "-s",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-o",
        str(output_file),
        prompt,
    ]


def run_codex_batch(
    *,
    prompt: str,
    repo_root: Path,
    output_file: Path,
    log_file: Path,
    deps: CodexBatchRunnerDeps,
    codex_batch_command_fn=None,
) -> int:
    """Execute one codex batch and return a stable CLI-style status code."""
    if codex_batch_command_fn is None:
        codex_batch_command_fn = codex_batch_command
    cmd = codex_batch_command_fn(
        prompt=prompt,
        repo_root=repo_root,
        output_file=output_file,
    )
    config = resolve_retry_config(deps)
    log_sections: list[str] = []

    for attempt in range(1, config.max_attempts + 1):
        header, result = run_batch_attempt(
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
        )
        early_return = handle_early_attempt_return(result)
        if early_return is not None:
            return early_return
        timeout_or_stall = handle_timeout_or_stall(
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
                return 0  # recovered from timeout/stall
            # Non-recovered timeout/stall: retry if attempts remain
            if attempt < config.max_attempts:
                delay = config.retry_backoff_seconds * (2 ** (attempt - 1))
                log_sections.append(
                    f"Timeout/stall on attempt {attempt}/{config.max_attempts}; "
                    f"retrying in {delay:.1f}s."
                )
                if delay > 0:
                    deps.sleep_fn(delay)
                continue
            return timeout_or_stall

        log_sections.append(
            f"{header}\n\nSTDOUT:\n{result.stdout_text}\n\nSTDERR:\n{result.stderr_text}\n"
        )

        success_code = handle_successful_attempt(
            result=result,
            output_file=output_file,
            log_file=log_file,
            deps=deps,
            log_sections=log_sections,
        )
        if success_code is not None:
            return success_code
        failure_code = handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=attempt,
            max_attempts=config.max_attempts,
            retry_backoff_seconds=config.retry_backoff_seconds,
            log_file=log_file,
            log_sections=log_sections,
        )
        if failure_code is not None:
            return failure_code

    deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
    return 1


def run_followup_scan(
    *,
    lang_name: str,
    scan_path: str,
    deps: FollowupScanDeps,
    force_queue_bypass: bool = False,
) -> int:
    """Run a follow-up scan and return a non-zero status when it fails."""
    scan_cmd = [
        deps.python_executable,
        "-m",
        "desloppify",
        "--lang",
        lang_name,
        "scan",
        "--path",
        scan_path,
    ]
    if force_queue_bypass:
        followup_attest = (
            "I understand this is not the intended workflow and "
            "I am intentionally skipping queue completion"
        )
        scan_cmd.extend(["--force-rescan", "--attest", followup_attest])
        print(
            deps.colorize_fn(
                "  Follow-up scan queue bypass enabled (--force-followup-scan).",
                "yellow",
            )
        )
    print(deps.colorize_fn("\n  Running follow-up scan...", "bold"))
    try:
        result = deps.subprocess_run(
            scan_cmd,
            cwd=str(deps.project_root),
            timeout=deps.timeout_seconds,
        )
    except deps.timeout_error:
        print(
            deps.colorize_fn(
                f"  Follow-up scan timed out after {deps.timeout_seconds}s.",
                "yellow",
            ),
            file=sys.stderr,
        )
        return 124
    except OSError as exc:
        print(
            deps.colorize_fn(f"  Follow-up scan failed: {exc}", "red"),
            file=sys.stderr,
        )
        return 1
    return int(getattr(result, "returncode", 0) or 0)


__all__ = [
    "CodexBatchRunnerDeps",
    "FollowupScanDeps",
    "codex_batch_command",
    "run_codex_batch",
    "run_followup_scan",
]
