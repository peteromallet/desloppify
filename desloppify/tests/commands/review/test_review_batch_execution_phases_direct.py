"""Direct tests for review batch execution phases module."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.app.commands.review.batch.execution_phases as phases_mod


def _prepared_context(**overrides):
    base = {
        "stamp": "stamp",
        "args": SimpleNamespace(),
        "config": {},
        "runner": "codex",
        "allow_partial": True,
        "run_parallel": True,
        "max_parallel_batches": 2,
        "heartbeat_seconds": 1.0,
        "batch_timeout_seconds": 60.0,
        "batch_max_retries": 1,
        "batch_retry_backoff_seconds": 1.0,
        "stall_warning_seconds": 10.0,
        "stall_kill_seconds": 30.0,
        "state": {},
        "lang": SimpleNamespace(name="python"),
        "packet": {"dimensions": ["d"]},
        "immutable_packet_path": Path("packet"),
        "prompt_packet_path": Path("prompt"),
        "scan_path": ".",
        "packet_dimensions": ["d"],
        "scored_dimensions": ["d"],
        "batches": [{"dimensions": ["d"]}],
        "selected_indexes": [0, 1],
        "project_root": Path("."),
        "run_dir": Path("run"),
        "logs_dir": Path("logs"),
        "prompt_files": {0: Path("p0"), 1: Path("p1")},
        "output_files": {0: Path("o0"), 1: Path("o1")},
        "log_files": {0: Path("l0"), 1: Path("l1")},
        "run_log_path": Path("run.log"),
        "append_run_log": lambda *_a, **_k: None,
        "batch_positions": {0: 1, 1: 2},
        "batch_status": {},
        "report_progress": lambda *_a, **_k: None,
        "record_issue": lambda *_a, **_k: None,
        "write_run_summary": lambda **_k: None,
    }
    base.update(overrides)
    return phases_mod.PreparedBatchRunContext(**base)


def _executed_context(**overrides):
    base = {
        "batch_results": [{"issues": []}],
        "successful_indexes": [0],
        "failure_set": set(),
    }
    base.update(overrides)
    return phases_mod.ExecutedBatchRunContext(**base)


def test_prepare_batch_run_returns_none_for_dry_run(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    project_root = tmp_path / "project"
    project_root.mkdir()
    packet = {
        "dimensions": ["design_coherence"],
        "investigation_batches": [{"dimensions": ["design_coherence"]}],
        "dimension_prompts": {"design_coherence": "prompt"},
    }

    def prepare_run_artifacts_fn(request):
        run_dir = request.run_root / request.stamp
        logs_dir = run_dir / "logs"
        prompts_dir = run_dir / "prompts"
        results_dir = run_dir / "results"
        logs_dir.mkdir(parents=True, exist_ok=True)
        prompts_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        prompt_files = {0: prompts_dir / "prompt-1.txt"}
        output_files = {0: results_dir / "result-1.json"}
        log_files = {0: logs_dir / "batch-1.log"}
        prompt_files[0].write_text("prompt")
        return run_dir, logs_dir, prompt_files, output_files, log_files

    deps = SimpleNamespace(
        colorize_fn=lambda text, _tone=None: text,
        run_stamp_fn=lambda: "stamp",
        load_or_prepare_packet_fn=lambda _request: (
            packet,
            tmp_path / "packet.json",
            tmp_path / "prompt.json",
        ),
        selected_batch_indexes_fn=lambda *_a, **_k: [0],
        prepare_run_artifacts_fn=prepare_run_artifacts_fn,
        safe_write_text_fn=lambda path, text: Path(path).write_text(text),
    )
    args = SimpleNamespace(
        runner="codex",
        allow_partial=False,
        path=".",
        dimensions=None,
        run_log_file=None,
        dry_run=True,
    )

    result = phases_mod.prepare_batch_run(
        args=args,
        state={},
        lang=SimpleNamespace(name="python"),
        config={},
        deps=deps,
        project_root=project_root,
        subagent_runs_dir=run_root,
    )

    summary_path = run_root / "stamp" / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    assert result is None
    assert summary["runner"] == "dry-run"
    assert summary["selected_batches"] == [1]
    assert summary["successful_batches"] == [1]
    assert summary["failed_batches"] == []
    assert summary["batches"]["1"]["status"] == "pending"


def test_execute_batch_run_partial_path_records_failures() -> None:
    logs: list[str] = []
    printed_failures: list[list[int]] = []
    prepared = _prepared_context(append_run_log=logs.append)
    deps = SimpleNamespace(
        run_codex_batch_fn=lambda *_a, **_k: 0,
        execute_batches_fn=lambda **_k: [1],
        collect_batch_results_fn=lambda **_k: ({}, []),
        colorize_fn=lambda text, _tone=None: text,
        print_failures_and_raise_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("unexpected")),
        print_failures_fn=lambda failures, **_k: printed_failures.append([idx for idx, _ in failures]),
    )

    original_collect = phases_mod.collect_and_reconcile_results
    phases_mod.collect_and_reconcile_results = lambda **_k: (
        [{"issues": []}],
        [0],
        [(1, "failed")],
        {1},
    )
    try:
        result = phases_mod.execute_batch_run(prepared=prepared, deps=deps)
    finally:
        phases_mod.collect_and_reconcile_results = original_collect

    assert result.batch_results == [{"issues": []}]
    assert result.successful_indexes == [0]
    assert result.failure_set == {1}
    assert printed_failures == [[1]]
    assert any("run-partial" in line for line in logs)
    assert any("successful=[1]" in line for line in logs)
    assert any("failed=[2]" in line for line in logs)


def test_execute_batch_run_keyboard_interrupt_exits_130() -> None:
    summary_calls: list[dict] = []
    logs: list[str] = []
    batch_status: dict[str, dict[str, object]] = {}
    prepared = _prepared_context(
        append_run_log=logs.append,
        batch_status=batch_status,
        write_run_summary=lambda **kwargs: summary_calls.append(kwargs),
    )
    deps = SimpleNamespace(
        run_codex_batch_fn=lambda *_a, **_k: 0,
        execute_batches_fn=lambda **_k: (_ for _ in ()).throw(KeyboardInterrupt()),
        collect_batch_results_fn=lambda **_k: ({}, []),
        colorize_fn=lambda text, _tone=None: text,
        print_failures_and_raise_fn=lambda **_k: None,
        print_failures_fn=lambda **_k: None,
    )

    with pytest.raises(SystemExit) as excinfo:
        phases_mod.execute_batch_run(prepared=prepared, deps=deps)

    assert excinfo.value.code == 130
    assert summary_calls[0]["interrupted"] is True
    assert summary_calls[0]["interruption_reason"] == "keyboard_interrupt"
    assert logs == ["run-interrupted reason=keyboard_interrupt"]


def test_merge_and_import_batch_run_calls_all_pipeline_steps() -> None:
    calls: list[str] = []
    original_merge = phases_mod.merge_and_write_results
    original_enforce = phases_mod.enforce_import_coverage
    original_import = phases_mod.import_and_finalize
    phases_mod.merge_and_write_results = lambda **_k: (Path("merged.json"), [])
    phases_mod.enforce_import_coverage = lambda **_k: calls.append("enforce")
    phases_mod.import_and_finalize = lambda **_k: calls.append("import")
    try:
        phases_mod.merge_and_import_batch_run(
            prepared=_prepared_context(
                allow_partial=False,
                append_run_log=lambda *_a, **_k: None,
                args=SimpleNamespace(),
            ),
            executed=_executed_context(),
            state_file=Path("state.json"),
            deps=SimpleNamespace(
                merge_batch_results_fn=lambda *_a, **_k: {"issues": []},
                build_import_provenance_fn=lambda **_k: {},
                safe_write_text_fn=lambda *_a, **_k: None,
                colorize_fn=lambda text, _tone=None: text,
                do_import_fn=lambda *_a, **_k: None,
                run_followup_scan_fn=lambda **_k: 0,
            ),
        )
    finally:
        phases_mod.merge_and_write_results = original_merge
        phases_mod.enforce_import_coverage = original_enforce
        phases_mod.import_and_finalize = original_import

    assert calls == ["enforce", "import"]


def test_is_partial_batch_retry_detects_subset() -> None:
    """Selected indexes that are a strict subset of all batches is a partial retry."""
    ctx = _prepared_context(
        batches=[{"dimensions": ["a"]}, {"dimensions": ["b"]}, {"dimensions": ["c"]}],
        selected_indexes=[1],
    )
    assert phases_mod._is_partial_batch_retry(ctx) is True


def test_is_partial_batch_retry_false_for_full_run() -> None:
    ctx = _prepared_context(
        batches=[{"dimensions": ["a"]}, {"dimensions": ["b"]}],
        selected_indexes=[0, 1],
    )
    assert phases_mod._is_partial_batch_retry(ctx) is False


def test_partial_retry_bypasses_coverage_gate() -> None:
    """When --only-batches selects a subset, the coverage gate gets allow_partial=True."""
    captured_kwargs: dict = {}
    original_merge = phases_mod.merge_and_write_results
    original_enforce = phases_mod.enforce_import_coverage
    original_import = phases_mod.import_and_finalize

    # Return missing dims so the gate would normally block.
    phases_mod.merge_and_write_results = lambda **_k: (Path("merged.json"), ["missing_dim"])

    def capture_enforce(**kwargs):
        captured_kwargs.update(kwargs)

    phases_mod.enforce_import_coverage = capture_enforce
    phases_mod.import_and_finalize = lambda **_k: None
    try:
        # 3 batches but only batch 1 selected => partial retry
        phases_mod.merge_and_import_batch_run(
            prepared=_prepared_context(
                allow_partial=False,
                batches=[{"dimensions": ["a"]}, {"dimensions": ["b"]}, {"dimensions": ["c"]}],
                selected_indexes=[1],
                append_run_log=lambda *_a, **_k: None,
                args=SimpleNamespace(),
            ),
            executed=_executed_context(),
            state_file=Path("state.json"),
            deps=SimpleNamespace(
                merge_batch_results_fn=lambda *_a, **_k: {"issues": []},
                build_import_provenance_fn=lambda **_k: {},
                safe_write_text_fn=lambda *_a, **_k: None,
                colorize_fn=lambda text, _tone=None: text,
                do_import_fn=lambda *_a, **_k: None,
                run_followup_scan_fn=lambda **_k: 0,
            ),
        )
    finally:
        phases_mod.merge_and_write_results = original_merge
        phases_mod.enforce_import_coverage = original_enforce
        phases_mod.import_and_finalize = original_import

    # The gate should have been called with allow_partial=True despite
    # the prepared context having allow_partial=False.
    assert captured_kwargs["allow_partial"] is True


def test_full_run_does_not_bypass_coverage_gate() -> None:
    """A full run (all batches selected) should NOT override allow_partial."""
    captured_kwargs: dict = {}
    original_merge = phases_mod.merge_and_write_results
    original_enforce = phases_mod.enforce_import_coverage
    original_import = phases_mod.import_and_finalize

    phases_mod.merge_and_write_results = lambda **_k: (Path("merged.json"), ["missing_dim"])

    def capture_enforce(**kwargs):
        captured_kwargs.update(kwargs)

    phases_mod.enforce_import_coverage = capture_enforce
    phases_mod.import_and_finalize = lambda **_k: None
    try:
        # All 2 batches selected => full run
        phases_mod.merge_and_import_batch_run(
            prepared=_prepared_context(
                allow_partial=False,
                batches=[{"dimensions": ["a"]}, {"dimensions": ["b"]}],
                selected_indexes=[0, 1],
                append_run_log=lambda *_a, **_k: None,
                args=SimpleNamespace(),
            ),
            executed=_executed_context(),
            state_file=Path("state.json"),
            deps=SimpleNamespace(
                merge_batch_results_fn=lambda *_a, **_k: {"issues": []},
                build_import_provenance_fn=lambda **_k: {},
                safe_write_text_fn=lambda *_a, **_k: None,
                colorize_fn=lambda text, _tone=None: text,
                do_import_fn=lambda *_a, **_k: None,
                run_followup_scan_fn=lambda **_k: 0,
            ),
        )
    finally:
        phases_mod.merge_and_write_results = original_merge
        phases_mod.enforce_import_coverage = original_enforce
        phases_mod.import_and_finalize = original_import

    # Full run should preserve the original allow_partial=False.
    assert captured_kwargs["allow_partial"] is False
