"""Direct unit tests for the Rovo Dev (`acli rovodev`) batch runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import desloppify.app.commands.review.batch.orchestrator as orchestrator_mod
import desloppify.app.commands.review.runner_rovodev as runner_rovodev_mod
from desloppify.app.commands.review.runner_process_impl.types import _ExecutionResult


def _safe_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_rovodev_batch_command_includes_acli_rovodev_invocation(monkeypatch) -> None:
    """The default command line invokes ``acli rovodev`` with ``--yolo``."""
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_NO_YOLO", raising=False)
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA", raising=False)
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_EXTRA_ARGS", raising=False)
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_EXECUTABLE", raising=False)

    cmd = runner_rovodev_mod.rovodev_batch_command(
        prompt="hello world",
        repo_root=Path("/tmp/repo"),
    )

    # The prompt is always the final positional argument so any flags can be
    # injected before it without colliding with shell-quoting edge cases.
    assert cmd[-1] == "hello world"
    joined = " ".join(cmd).lower()
    assert "rovodev" in joined
    # --yolo is enabled by default so the agent can write the per-batch
    # output file in non-interactive mode without permission prompts.
    assert "--yolo" in joined


def test_rovodev_batch_command_honours_env_overrides(monkeypatch) -> None:
    """Schema, extra args, and executable overrides are respected."""
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_NO_YOLO", raising=False)
    monkeypatch.setenv("DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA", '{"type":"object"}')
    monkeypatch.setenv("DESLOPPIFY_ROVODEV_EXTRA_ARGS", "--config-override foo")
    monkeypatch.setenv("DESLOPPIFY_ROVODEV_EXECUTABLE", "acli")

    cmd = runner_rovodev_mod.rovodev_batch_command(
        prompt="prompt",
        repo_root=Path("/tmp/repo"),
    )

    joined = " ".join(cmd)
    assert "--output-schema" in joined
    assert '{"type":"object"}' in joined
    assert "--config-override foo" in joined
    assert cmd[-1] == "prompt"


def test_rovodev_batch_command_no_yolo_opt_out(monkeypatch) -> None:
    """Setting DESLOPPIFY_ROVODEV_NO_YOLO=1 omits the --yolo flag."""
    monkeypatch.setenv("DESLOPPIFY_ROVODEV_NO_YOLO", "1")
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA", raising=False)
    monkeypatch.delenv("DESLOPPIFY_ROVODEV_EXTRA_ARGS", raising=False)

    cmd = runner_rovodev_mod.rovodev_batch_command(
        prompt="p",
        repo_root=Path("/tmp/repo"),
    )

    assert "--yolo" not in " ".join(cmd)


def test_extract_json_object_returns_last_balanced_object() -> None:
    """When the agent emits multiple JSON objects, the last one wins."""
    text = (
        "Working...\n"
        '{"assessments": {"logic_clarity": 10}, "issues": []}\n'
        "Final answer:\n"
        '{"assessments": {"logic_clarity": 88}, "issues": []}\n'
    )

    extracted = runner_rovodev_mod._extract_json_object(text)

    assert extracted is not None
    assert json.loads(extracted)["assessments"]["logic_clarity"] == 88


def test_extract_json_object_handles_strings_with_braces() -> None:
    """JSON strings containing braces should not desync the brace counter."""
    payload = {"comment": "function() { return 1; }", "issues": []}
    text = "Plan:\n" + json.dumps(payload)

    extracted = runner_rovodev_mod._extract_json_object(text)

    assert extracted is not None
    assert json.loads(extracted) == payload


def test_extract_json_object_returns_none_for_no_object() -> None:
    assert runner_rovodev_mod._extract_json_object("just narration") is None
    assert runner_rovodev_mod._extract_json_object("") is None


def test_run_rovodev_batch_recovers_timeout_from_stdout_payload(tmp_path: Path) -> None:
    """A timed-out attempt with a valid JSON payload in stdout is recovered."""
    log_file = tmp_path / "batch.log"
    output_file = tmp_path / "out.json"
    payload = {"assessments": {"logic_clarity": 88}, "issues": []}
    stdout_text = (
        "I am evaluating logic_clarity now.\n"
        f"Final reply:\n{json.dumps(payload)}\n"
    )

    with patch(
        "desloppify.app.commands.review.runner_rovodev._run_batch_attempt",
        return_value=(
            "ATTEMPT 1/1",
            _ExecutionResult(code=1, stdout_text=stdout_text, stderr_text="", timed_out=True),
        ),
    ):
        code = runner_rovodev_mod.run_rovodev_batch(
            prompt="test prompt",
            repo_root=tmp_path,
            output_file=output_file,
            log_file=log_file,
            deps=orchestrator_mod.CodexBatchRunnerDeps(
                timeout_seconds=60,
                subprocess_run=subprocess.run,
                timeout_error=TimeoutError,
                safe_write_text_fn=_safe_write_text,
                sleep_fn=lambda _seconds: None,
            ),
        )

    assert code == 0
    assert json.loads(output_file.read_text()) == payload
    assert "Recovered timed-out batch from JSON output file" in log_file.read_text()


def test_run_rovodev_batch_restores_valid_output_after_retry_failure(tmp_path: Path) -> None:
    """A successful first-attempt payload is preserved across a fatal retry."""
    output_file = tmp_path / "batch-1.raw.txt"
    log_file = tmp_path / "batch-1.log"
    first_payload = {"assessments": {"logic_clarity": 10}, "issues": []}
    first_stdout = "Reply:\n" + json.dumps(first_payload) + "\n"

    with patch(
        "desloppify.app.commands.review.runner_rovodev._run_batch_attempt",
        side_effect=[
            (
                "ATTEMPT 1/2",
                _ExecutionResult(
                    code=1,
                    stdout_text=first_stdout,
                    stderr_text="stream disconnected before completion",
                ),
            ),
            (
                "ATTEMPT 2/2",
                _ExecutionResult(code=1, stdout_text="", stderr_text="fatal auth error"),
            ),
        ],
    ):
        code = runner_rovodev_mod.run_rovodev_batch(
            prompt="test prompt",
            repo_root=tmp_path,
            output_file=output_file,
            log_file=log_file,
            deps=orchestrator_mod.CodexBatchRunnerDeps(
                timeout_seconds=60,
                subprocess_run=subprocess.run,
                timeout_error=TimeoutError,
                safe_write_text_fn=_safe_write_text,
                max_retries=1,
                retry_backoff_seconds=0.0,
                sleep_fn=lambda _seconds: None,
            ),
        )

    assert code == 1
    # The recoverable payload from attempt 1 must survive the fatal retry,
    # otherwise downstream collect_batch_results cannot recover the result.
    assert json.loads(output_file.read_text()) == first_payload


def test_select_batch_runner_dispatches_to_rovodev() -> None:
    """The orchestrator's runner dispatch table includes rovodev."""
    assert (
        orchestrator_mod._select_batch_runner("rovodev")
        is runner_rovodev_mod.run_rovodev_batch
    )
    # Unknown runner names fall back to codex (already validated upstream).
    assert (
        orchestrator_mod._select_batch_runner("unknown")
        is orchestrator_mod.run_codex_batch
    )


def test_validate_runner_accepts_rovodev() -> None:
    from desloppify.app.commands.review.batch.scope import validate_runner

    # Should not raise.
    validate_runner("rovodev", colorize_fn=lambda text, _style: text)


def test_runner_parser_accepts_rovodev_choice() -> None:
    from desloppify.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(
        ["review", "--run-batches", "--runner", "rovodev"]
    )
    assert args.runner == "rovodev"


def test_supported_blind_review_runners_includes_rovodev() -> None:
    from desloppify.app.commands.review.importing.policy import (
        SUPPORTED_BLIND_REVIEW_RUNNERS,
    )

    assert "rovodev" in SUPPORTED_BLIND_REVIEW_RUNNERS


def test_runner_missing_detection_recognises_acli(monkeypatch) -> None:
    """The runner-missing detector recognises the ``acli`` binary by name."""
    from desloppify.app.commands.review.runner_failures import _is_runner_missing

    assert _is_runner_missing("acli not found")
    assert _is_runner_missing("no such file or directory: $ acli rovodev run")
    assert not _is_runner_missing("totally unrelated error")


@pytest.mark.parametrize(
    "runner,expected_attr",
    [
        ("codex", "run_codex_batch"),
        ("opencode", "run_opencode_batch"),
        ("rovodev", "run_rovodev_batch"),
    ],
)
def test_select_batch_runner_table(runner: str, expected_attr: str) -> None:
    selected = orchestrator_mod._select_batch_runner(runner)
    assert selected is getattr(orchestrator_mod, expected_attr)
