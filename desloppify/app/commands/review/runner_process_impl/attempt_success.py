"""Success-path output validation helpers for review batch attempts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from .types import BatchRunnerDeps, _ExecutionResult

logger = logging.getLogger(__name__)


DefValidateFn = Callable[[Path], bool]


def handle_successful_attempt_core(
    *,
    result: _ExecutionResult,
    output_file: Path,
    log_file: Path,
    deps: BatchRunnerDeps,
    log_sections: list[str],
    default_validate_fn: DefValidateFn,
    monotonic_fn: Callable[[], float],
) -> int | None:
    """Validate successful run output and handle delayed/fallback writes."""
    if result.code != 0:
        return None

    validate = deps.validate_output_fn or default_validate_fn
    valid = validate(output_file)
    valid, grace_wait_used = _validate_with_grace_wait(
        valid,
        output_file=output_file,
        deps=deps,
        validate=validate,
        monotonic_fn=monotonic_fn,
    )
    valid = _recover_output_from_fallback_text(
        valid,
        result=result,
        output_file=output_file,
        deps=deps,
        validate=validate,
        log_sections=log_sections,
    )

    if not valid:
        log_sections.append(
            "Runner exited 0 but output file is missing or invalid; "
            "treating as execution failure."
        )
        deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
        return 1

    if grace_wait_used:
        log_sections.append(
            "Runner output validation passed after grace wait for delayed file write."
        )

    deps.safe_write_text_fn(log_file, "\n\n".join(log_sections))
    return 0


def _validation_timing(deps: CodexBatchRunnerDeps) -> tuple[float, float]:
    grace_raw = getattr(deps, "output_validation_grace_seconds", 0.0)
    poll_raw = getattr(deps, "output_validation_poll_seconds", 0.1)
    try:
        grace_seconds = max(0.0, float(grace_raw))
    except (TypeError, ValueError):
        grace_seconds = 0.0
    try:
        poll_seconds = max(0.01, float(poll_raw))
    except (TypeError, ValueError):
        poll_seconds = 0.1
    return grace_seconds, poll_seconds


def _validate_with_grace_wait(
    valid: bool,
    *,
    output_file: Path,
    deps: CodexBatchRunnerDeps,
    validate: DefValidateFn,
    monotonic_fn: Callable[[], float],
) -> tuple[bool, bool]:
    if valid:
        return True, False
    grace_seconds, poll_seconds = _validation_timing(deps)
    if grace_seconds <= 0:
        return False, False
    deadline = monotonic_fn() + grace_seconds
    while monotonic_fn() < deadline:
        remaining = deadline - monotonic_fn()
        sleep_for = min(poll_seconds, max(0.0, remaining))
        if sleep_for <= 0:
            break
        try:
            deps.sleep_fn(sleep_for)
        except (OSError, RuntimeError, ValueError, TypeError):
            break
        if validate(output_file):
            return True, True
    return False, True


def _recover_output_from_fallback_text(
    valid: bool,
    *,
    result: _ExecutionResult,
    output_file: Path,
    deps: CodexBatchRunnerDeps,
    validate: DefValidateFn,
    log_sections: list[str],
) -> bool:
    if valid or deps.validate_output_fn is None:
        return valid
    fallback_text = (result.stdout_text or "").strip() or (
        result.stderr_text or ""
    ).strip()
    if not fallback_text:
        return False
    try:
        deps.safe_write_text_fn(output_file, fallback_text)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.debug(
            "Failed writing fallback runner output to %s: %s",
            output_file,
            exc,
        )
        return False
    if not validate(output_file):
        return False
    log_sections.append("Runner output recovered from stdout/stderr fallback text.")
    return True


__all__ = ["handle_successful_attempt_core"]
