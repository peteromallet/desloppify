"""Tests for review runner internals: process I/O, retry logic, parallel execution.

Covers the pure-logic functions in:
- runner_process_impl.io.py     (payload extraction, stall detection, output file helpers)
- runner_process_impl.attempts.py (retry config resolution, attempt handler helpers)
- runner_parallel.execution.py (parallel runtime resolution, future completion, heartbeat)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


from desloppify.app.commands.review.runner_process_impl.attempts import (
    handle_early_attempt_return,
    handle_failed_attempt,
    handle_successful_attempt,
    handle_timeout_or_stall,
    resolve_retry_config,
)
from desloppify.app.commands.review.runner_process_impl.io import (
    _check_stall,
    _extract_text_from_opencode_json_stream,
    _output_file_has_json_payload,
    _output_file_status_text,
    extract_payload_from_log,
)
from desloppify.app.commands.review.runner_process_impl.types import (
    CodexBatchRunnerDeps,
    _ExecutionResult,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_deps(**overrides) -> CodexBatchRunnerDeps:
    """Build a minimal CodexBatchRunnerDeps with sensible defaults."""
    defaults = dict(
        timeout_seconds=60,
        subprocess_run=MagicMock(),
        timeout_error=TimeoutError,
        safe_write_text_fn=MagicMock(),
        use_popen_runner=False,
        subprocess_popen=None,
        max_retries=0,
        retry_backoff_seconds=0.0,
        sleep_fn=MagicMock(),
        live_log_interval_seconds=5.0,
        stall_after_output_seconds=90,
        output_validation_grace_seconds=0.0,
        output_validation_poll_seconds=0.01,
    )
    defaults.update(overrides)
    return CodexBatchRunnerDeps(**defaults)


# ═══════════════════════════════════════════════════════════════════
# runner_process_impl.io.py
# ═══════════════════════════════════════════════════════════════════


class TestOutputFileStatusText:
    """_output_file_status_text: describes a file's state for log snapshots."""

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nope.json"
        result = _output_file_status_text(p)
        assert "(missing)" in result

    def test_existing_file(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text('{"ok": true}')
        result = _output_file_status_text(p)
        assert "(exists" in result
        assert "bytes=" in result
        assert "modified=" in result


class TestOutputFileHasJsonPayload:
    """_output_file_has_json_payload: validates JSON dict output files."""

    def test_missing_file(self, tmp_path):
        assert _output_file_has_json_payload(tmp_path / "missing.json") is False

    def test_valid_json_dict(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text('{"assessments": {}}')
        assert _output_file_has_json_payload(p) is True

    def test_json_array_rejected(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text("[1, 2, 3]")
        assert _output_file_has_json_payload(p) is False

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text("not json at all")
        assert _output_file_has_json_payload(p) is False

    def test_empty_file(self, tmp_path):
        p = tmp_path / "out.json"
        p.write_text("")
        assert _output_file_has_json_payload(p) is False


class TestExtractPayloadFromLog:
    """extract_payload_from_log: recovers batch payload from runner log files."""

    def _setup_log(self, tmp_path, batch_index: int, content: str) -> Path:
        """Write a log file and return the raw_path that the function expects."""
        logs_dir = tmp_path / "subagents" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"batch-{batch_index + 1}.log"
        log_file.write_text(content)
        # raw_path must be in subagents/raw/ so that parent.parent / "logs" works
        raw_dir = tmp_path / "subagents" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        return raw_dir / f"batch-{batch_index + 1}.json"

    def test_no_log_file_returns_none(self, tmp_path):
        raw_path = tmp_path / "subagents" / "raw" / "batch-1.json"
        result = extract_payload_from_log(0, raw_path, lambda t: None)
        assert result is None

    def test_extracts_from_stdout_section(self, tmp_path):
        payload = {"assessments": {"naming": 0.8}}
        log_content = (
            "some preamble\n"
            "\nSTDOUT:\n"
            f"{json.dumps(payload)}\n"
            "\n\nSTDERR:\n"
            "some error text\n"
        )
        raw_path = self._setup_log(tmp_path, 0, log_content)

        def extract_fn(text):
            try:
                obj = json.loads(text.strip())
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None

        result = extract_payload_from_log(0, raw_path, extract_fn)
        assert result == payload

    def test_extracts_from_stdout_at_start_of_file(self, tmp_path):
        """When STDOUT: is at the very start (no leading newline)."""
        payload = {"issues": []}
        log_content = f"STDOUT:\n{json.dumps(payload)}\n\n\nSTDERR:\nwarning\n"
        raw_path = self._setup_log(tmp_path, 2, log_content)

        def extract_fn(text):
            try:
                obj = json.loads(text.strip())
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None

        result = extract_payload_from_log(2, raw_path, extract_fn)
        assert result == payload

    def test_stdout_section_no_payload_returns_none(self, tmp_path):
        """When STDOUT section exists but has no parseable payload, returns None
        (does NOT fall back to whole-log parsing)."""
        log_content = (
            "\nSTDOUT:\n"
            "just some random text, no JSON\n"
            "\n\nSTDERR:\n"
            '{"this_should_not_be_found": true}\n'
        )
        raw_path = self._setup_log(tmp_path, 0, log_content)
        result = extract_payload_from_log(0, raw_path, lambda t: None)
        assert result is None

    def test_no_stdout_marker_falls_back_to_whole_log(self, tmp_path):
        """When there is no STDOUT marker, extract_fn gets the whole log."""
        payload = {"quality": {"overall": 0.9}}
        log_content = json.dumps(payload)
        raw_path = self._setup_log(tmp_path, 1, log_content)

        def extract_fn(text):
            try:
                obj = json.loads(text.strip())
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None

        result = extract_payload_from_log(1, raw_path, extract_fn)
        assert result == payload

    def test_extract_fn_returning_none_propagates(self, tmp_path):
        """When extract_fn cannot parse anything, None is returned."""
        log_content = "no json here at all"
        raw_path = self._setup_log(tmp_path, 0, log_content)
        result = extract_payload_from_log(0, raw_path, lambda t: None)
        assert result is None


class TestCheckStall:
    """_check_stall: state machine for detecting runner stalls."""

    def test_no_output_file_first_call_not_stalled(self, tmp_path):
        """First call with missing output file: not stalled, baseline set."""
        output_file = tmp_path / "nope.json"
        now = 1000.0
        stalled, sig, stable = _check_stall(
            output_file, None, None, now, now, threshold=30
        )
        assert stalled is False
        assert sig is None
        assert stable == now  # baseline set to now

    def test_no_output_file_never_stalls(self, tmp_path):
        """Missing output file never triggers stall — the real timeout handles it."""
        output_file = tmp_path / "nope.json"
        baseline = 1000.0
        now = 1050.0  # 50s later, well past threshold
        last_activity = 1010.0  # 40s idle
        stalled, sig, stable = _check_stall(
            output_file, None, baseline, now, last_activity, threshold=30
        )
        assert stalled is False
        assert stable == baseline  # baseline preserved

    def test_no_output_file_not_stalled_when_stream_active(self, tmp_path):
        """Missing output but recent stream activity — still no stall."""
        output_file = tmp_path / "nope.json"
        baseline = 1000.0
        now = 1050.0
        last_activity = 1040.0  # only 10s idle
        stalled, sig, stable = _check_stall(
            output_file, None, baseline, now, last_activity, threshold=30
        )
        assert stalled is False

    def test_file_changes_resets_stable_since(self, tmp_path):
        """When the file signature changes, stable_since resets and no stall."""
        output_file = tmp_path / "out.json"
        output_file.write_text('{"a": 1}')
        stat = output_file.stat()
        current_sig = (int(stat.st_size), int(stat.st_mtime))
        # Different previous signature => file changed
        old_sig = (0, 0)
        now = 2000.0
        stalled, new_sig, new_stable = _check_stall(
            output_file, old_sig, 1900.0, now, 1950.0, threshold=30
        )
        assert stalled is False
        assert new_sig == current_sig
        assert new_stable == now  # reset to now

    def test_file_stable_stalls_after_threshold(self, tmp_path):
        """File exists with same signature for longer than threshold => stall."""
        output_file = tmp_path / "out.json"
        output_file.write_text('{"data": true}')
        stat = output_file.stat()
        sig = (int(stat.st_size), int(stat.st_mtime))
        stable_since = 1000.0
        now = 1050.0  # 50s stable
        last_activity = 1010.0  # 40s stream idle
        stalled, new_sig, new_stable = _check_stall(
            output_file, sig, stable_since, now, last_activity, threshold=30
        )
        assert stalled is True
        assert new_sig == sig
        assert new_stable == stable_since

    def test_file_stable_not_stalled_within_threshold(self, tmp_path):
        """File stable but within threshold => no stall."""
        output_file = tmp_path / "out.json"
        output_file.write_text('{"data": true}')
        stat = output_file.stat()
        sig = (int(stat.st_size), int(stat.st_mtime))
        stable_since = 1000.0
        now = 1020.0  # only 20s
        last_activity = 1000.0
        stalled, new_sig, new_stable = _check_stall(
            output_file, sig, stable_since, now, last_activity, threshold=30
        )
        assert stalled is False

    def test_same_sig_but_prev_stable_none(self, tmp_path):
        """Same signature, prev_stable=None => not stalled, stable stays None."""
        output_file = tmp_path / "out.json"
        output_file.write_text('{"x": 1}')
        stat = output_file.stat()
        sig = (int(stat.st_size), int(stat.st_mtime))
        stalled, new_sig, new_stable = _check_stall(
            output_file, sig, None, 2000.0, 1990.0, threshold=30
        )
        assert stalled is False
        assert new_stable is None


# ═══════════════════════════════════════════════════════════════════
# runner_process_impl.attempts.py
# ═══════════════════════════════════════════════════════════════════


class TestResolveRetryConfig:
    """resolve_retry_config: normalizes deps into _RetryConfig."""

    def test_defaults(self):
        deps = _make_deps()
        cfg = resolve_retry_config(deps)
        assert cfg.max_attempts == 1  # 0 retries => 1 attempt
        assert cfg.retry_backoff_seconds == 0.0
        assert cfg.live_log_interval == 5.0
        assert cfg.stall_seconds == 90
        assert cfg.use_popen is False

    def test_retries_become_attempts(self):
        deps = _make_deps(max_retries=3)
        cfg = resolve_retry_config(deps)
        assert cfg.max_attempts == 4  # 3 retries + 1 initial

    def test_negative_retries_clamped_to_zero(self):
        deps = _make_deps(max_retries=-5)
        cfg = resolve_retry_config(deps)
        assert cfg.max_attempts == 1

    def test_backoff_seconds(self):
        deps = _make_deps(retry_backoff_seconds=2.5)
        cfg = resolve_retry_config(deps)
        assert cfg.retry_backoff_seconds == 2.5

    def test_negative_backoff_clamped(self):
        deps = _make_deps(retry_backoff_seconds=-1.0)
        cfg = resolve_retry_config(deps)
        assert cfg.retry_backoff_seconds == 0.0

    def test_live_log_interval_custom(self):
        deps = _make_deps(live_log_interval_seconds=10.0)
        cfg = resolve_retry_config(deps)
        assert cfg.live_log_interval == 10.0

    def test_live_log_interval_zero_uses_default(self):
        deps = _make_deps(live_log_interval_seconds=0)
        cfg = resolve_retry_config(deps)
        assert cfg.live_log_interval == 5.0  # fallback

    def test_stall_seconds_custom(self):
        deps = _make_deps(stall_after_output_seconds=120)
        cfg = resolve_retry_config(deps)
        assert cfg.stall_seconds == 120

    def test_stall_seconds_zero_disables(self):
        deps = _make_deps(stall_after_output_seconds=0)
        cfg = resolve_retry_config(deps)
        assert cfg.stall_seconds == 0

    def test_use_popen_true_with_callable(self):
        deps = _make_deps(use_popen_runner=True, subprocess_popen=MagicMock())
        cfg = resolve_retry_config(deps)
        assert cfg.use_popen is True

    def test_use_popen_true_without_callable(self):
        deps = _make_deps(use_popen_runner=True, subprocess_popen=None)
        cfg = resolve_retry_config(deps)
        assert cfg.use_popen is False  # no callable => disabled

    def test_non_numeric_retries_defaults_to_zero(self):
        deps = _make_deps(max_retries="abc")
        cfg = resolve_retry_config(deps)
        assert cfg.max_attempts == 1

    def test_non_numeric_backoff_defaults_to_zero(self):
        deps = _make_deps(retry_backoff_seconds="bad")
        cfg = resolve_retry_config(deps)
        assert cfg.retry_backoff_seconds == 0.0


class TestHandleEarlyAttemptReturn:
    """handle_early_attempt_return: passes through early_return from result."""

    def test_none_when_no_early_return(self):
        result = _ExecutionResult(code=0, stdout_text="", stderr_text="")
        assert handle_early_attempt_return(result) is None

    def test_returns_early_return_code(self):
        result = _ExecutionResult(code=0, stdout_text="", stderr_text="", early_return=127)
        assert handle_early_attempt_return(result) == 127


class TestHandleTimeoutOrStall:
    """handle_timeout_or_stall: returns exit code for timeout/stall scenarios."""

    def test_returns_none_for_normal_result(self, tmp_path):
        result = _ExecutionResult(code=0, stdout_text="ok", stderr_text="")
        deps = _make_deps()
        ret = handle_timeout_or_stall(
            header="ATTEMPT 1/1",
            result=result,
            deps=deps,
            output_file=tmp_path / "out.json",
            log_file=tmp_path / "log.txt",
            log_sections=[],
            stall_seconds=90,
        )
        assert ret is None

    def test_timeout_with_valid_output_recovers(self, tmp_path):
        output_file = tmp_path / "out.json"
        output_file.write_text('{"assessments": {}}')
        result = _ExecutionResult(
            code=1, stdout_text="", stderr_text="", timed_out=True
        )
        deps = _make_deps()
        log_sections: list[str] = []
        ret = handle_timeout_or_stall(
            header="ATTEMPT 1/1",
            result=result,
            deps=deps,
            output_file=output_file,
            log_file=tmp_path / "log.txt",
            log_sections=log_sections,
            stall_seconds=90,
        )
        assert ret == 0  # recovered

    def test_timeout_without_output_returns_124(self, tmp_path):
        result = _ExecutionResult(
            code=1, stdout_text="", stderr_text="", timed_out=True
        )
        deps = _make_deps()
        ret = handle_timeout_or_stall(
            header="ATTEMPT 1/1",
            result=result,
            deps=deps,
            output_file=tmp_path / "missing.json",
            log_file=tmp_path / "log.txt",
            log_sections=[],
            stall_seconds=90,
        )
        assert ret == 124

    def test_stall_with_valid_output_recovers(self, tmp_path):
        output_file = tmp_path / "out.json"
        output_file.write_text('{"quality": {}}')
        result = _ExecutionResult(
            code=1, stdout_text="", stderr_text="", stalled=True
        )
        deps = _make_deps()
        log_sections: list[str] = []
        ret = handle_timeout_or_stall(
            header="ATTEMPT 1/1",
            result=result,
            deps=deps,
            output_file=output_file,
            log_file=tmp_path / "log.txt",
            log_sections=log_sections,
            stall_seconds=60,
        )
        assert ret == 0

    def test_stall_without_output_returns_124(self, tmp_path):
        result = _ExecutionResult(
            code=1, stdout_text="", stderr_text="", stalled=True
        )
        deps = _make_deps()
        ret = handle_timeout_or_stall(
            header="ATTEMPT 1/1",
            result=result,
            deps=deps,
            output_file=tmp_path / "missing.json",
            log_file=tmp_path / "log.txt",
            log_sections=[],
            stall_seconds=60,
        )
        assert ret == 124

    def test_timeout_log_sections_appended(self, tmp_path):
        result = _ExecutionResult(
            code=1, stdout_text="out", stderr_text="err", timed_out=True
        )
        deps = _make_deps(timeout_seconds=120)
        log_sections: list[str] = []
        handle_timeout_or_stall(
            header="ATTEMPT 1/2",
            result=result,
            deps=deps,
            output_file=tmp_path / "missing.json",
            log_file=tmp_path / "log.txt",
            log_sections=log_sections,
            stall_seconds=90,
        )
        assert any("TIMEOUT" in s for s in log_sections)
        assert any("120s" in s for s in log_sections)

    def test_stall_log_sections_appended(self, tmp_path):
        result = _ExecutionResult(
            code=1, stdout_text="out", stderr_text="err", stalled=True
        )
        deps = _make_deps()
        log_sections: list[str] = []
        handle_timeout_or_stall(
            header="ATTEMPT 1/1",
            result=result,
            deps=deps,
            output_file=tmp_path / "missing.json",
            log_file=tmp_path / "log.txt",
            log_sections=log_sections,
            stall_seconds=45,
        )
        assert any("STALL RECOVERY" in s for s in log_sections)


class TestHandleSuccessfulAttempt:
    """handle_successful_attempt: validates code==0 results have valid output."""

    def test_nonzero_code_returns_none(self, tmp_path):
        result = _ExecutionResult(code=1, stdout_text="", stderr_text="")
        ret = handle_successful_attempt(
            result=result,
            output_file=tmp_path / "out.json",
            log_file=tmp_path / "log.txt",
            deps=_make_deps(),
            log_sections=[],
        )
        assert ret is None  # not handled by this function

    def test_success_with_valid_output(self, tmp_path):
        output_file = tmp_path / "out.json"
        output_file.write_text('{"assessments": {}}')
        result = _ExecutionResult(code=0, stdout_text="done", stderr_text="")
        ret = handle_successful_attempt(
            result=result,
            output_file=output_file,
            log_file=tmp_path / "log.txt",
            deps=_make_deps(),
            log_sections=[],
        )
        assert ret == 0

    def test_success_without_output_returns_1(self, tmp_path):
        """Exit 0 but missing output file => treated as failure."""
        result = _ExecutionResult(code=0, stdout_text="done", stderr_text="")
        log_sections: list[str] = []
        ret = handle_successful_attempt(
            result=result,
            output_file=tmp_path / "missing.json",
            log_file=tmp_path / "log.txt",
            deps=_make_deps(),
            log_sections=log_sections,
        )
        assert ret == 1
        assert any("missing or invalid" in s for s in log_sections)

    def test_success_with_delayed_output_passes_with_grace(self, tmp_path):
        """Exit 0 with late output write should pass after grace polling."""
        output_file = tmp_path / "out.txt"
        calls = {"n": 0}

        def _validate(path: Path) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                return False
            path.write_text("late but valid")
            return True

        result = _ExecutionResult(code=0, stdout_text="done", stderr_text="")
        deps = _make_deps(
            validate_output_fn=_validate,
            output_validation_grace_seconds=0.5,
            output_validation_poll_seconds=0.01,
            sleep_fn=MagicMock(),
        )
        log_sections: list[str] = []
        ret = handle_successful_attempt(
            result=result,
            output_file=output_file,
            log_file=tmp_path / "log.txt",
            deps=deps,
            log_sections=log_sections,
        )
        assert ret == 0
        assert any("grace wait" in s for s in log_sections)
        deps.sleep_fn.assert_called()

    def test_success_recovers_from_stdout_fallback_for_custom_validator(self, tmp_path):
        """Custom validator mode can recover by writing stdout fallback text."""
        output_file = tmp_path / "out.txt"

        def _text_validate(path: Path) -> bool:
            return path.exists() and bool(path.read_text().strip())

        def _safe_write(path: Path, text: str) -> None:
            path.write_text(text)

        result = _ExecutionResult(code=0, stdout_text="fallback output", stderr_text="")
        log_sections: list[str] = []
        ret = handle_successful_attempt(
            result=result,
            output_file=output_file,
            log_file=tmp_path / "log.txt",
            deps=_make_deps(
                validate_output_fn=_text_validate,
                safe_write_text_fn=_safe_write,
                output_validation_grace_seconds=0.0,
            ),
            log_sections=log_sections,
        )
        assert ret == 0
        assert output_file.read_text() == "fallback output"
        assert any("stdout/stderr fallback" in s for s in log_sections)


class TestHandleFailedAttempt:
    """handle_failed_attempt: transient failure detection and retry delay."""

    def test_non_transient_failure_returns_code(self, tmp_path):
        result = _ExecutionResult(
            code=1, stdout_text="", stderr_text="something unexpected"
        )
        deps = _make_deps(max_retries=2)
        ret = handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=1,
            max_attempts=3,
            retry_backoff_seconds=1.0,
            log_file=tmp_path / "log.txt",
            log_sections=[],
        )
        assert ret == 1  # non-transient => immediate return

    def test_transient_failure_retries(self, tmp_path):
        """Transient phrase in output + attempts remaining => returns None (retry)."""
        result = _ExecutionResult(
            code=1,
            stdout_text="",
            stderr_text="stream disconnected before completion",
        )
        deps = _make_deps(max_retries=2, sleep_fn=MagicMock())
        log_sections: list[str] = []
        ret = handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=1,
            max_attempts=3,
            retry_backoff_seconds=2.0,
            log_file=tmp_path / "log.txt",
            log_sections=log_sections,
        )
        assert ret is None  # signals retry
        deps.sleep_fn.assert_called_once_with(2.0)  # 2.0 * 2^(1-1) = 2.0
        assert any("retrying" in s.lower() for s in log_sections)

    def test_transient_failure_last_attempt_returns_code(self, tmp_path):
        """Transient but on last attempt => returns code."""
        result = _ExecutionResult(
            code=1,
            stdout_text="",
            stderr_text="connection reset by peer",
        )
        deps = _make_deps()
        ret = handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=3,
            max_attempts=3,
            retry_backoff_seconds=1.0,
            log_file=tmp_path / "log.txt",
            log_sections=[],
        )
        assert ret == 1  # last attempt, no more retries

    def test_backoff_exponential(self, tmp_path):
        """Backoff delay doubles per attempt."""
        result = _ExecutionResult(
            code=1,
            stdout_text="",
            stderr_text="connection refused",
        )
        deps = _make_deps(max_retries=3, sleep_fn=MagicMock())
        # attempt=2, backoff=1.0 => delay = 1.0 * 2^(2-1) = 2.0
        handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=2,
            max_attempts=4,
            retry_backoff_seconds=1.0,
            log_file=tmp_path / "log.txt",
            log_sections=[],
        )
        deps.sleep_fn.assert_called_once_with(2.0)

    def test_sleep_fn_error_aborts_retries(self, tmp_path):
        """If sleep_fn raises, remaining retries are aborted."""
        result = _ExecutionResult(
            code=1,
            stdout_text="",
            stderr_text="temporarily unavailable",
        )
        deps = _make_deps(
            max_retries=3,
            sleep_fn=MagicMock(side_effect=OSError("sleep broken")),
        )
        log_sections: list[str] = []
        ret = handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=1,
            max_attempts=4,
            retry_backoff_seconds=1.0,
            log_file=tmp_path / "log.txt",
            log_sections=log_sections,
        )
        assert ret == 1  # aborted
        assert any("aborting" in s.lower() for s in log_sections)

    def test_zero_backoff_skips_sleep(self, tmp_path):
        """With backoff=0, sleep is not called (delay_seconds == 0)."""
        result = _ExecutionResult(
            code=1,
            stdout_text="",
            stderr_text="network is unreachable",
        )
        deps = _make_deps(max_retries=2, sleep_fn=MagicMock())
        handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=1,
            max_attempts=3,
            retry_backoff_seconds=0.0,
            log_file=tmp_path / "log.txt",
            log_sections=[],
        )
        # delay_seconds = 0.0 * 2^0 = 0.0 => condition `delay_seconds > 0` is False
        deps.sleep_fn.assert_not_called()

    def test_transient_phrase_case_insensitive(self, tmp_path):
        """Transient detection is case-insensitive (combined text is lowered)."""
        result = _ExecutionResult(
            code=1,
            stdout_text="",
            stderr_text="CONNECTION RESET BY PEER",
        )
        deps = _make_deps(max_retries=2, sleep_fn=MagicMock())
        ret = handle_failed_attempt(
            result=result,
            deps=deps,
            attempt=1,
            max_attempts=3,
            retry_backoff_seconds=0.0,
            log_file=tmp_path / "log.txt",
            log_sections=[],
        )
        assert ret is None  # recognized as transient


# ═══════════════════════════════════════════════════════════════════
# runner_parallel.execution.py
# ═══════════════════════════════════════════════════════════════════




class TestExtractTextFromOpenCodeJsonStream:
    """_extract_text_from_opencode_json_stream: extracts terminal assistant text."""

    def test_terminal_stop_step_wins_over_planning_text(self):
        final_payload = json.dumps({"assessments": {}})
        planning_payload = json.dumps(
            {"assessments": {"logic_clarity": 10}, "issues": []}
        )
        stream = (
            '{"type":"step_start","part":{"type":"step-start"}}\n'
            + json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": f"planning {planning_payload}"},
                }
            )
            + "\n"
            + '{"type":"step_finish","part":{"type":"step-finish","reason":"tool-calls"}}\n'
            + '{"type":"step_start","part":{"type":"step-start"}}\n'
            + json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": final_payload},
                }
            )
            + "\n"
            + '{"type":"step_finish","part":{"type":"step-finish","reason":"stop"}}\n'
        )
        assert _extract_text_from_opencode_json_stream(stream) == final_payload

    def test_in_progress_step_returns_empty(self):
        payload = json.dumps({"assessments": {"logic_clarity": 10}, "issues": []})
        stream = (
            '{"type":"step_start","part":{"type":"step-start"}}\n'
            + json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": payload},
                }
            )
            + "\n"
        )
        assert _extract_text_from_opencode_json_stream(stream) == ""


class TestOpenCodeFailureDetection:
    def test_opencode_runner_missing_patterns_detected(self):
        from desloppify.app.commands.review.runner_failures import _is_runner_missing

        assert _is_runner_missing("opencode not found") is True
        assert _is_runner_missing("errno 2 opencode") is True
        assert _is_runner_missing("no such file or directory $ opencode run") is True


class TestOpenCodeProvenanceSupport:
    def test_supported_blind_review_runners_include_opencode(self):
        from desloppify.app.commands.review.importing.policy import (
            SUPPORTED_BLIND_REVIEW_RUNNERS,
        )

        assert "opencode" in SUPPORTED_BLIND_REVIEW_RUNNERS
