"""Failure classification and reporting for review batch runner execution."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from desloppify.base.exception_sets import CommandError, RunnerTimeoutError
from desloppify.base.output.fallbacks import log_best_effort_failure

logger = logging.getLogger(__name__)

TRANSIENT_RUNNER_PHRASES = (
    "stream disconnected before completion",
    "error sending request for url",
    "connection reset by peer",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "network is unreachable",
    "connection refused",
    "timed out while",
    "no last agent message; wrote empty content",
)
_USAGE_LIMIT_PHRASES = (
    "you've hit your usage limit",
    "you have hit your usage limit",
    "codex/settings/usage",
)
_CODEX_BACKEND_PATH_HINT = "/backend-api/codex/responses"
_CODEX_BACKEND_HOST_HINT = "chatgpt.com"
_SANDBOX_PATH_WARNING_PHRASES = (
    "could not update path: operation not permitted",
    "operation not permitted (os error 1)",
)
_RUNNER_AUTH_PHRASES = (
    "not authenticated",
    "authentication failed",
    "unauthorized",
    "forbidden",
    "login required",
    "please login",
    "access token",
)
_FAILURE_HINT_BY_CATEGORY = {
    "runner_missing": (
        "Runner CLI not found on PATH. "
        "Install the runner (codex or opencode) and verify it is on your PATH."
    ),
    "runner_auth": (
        "Runner appears unauthenticated. "
        "For Codex run `codex login`; for OpenCode check your auth configuration."
    ),
    "usage_limit": (
        "Runner usage quota is exhausted for this account. "
        "Wait for reset or add credits, then rerun failed batches."
    ),
    "stream_disconnect": (
        "Transient runner connectivity issue detected. Retry with "
        "`--batch-max-retries 2 --batch-retry-backoff-seconds 2` and, if needed, "
        "lower concurrency via `--max-parallel-batches 1`."
    ),
}


def _is_runner_missing(text: str) -> bool:
    for runner_name in ("codex", "opencode"):
        if f"{runner_name} not found" in text:
            return True
        if "no such file or directory" in text and f"$ {runner_name} " in text:
            return True
        if "errno 2" in text and runner_name in text:
            return True
    return False


def _is_runner_auth_failure(text: str) -> bool:
    return any(phrase in text for phrase in _RUNNER_AUTH_PHRASES)


def _normalize_runner_failure_text(log_text: str) -> str:
    """Normalize runner logs for resilient failure phrase matching."""
    return log_text.casefold().replace("’", "'").replace("`", "'")


def _is_usage_limit_failure(text: str) -> bool:
    """Return True when normalized failure text indicates account quota/usage limit.

    Beyond the exact phrases in ``_USAGE_LIMIT_PHRASES``, this catches variant
    wording that includes "usage limit" alongside retry/admin guidance.

    Credit: Valeriy Pavlovich (@iqdoctor) — see PR #175.
    """
    if any(phrase in text for phrase in _USAGE_LIMIT_PHRASES):
        return True
    if "usage limit" not in text:
        return False
    return (
        "try again at" in text
        or "send a request to your admin" in text
        or "more access now" in text
    )


def classify_runner_failure(log_text: str) -> str:
    """Classify batch failure type from log contents."""
    text = _normalize_runner_failure_text(log_text)
    if "timeout after" in text:
        return "timeout"
    if _is_usage_limit_failure(text):
        return "usage_limit"
    if any(phrase in text for phrase in TRANSIENT_RUNNER_PHRASES):
        return "stream_disconnect"
    if _is_runner_missing(text):
        return "runner_missing"
    if _is_runner_auth_failure(text):
        return "runner_auth"
    if "runner exception" in text:
        return "runner_exception"
    return "unknown"


def has_codex_backend_connectivity_issue(log_text: str) -> bool:
    """Return True when logs indicate Codex backend URL is unreachable."""
    text = _normalize_runner_failure_text(log_text)
    if "error sending request for url" not in text:
        return False
    return (
        _CODEX_BACKEND_PATH_HINT in text
        or _CODEX_BACKEND_HOST_HINT in text
        or "nodename nor servname provided" in text
        or "name or service not known" in text
        or "temporary failure in name resolution" in text
    )


def looks_like_restricted_sandbox(log_text: str) -> bool:
    """Return True when logs resemble a constrained agent sandbox execution."""
    text = _normalize_runner_failure_text(log_text)
    return any(phrase in text for phrase in _SANDBOX_PATH_WARNING_PHRASES)


def summarize_failure_categories(
    *, failures: list[int], logs_dir: Path
) -> dict[str, int]:
    """Return counts by failure category for failed batches."""
    categories: dict[str, int] = {}
    for idx in sorted(set(failures)):
        log_file = logs_dir / f"batch-{idx + 1}.log"
        if not log_file.exists():
            category = "missing_log"
        else:
            try:
                category = classify_runner_failure(
                    log_file.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                category = "log_read_error"
        categories[category] = categories.get(category, 0) + 1
    return categories


def _append_unique_hint(hints: list[str], hint: str | None) -> None:
    if not hint or hint in hints:
        return
    hints.append(hint)


def _connectivity_hints(text: str) -> list[str]:
    if not has_codex_backend_connectivity_issue(text):
        return []
    hints = [
        "Runner cannot reach its backend from this environment. "
        "Check outbound HTTPS/DNS/proxy access, or use cloud fallback: "
        "`desloppify review --external-start --external-runner claude`."
    ]
    if looks_like_restricted_sandbox(text):
        hints.append(
            "Logs suggest the run executed in a restricted sandbox "
            "(`could not update PATH: Operation not permitted`). "
            "Re-run `desloppify review --run-batches ...` from a host shell with "
            "outbound network access, or allow unsandboxed execution in your agent."
        )
    return hints


def _skill_file_hint(text: str) -> str | None:
    if "failed to load skill" not in text or "missing yaml frontmatter" not in text:
        return None
    return (
        "Runner loaded an invalid local skill file. Fix/remove malformed "
        "SKILL.md entries under the runner's skill directory to reduce noise."
    )


def runner_failure_hints(*, failures: list[int], logs_dir: Path) -> list[str]:
    """Infer common runner environment failures from batch logs."""
    hints: list[str] = []
    for idx in sorted(set(failures)):
        log_file = logs_dir / f"batch-{idx + 1}.log"
        raw = ""
        try:
            raw = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log_best_effort_failure(
                logger,
                f"read review batch log {log_file.name} for hints",
                exc,
            )
            continue
        if not raw:
            continue
        text = _normalize_runner_failure_text(raw)
        category = classify_runner_failure(text)
        _append_unique_hint(hints, _FAILURE_HINT_BY_CATEGORY.get(category))
        for hint in _connectivity_hints(text):
            _append_unique_hint(hints, hint)
        _append_unique_hint(hints, _skill_file_hint(text))
    return hints


def any_restricted_sandbox_failures(*, failures: list[int], logs_dir: Path) -> bool:
    """Return True when any failed batch log shows restricted sandbox indicators."""
    for idx in sorted(set(failures)):
        log_file = logs_dir / f"batch-{idx + 1}.log"
        text = ""
        try:
            text = _normalize_runner_failure_text(
                log_file.read_text(encoding="utf-8", errors="replace")
            )
        except OSError as exc:
            log_best_effort_failure(
                logger,
                f"read review batch log {log_file.name} for sandbox checks",
                exc,
            )
            continue
        if not text:
            continue
        if looks_like_restricted_sandbox(text):
            return True
    return False


def _print_failures_report(
    *,
    failures: list[int],
    packet_path: Path,
    logs_dir: Path,
    colorize_fn,
) -> None:
    """Render retry guidance for failed batches."""
    failed_1 = sorted({idx + 1 for idx in failures})
    failed_csv = ",".join(str(i) for i in failed_1)
    print(colorize_fn(f"\n  Failed batches: {failed_1}", "red"), file=sys.stderr)
    categories = summarize_failure_categories(failures=failures, logs_dir=logs_dir)
    if categories:
        labels = {
            "timeout": "timeout",
            "stream_disconnect": "stream disconnect",
            "usage_limit": "usage limit",
            "runner_missing": "runner missing",
            "runner_auth": "runner auth",
            "runner_exception": "runner exception",
            "missing_log": "missing log",
            "log_read_error": "log read error",
            "unknown": "unknown",
        }
        category_segments = [
            f"{labels.get(name, name)}={count}"
            for name, count in sorted(categories.items())
        ]
        print(
            colorize_fn(
                f"  Failure categories: {', '.join(category_segments)}",
                "yellow",
            ),
            file=sys.stderr,
        )
        if categories.get("timeout", 0) > 0:
            print(
                colorize_fn(
                    "  Timeout tuning: lower concurrency with `--max-parallel-batches 1..3` "
                    "or increase `--batch-timeout-seconds` for long-running reviews.",
                    "yellow",
                ),
                file=sys.stderr,
            )
        if categories.get("stream_disconnect", 0) > 0:
            print(
                colorize_fn(
                    "  Connectivity tuning: enable retries with `--batch-max-retries 2` "
                    "and `--batch-retry-backoff-seconds 2`, then retry failed batches.",
                    "yellow",
                ),
                file=sys.stderr,
            )
            if any_restricted_sandbox_failures(failures=failures, logs_dir=logs_dir):
                print(
                    colorize_fn(
                        "  Sandbox hint: logs indicate restricted sandbox execution. "
                        "Re-run from a host shell with outbound network access, or "
                        "allow unsandboxed execution in your agent.",
                        "yellow",
                    ),
                    file=sys.stderr,
                )
    print(colorize_fn("  Retry command:", "yellow"), file=sys.stderr)
    print(
        colorize_fn(
            f"    desloppify review --run-batches --packet {packet_path} --only-batches {failed_csv}",
            "yellow",
        ),
        file=sys.stderr,
    )
    for idx_1 in failed_1:
        log_file = logs_dir / f"batch-{idx_1}.log"
        print(colorize_fn(f"    log: {log_file}", "dim"), file=sys.stderr)
    hints = runner_failure_hints(failures=failures, logs_dir=logs_dir)
    if hints:
        print(colorize_fn("  Environment hints:", "yellow"), file=sys.stderr)
        for hint in hints:
            print(colorize_fn(f"    {hint}", "dim"), file=sys.stderr)


def print_failures(
    *,
    failures: list[int],
    packet_path: Path,
    logs_dir: Path,
    colorize_fn,
) -> None:
    """Render retry guidance for failed batches without exiting."""
    normalized_failures = sorted({int(idx) for idx in failures})
    if not normalized_failures:
        print(colorize_fn("  Failed batches: []", "yellow"), file=sys.stderr)
        return
    _print_failures_report(
        failures=normalized_failures,
        packet_path=packet_path,
        logs_dir=logs_dir,
        colorize_fn=colorize_fn,
    )


def print_failures_and_raise(
    *,
    failures: list[int],
    packet_path: Path,
    logs_dir: Path,
    colorize_fn,
) -> None:
    """Render retry guidance for failed batches and raise CommandError."""
    if not failures:
        print(colorize_fn("  Failed batches: []", "yellow"), file=sys.stderr)
    _print_failures_report(
        failures=failures,
        packet_path=packet_path,
        logs_dir=logs_dir,
        colorize_fn=colorize_fn,
    )
    failed_1 = sorted({idx + 1 for idx in failures})
    categories = summarize_failure_categories(failures=failures, logs_dir=logs_dir)
    timeout_count = categories.get("timeout", 0)
    if timeout_count > 0 and timeout_count == sum(categories.values()):
        raise RunnerTimeoutError(f"batch execution failed: {failed_1}", exit_code=1)
    raise CommandError(f"batch execution failed: {failed_1}", exit_code=1)


__all__ = [
    "TRANSIENT_RUNNER_PHRASES",
    "any_restricted_sandbox_failures",
    "classify_runner_failure",
    "has_codex_backend_connectivity_issue",
    "looks_like_restricted_sandbox",
    "print_failures",
    "print_failures_and_raise",
    "runner_failure_hints",
    "summarize_failure_categories",
]
