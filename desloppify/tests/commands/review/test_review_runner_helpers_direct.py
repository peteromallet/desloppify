"""Direct unit tests for review runner helper orchestration paths."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import desloppify.app.commands.review.batch.orchestrator as orchestrator_mod
import desloppify.app.commands.review.batch.prompt_template as prompt_template_mod
import desloppify.app.commands.review.runner_opencode as runner_opencode_mod
import desloppify.app.commands.review.runner_parallel as runner_helpers_mod
from desloppify.app.commands.review.batch.execution import CollectBatchResultsRequest
from desloppify.app.commands.review.runner_process_impl.types import _ExecutionResult


def test_execute_batches_parallel_emits_heartbeat_event() -> None:
    events: list[str] = []

    def _progress(event) -> None:
        events.append(getattr(event, "event", ""))

    failures = runner_helpers_mod.execute_batches(
        tasks={0: lambda: (time.sleep(0.08), 0)[1]},
        options=runner_helpers_mod.BatchExecutionOptions(
            run_parallel=True,
            max_parallel_workers=1,
            heartbeat_seconds=0.01,
        ),
        progress_fn=_progress,
    )

    assert failures == []
    assert "queued" in events
    assert "start" in events
    assert "done" in events
    assert "heartbeat" in events


def test_execute_batches_parallel_task_exception_marks_failure() -> None:
    captured: list[tuple[int, str]] = []

    def _boom() -> int:
        raise RuntimeError("task failed")

    failures = runner_helpers_mod.execute_batches(
        tasks={0: _boom},
        options=runner_helpers_mod.BatchExecutionOptions(
            run_parallel=True,
            max_parallel_workers=1,
            heartbeat_seconds=0.01,
        ),
        error_log_fn=lambda idx, exc: captured.append((idx, str(exc))),
    )

    assert failures == [0]
    assert captured
    assert any("task failed" in message for _idx, message in captured)


def test_collect_batch_results_recovers_from_log_stdout_payload(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    results_dir = run_root / "results"
    logs_dir = run_root / "logs"
    results_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    raw_path = results_dir / "batch-1.raw.txt"
    payload = {
        "assessments": {"logic_clarity": 91.0},
        "dimension_notes": {"logic_clarity": {"evidence": ["recoverable path"]}},
        "issues": [],
    }
    log_path = logs_dir / "batch-1.log"
    log_path.write_text(
        "STDOUT:\n"
        + json.dumps(payload)
        + "\n\nSTDERR:\nrunner transient error\n"
    )

    batch_results, failures = runner_helpers_mod.collect_batch_results(
        request=CollectBatchResultsRequest(
            selected_indexes=[0],
            failures=[0],
            output_files={0: raw_path},
            allowed_dims={"logic_clarity"},
        ),
        extract_payload_fn=lambda raw: json.loads(raw),
        normalize_result_fn=lambda parsed, _allowed: (
            parsed.get("assessments", {}),
            parsed.get("issues", []),
            parsed.get("dimension_notes", {}),
            parsed.get("dimension_judgment", {}),
            {},
            {},
        ),
    )

    assert failures == []
    assert len(batch_results) == 1
    assert raw_path.exists()
    persisted = json.loads(raw_path.read_text())
    assert persisted["assessments"]["logic_clarity"] == 91.0


def test_collect_batch_results_marks_failure_on_normalize_error(tmp_path: Path) -> None:
    raw_path = tmp_path / "batch-1.raw.txt"
    raw_path.write_text(json.dumps({"assessments": {"logic_clarity": 50.0}, "issues": []}))

    batch_results, failures = runner_helpers_mod.collect_batch_results(
        request=CollectBatchResultsRequest(
            selected_indexes=[0],
            failures=[],
            output_files={0: raw_path},
            allowed_dims={"logic_clarity"},
        ),
        extract_payload_fn=lambda raw: json.loads(raw),
        normalize_result_fn=lambda _parsed, _allowed: (_ for _ in ()).throw(
            ValueError("normalize failed")
        ),
    )

    assert batch_results == []
    assert failures == [0]


def test_render_batch_prompt_loads_context_updates_example() -> None:
    prompt = prompt_template_mod.render_batch_prompt(
        repo_root=Path("/tmp/repo"),
        packet_path=Path("/tmp/repo/query.blind.json"),
        batch_index=0,
        batch={
            "name": "B1",
            "why": "test",
            "dimensions": ["logic_clarity"],
            "files_to_read": ["src/a.py"],
            "dimension_prompts": {
                "logic_clarity": {
                    "description": "Keep logic direct.",
                }
            },
        },
    )

    assert "context_updates example" in prompt


def _safe_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_run_opencode_batch_recovers_timeout_from_stdout_payload(tmp_path: Path) -> None:
    log_file = tmp_path / "batch.log"
    output_file = tmp_path / "out.json"
    stale_payload = {"assessments": {"logic_clarity": 12}, "issues": []}
    payload = {"assessments": {"logic_clarity": 88}, "issues": []}
    stdout_text = "\n".join([
        json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
        json.dumps({"type": "text", "part": {"type": "text", "text": f"planning {json.dumps(stale_payload)}"}}),
        json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls"}}),
        json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
        json.dumps({"type": "text", "part": {"type": "text", "text": json.dumps(payload)}}),
        json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}}),
        "",
    ])

    with patch(
        "desloppify.app.commands.review.runner_opencode._run_batch_attempt",
        return_value=(
            "ATTEMPT 1/1",
            _ExecutionResult(code=1, stdout_text=stdout_text, stderr_text="", timed_out=True),
        ),
    ):
        code = runner_opencode_mod.run_opencode_batch(
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


def test_run_opencode_batch_restores_valid_output_after_retry_failure(tmp_path: Path) -> None:
    output_file = tmp_path / "batch-1.raw.txt"
    log_file = tmp_path / "batch-1.log"
    first_payload = {"assessments": {"logic_clarity": 10}, "issues": []}
    first_stdout = json.dumps({"type": "text", "part": {"type": "text", "text": json.dumps(first_payload)}}) + "\n"

    with patch(
        "desloppify.app.commands.review.runner_opencode._run_batch_attempt",
        side_effect=[
            ("ATTEMPT 1/2", _ExecutionResult(code=1, stdout_text=first_stdout, stderr_text="stream disconnected before completion")),
            ("ATTEMPT 2/2", _ExecutionResult(code=1, stdout_text="", stderr_text="fatal auth error")),
        ],
    ):
        code = runner_opencode_mod.run_opencode_batch(
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
    assert json.loads(output_file.read_text()) == first_payload

    batch_results, failures = runner_helpers_mod.collect_batch_results(
        request=CollectBatchResultsRequest(
            selected_indexes=[0],
            failures=[0],
            output_files={0: output_file},
            allowed_dims={"logic_clarity"},
        ),
        extract_payload_fn=lambda raw: json.loads(raw),
        normalize_result_fn=lambda payload, _dims: (payload.get("assessments", {}), payload.get("issues", []), {}, {}, {}, {}),
    )

    assert len(batch_results) == 1
    assert failures == []
    assert batch_results[0].assessments == first_payload["assessments"]
