"""Direct tests for review batch execution helper modules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.app.commands.review.batch import execution_dry_run as dry_run_mod
from desloppify.app.commands.review.batch import execution_progress as progress_mod
from desloppify.app.commands.review.batch import execution_results as results_mod
from desloppify.app.commands.review.batch import orchestrator as orchestrator_mod
from desloppify.app.commands.review.runner_parallel import BatchProgressEvent
from desloppify.base.exception_sets import CommandError


def _safe_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_maybe_handle_dry_run_false_noop(tmp_path: Path) -> None:
    logs: list[str] = []
    handled = dry_run_mod.maybe_handle_dry_run(
        args=SimpleNamespace(dry_run=False),
        stamp="s1",
        selected_indexes=[0],
        run_dir=tmp_path / "run",
        logs_dir=tmp_path / "run" / "logs",
        immutable_packet_path=tmp_path / "immutable.json",
        prompt_packet_path=tmp_path / "prompt.json",
        prompt_files={0: tmp_path / "run" / "prompts" / "batch-1.md"},
        output_files={0: tmp_path / "run" / "results" / "batch-1.json"},
        safe_write_text_fn=_safe_write_text,
        colorize_fn=lambda text, _tone=None: text,
        append_run_log=logs.append,
    )
    assert handled is False
    assert logs == []


def test_maybe_handle_dry_run_writes_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    logs: list[str] = []
    handled = dry_run_mod.maybe_handle_dry_run(
        args=SimpleNamespace(dry_run=True),
        stamp="s2",
        selected_indexes=[0, 2],
        run_dir=run_dir,
        logs_dir=run_dir / "logs",
        immutable_packet_path=tmp_path / "immutable.json",
        prompt_packet_path=tmp_path / "prompt.json",
        prompt_files={
            0: run_dir / "prompts" / "batch-1.md",
            2: run_dir / "prompts" / "batch-3.md",
        },
        output_files={
            0: run_dir / "results" / "batch-1.json",
            2: run_dir / "results" / "batch-3.json",
        },
        safe_write_text_fn=_safe_write_text,
        colorize_fn=lambda text, _tone=None: text,
        append_run_log=logs.append,
    )
    assert handled is True
    summary = json.loads((run_dir / "run_summary.json").read_text())
    assert summary["runner"] == "dry-run"
    assert summary["selected_batches"] == [1, 3]
    assert "run-finished dry-run" in logs


def test_progress_reporter_tracks_lifecycle_and_stalls(tmp_path: Path) -> None:
    logs: list[str] = []
    batch_status: dict[str, dict[str, object]] = {}
    stall_warned: set[int] = set()
    reporter = progress_mod.build_progress_reporter(
        batch_positions={0: 1, 1: 2},
        batch_status=batch_status,
        stall_warned_batches=stall_warned,
        total_batches=2,
        stall_warning_seconds=5.0,
        prompt_files={0: tmp_path / "p0", 1: tmp_path / "p1"},
        output_files={0: tmp_path / "o0", 1: tmp_path / "o1"},
        log_files={0: tmp_path / "l0", 1: tmp_path / "l1"},
        append_run_log=logs.append,
        colorize_fn=lambda text, _tone=None: text,
    )
    reporter(BatchProgressEvent(batch_index=0, event="queued"))
    reporter(BatchProgressEvent(batch_index=0, event="start"))
    reporter(
        BatchProgressEvent(
            batch_index=0,
            event="heartbeat",
            details={"active_batches": [0], "queued_batches": [1], "elapsed_seconds": {0: 7}},
        )
    )
    reporter(BatchProgressEvent(batch_index=0, event="done", code=0, details={"elapsed_seconds": 9}))
    assert batch_status["1"]["status"] == "succeeded"
    assert batch_status["1"]["elapsed_seconds"] == 9
    assert 0 not in stall_warned
    assert any("stall-warning" in line for line in logs)
    assert any("batch-done batch=1" in line for line in logs)


def test_progress_heartbeat_helper_contracts() -> None:
    active, queued, elapsed = progress_mod._parse_heartbeat_details(
        {
            "active_batches": [0, "1", 2],
            "queued_batches": [3, None, 4],
            "elapsed_seconds": {0: 4.8, 1: "bad", 2: 9},
        }
    )
    assert active == [0, 2]
    assert queued == [3, 4]
    assert elapsed == {0: 4.8, 2: 9.0}

    segments = progress_mod._render_heartbeat_segments(
        active=[0, 2, 5],
        elapsed_seconds=elapsed,
    )
    assert segments == ["#1:4s", "#3:9s", "#6:0s"]

    newly_warned = progress_mod._find_newly_stalled_batches(
        active=[0, 1, 2],
        elapsed_seconds={0: 3.0, 1: 7.0, 2: 8.0},
        stall_warning_seconds=6.0,
        stall_warned_batches={1},
    )
    assert newly_warned == [2]
    assert (
        progress_mod._find_newly_stalled_batches(
            active=[2],
            elapsed_seconds={2: 99.0},
            stall_warning_seconds=0.0,
            stall_warned_batches=set(),
        )
        == []
    )


def test_collect_and_reconcile_results_marks_failure_modes(tmp_path: Path) -> None:
    out0 = tmp_path / "out0.json"
    out0.write_text("{}")
    output_files = {0: out0, 1: tmp_path / "out1.json", 2: tmp_path / "out2.json"}
    batch_status: dict[str, dict[str, object]] = {}
    batch_results, successful, failures, failure_set = results_mod.collect_and_reconcile_results(
        collect_batch_results_fn=lambda _request: ([{"ok": True}], [1, 2]),
        request=orchestrator_mod.review_batches_mod.CollectBatchResultsRequest(
            selected_indexes=[0, 1, 2],
            failures=[1],
            output_files=output_files,
            allowed_dims={"design_coherence"},
        ),
        execution_failures=[1],
        batch_positions={0: 1, 1: 2, 2: 3},
        batch_status=batch_status,
    )
    assert batch_results == [{"ok": True}]
    assert successful == [0]
    assert failures == [1, 2]
    assert failure_set == {1, 2}
    assert batch_status["1"]["status"] == "succeeded"
    assert batch_status["2"]["status"] == "failed"
    assert batch_status["3"]["status"] == "missing_output"


def test_merge_and_finalize_helpers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        results_mod,
        "collect_reviewed_files_from_batches",
        lambda **_kwargs: ["a.py", "b.py"],
    )
    monkeypatch.setattr(results_mod, "normalize_dimension_list", lambda dims: [str(d) for d in dims if d])
    monkeypatch.setattr(
        results_mod,
        "print_import_dimension_coverage_notice",
        lambda **_kwargs: ["missing_dim"],
    )
    monkeypatch.setattr(results_mod, "print_review_quality", lambda *_args, **_kwargs: None)

    run_dir = tmp_path / "run"
    merged_path, missing = results_mod.merge_and_write_results(
        merge_batch_results_fn=lambda _batch_results: {
            "assessments": {"design_coherence": 80.0},
            "issues": [{"dimension": "type_safety"}],
            "review_quality": {"overall": 0.8},
        },
        build_import_provenance_fn=lambda **_kwargs: {"trusted": True},
        batch_results=[{"dummy": True}],
        batches=[{"name": "Full codebase sweep"}],
        successful_indexes=[0],
        packet={"dimensions": ["design_coherence"], "total_files": 10},
        packet_dimensions=["design_coherence"],
        scored_dimensions=["design_coherence", "type_safety"],
        scan_path=".",
        runner="codex",
        prompt_packet_path=tmp_path / "packet.json",
        stamp="r1",
        run_dir=run_dir,
        safe_write_text_fn=_safe_write_text,
        colorize_fn=lambda text, _tone=None: text,
    )
    assert merged_path.exists()
    assert missing == ["missing_dim"]
    merged_payload = json.loads(merged_path.read_text())
    assert merged_payload["review_scope"]["reviewed_files_count"] == 2
    assert merged_payload["provenance"]["trusted"] is True
    assert merged_payload["review_quality"]["overall"] == 0.8

    logs: list[str] = []
    args = SimpleNamespace(scan_after_import=True, path=".")
    results_mod.import_and_finalize(
        do_import_fn=lambda *_args, **_kwargs: None,
        run_followup_scan_fn=lambda **_kwargs: 0,
        merged_path=merged_path,
        state={},
        lang=SimpleNamespace(name="python"),
        state_file=tmp_path / "state.json",
        config={},
        allow_partial=False,
        successful_indexes=[0],
        failure_set={1},
        append_run_log=logs.append,
        args=args,
    )
    assert any("run-finished" in line for line in logs)


def test_import_and_finalize_raises_when_followup_scan_fails(tmp_path: Path) -> None:
    merged_path = tmp_path / "merged.json"
    merged_path.write_text("{}")
    args = SimpleNamespace(scan_after_import=True, path=".")
    with pytest.raises(CommandError):
        results_mod.import_and_finalize(
            do_import_fn=lambda *_args, **_kwargs: None,
            run_followup_scan_fn=lambda **_kwargs: 7,
            merged_path=merged_path,
            state={},
            lang=SimpleNamespace(name="python"),
            state_file=tmp_path / "state.json",
            config={},
            allow_partial=False,
            successful_indexes=[],
            failure_set=set(),
            append_run_log=lambda _msg: None,
            args=args,
        )


def test_do_import_run_reuses_merge_result_boundary(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "batch-1.raw.txt").write_text("{}")

    blind_packet = run_dir / "blind.json"
    blind_packet.write_text("{}")
    immutable_packet = run_dir / "packet.json"
    immutable_packet.write_text(
        json.dumps(
            {
                "dimensions": ["mid_level_elegance"],
                "investigation_batches": [
                    {
                        "name": "mid_level_elegance",
                        "dimensions": ["mid_level_elegance"],
                        "files_to_read": ["a.py"],
                    }
                ],
            }
        )
    )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "runner": "codex",
                "run_stamp": "r1",
                "selected_batches": [1],
                "successful_batches": [1],
                "blind_packet": str(blind_packet),
                "immutable_packet": str(immutable_packet),
            }
        )
    )

    monkeypatch.setattr(
        orchestrator_mod,
        "collect_batch_results",
        lambda **_kwargs: ([{"dummy": True}], []),
    )

    merge_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        orchestrator_mod,
        "_merge_and_write_results",
        lambda **kwargs: (
            merge_calls.append(kwargs)
            or (run_dir / "holistic_issues_merged.json", ["missing_dim"])
        ),
    )
    coverage_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        orchestrator_mod,
        "_enforce_import_coverage",
        lambda **kwargs: coverage_calls.append(kwargs),
    )
    monkeypatch.setattr(orchestrator_mod, "_do_import", lambda *_args, **_kwargs: None)

    orchestrator_mod.do_import_run(
        str(run_dir),
        state={},
        lang=SimpleNamespace(name="python"),
        state_file=str(tmp_path / "state.json"),
        config={},
        allow_partial=True,
        scan_after_import=False,
        dry_run=True,
    )

    assert len(merge_calls) == 1
    assert merge_calls[0]["merge_batch_results_fn"] is orchestrator_mod._merge_batch_results
    assert len(coverage_calls) == 1
    assert coverage_calls[0]["allow_partial"] is True


def test_do_import_run_recollects_batches_from_selected_indexes(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "batch-1.raw.txt").write_text("{}")
    (results_dir / "batch-2.raw.txt").write_text("{}")

    blind_packet = run_dir / "blind.json"
    blind_packet.write_text("{}")
    immutable_packet = run_dir / "packet.json"
    immutable_packet.write_text(
        json.dumps(
            {
                "dimensions": ["mid_level_elegance"],
                "investigation_batches": [
                    {
                        "name": "mid_level_elegance",
                        "dimensions": ["mid_level_elegance"],
                        "files_to_read": ["a.py"],
                    }
                ],
            }
        )
    )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "runner": "codex",
                "run_stamp": "r2",
                "selected_batches": [1, 2],
                "successful_batches": [1],
                "failed_batches": [2],
                "blind_packet": str(blind_packet),
                "immutable_packet": str(immutable_packet),
            }
        )
    )

    collect_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        orchestrator_mod,
        "collect_batch_results",
        lambda **kwargs: (collect_calls.append(kwargs) or ([{"dummy": True}], [])),
    )
    monkeypatch.setattr(
        orchestrator_mod,
        "_merge_and_write_results",
        lambda **_kwargs: (run_dir / "holistic_issues_merged.json", []),
    )
    monkeypatch.setattr(
        orchestrator_mod,
        "_enforce_import_coverage",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(orchestrator_mod, "_do_import", lambda *_args, **_kwargs: None)

    orchestrator_mod.do_import_run(
        str(run_dir),
        state={},
        lang=SimpleNamespace(name="python"),
        state_file=str(tmp_path / "state.json"),
        config={},
        allow_partial=True,
        scan_after_import=False,
        dry_run=True,
    )

    assert len(collect_calls) == 1
    assert collect_calls[0]["request"].selected_indexes == [0, 1]


def test_try_load_prepared_packet_accepts_matching_contract(tmp_path: Path, monkeypatch) -> None:
    expected_contract = {
        "path": "/repo",
        "state_path": "/repo/.desloppify/state.json",
        "dimensions": [],
        "retrospective": False,
        "retrospective_max_issues": 30,
        "retrospective_max_batch_items": 20,
        "config_hash": "abc",
    }
    query_path = tmp_path / "query.json"
    query_path.write_text(
        json.dumps(
            {
                "investigation_batches": [{"name": "mid_level_elegance"}],
                "prepared_packet_contract": dict(expected_contract),
            }
        )
    )
    monkeypatch.setattr(orchestrator_mod, "query_file_path", lambda: query_path)

    packet, mismatch = orchestrator_mod._try_load_prepared_packet(
        expected_contract=expected_contract
    )
    assert packet is not None
    assert mismatch is None


def test_try_load_prepared_packet_rejects_contract_mismatch(tmp_path: Path, monkeypatch) -> None:
    expected_contract = {
        "path": "/repo/new",
        "state_path": "/repo/.desloppify/state.json",
        "dimensions": [],
        "retrospective": False,
        "retrospective_max_issues": 30,
        "retrospective_max_batch_items": 20,
        "config_hash": "abc",
    }
    query_path = tmp_path / "query.json"
    query_path.write_text(
        json.dumps(
            {
                "investigation_batches": [{"name": "mid_level_elegance"}],
                "prepared_packet_contract": {
                    **expected_contract,
                    "path": "/repo/old",
                },
            }
        )
    )
    monkeypatch.setattr(orchestrator_mod, "query_file_path", lambda: query_path)

    packet, mismatch = orchestrator_mod._try_load_prepared_packet(
        expected_contract=expected_contract
    )
    assert packet is None
    assert mismatch == "contract field 'path' differs"


def test_try_load_prepared_packet_rejects_state_scope_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected_contract = {
        "path": "/repo",
        "state_path": "/repo/.desloppify/state-a.json",
        "dimensions": [],
        "retrospective": False,
        "retrospective_max_issues": 30,
        "retrospective_max_batch_items": 20,
        "config_hash": "abc",
    }
    query_path = tmp_path / "query.json"
    query_path.write_text(
        json.dumps(
            {
                "investigation_batches": [{"name": "mid_level_elegance"}],
                "prepared_packet_contract": {
                    **expected_contract,
                    "state_path": "/repo/.desloppify/state-b.json",
                },
            }
        )
    )
    monkeypatch.setattr(orchestrator_mod, "query_file_path", lambda: query_path)

    packet, mismatch = orchestrator_mod._try_load_prepared_packet(
        expected_contract=expected_contract
    )

    assert packet is None
    assert mismatch == "contract field 'state_path' differs"


def test_build_batch_run_deps_selects_opencode_runner(tmp_path: Path) -> None:
    deps = orchestrator_mod._build_batch_run_deps(
        args=SimpleNamespace(runner="opencode"),
        policy=SimpleNamespace(
            batch_timeout_seconds=60,
            heartbeat_seconds=1.0,
            stall_kill_seconds=30,
            batch_max_retries=1,
            batch_retry_backoff_seconds=0.5,
        ),
        project_root=tmp_path,
    )

    assert deps.run_codex_batch_fn.func is orchestrator_mod.run_opencode_batch


def test_build_batch_run_deps_keeps_codex_runner_default(tmp_path: Path) -> None:
    deps = orchestrator_mod._build_batch_run_deps(
        args=SimpleNamespace(runner="codex"),
        policy=SimpleNamespace(
            batch_timeout_seconds=60,
            heartbeat_seconds=1.0,
            stall_kill_seconds=30,
            batch_max_retries=1,
            batch_retry_backoff_seconds=0.5,
        ),
        project_root=tmp_path,
    )

    assert deps.run_codex_batch_fn.func is orchestrator_mod.run_codex_batch
