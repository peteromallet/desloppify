"""Runner/helper-heavy review command cases split from review_commands_cases.py."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import desloppify.app.commands.review.runner_failures as runner_failures_mod
import desloppify.app.commands.review.runner_packets as runner_packets_mod
import desloppify.app.commands.review.runner_parallel as runner_parallel_mod
import desloppify.app.commands.runner.codex_batch as runner_process_mod
from desloppify.app.commands.review.batch.orchestrator import do_run_batches
from desloppify.app.commands.review.batch.execution import CollectBatchResultsRequest
from desloppify.base.exception_sets import CommandError

runner_helpers_mod = SimpleNamespace(
    BatchExecutionOptions=runner_parallel_mod.BatchExecutionOptions,
    BatchResult=runner_parallel_mod.BatchResult,
    CodexBatchRunnerDeps=runner_process_mod.CodexBatchRunnerDeps,
    FollowupScanDeps=runner_process_mod.FollowupScanDeps,
    build_batch_import_provenance=runner_packets_mod.build_batch_import_provenance,
    build_blind_packet=runner_packets_mod.build_blind_packet,
    collect_batch_results=runner_parallel_mod.collect_batch_results,
    codex_batch_command=runner_process_mod.codex_batch_command,
    execute_batches=runner_parallel_mod.execute_batches,
    prepare_run_artifacts=runner_packets_mod.prepare_run_artifacts,
    print_failures=runner_failures_mod.print_failures,
    print_failures_and_raise=runner_failures_mod.print_failures_and_raise,
    run_codex_batch=runner_process_mod.run_codex_batch,
    run_followup_scan=runner_process_mod.run_followup_scan,
    run_stamp=runner_packets_mod.run_stamp,
    selected_batch_indexes=runner_packets_mod.selected_batch_indexes,
    sha256_file=runner_packets_mod.sha256_file,
    write_packet_snapshot=runner_packets_mod.write_packet_snapshot,
)


class TestCmdReviewPrepareRunnerHelpers:
    def test_collect_batch_results_recovers_execution_failure_with_valid_output(
        self, tmp_path
    ):

        output_file = tmp_path / "batch-1.raw.txt"
        output_file.write_text(
            json.dumps(
                {
                    "assessments": {"logic_clarity": 88.0},
                    "dimension_notes": {
                        "logic_clarity": {
                            "evidence": ["flow has one avoidable branch detour"],
                            "impact_scope": "module",
                            "fix_scope": "single_edit",
                            "confidence": "medium",
                        }
                    },
                    "issues": [],
                }
            )
        )

        def normalize_result(payload, _allowed_dims):
            notes = payload.get("dimension_notes", {})
            return payload.get("assessments", {}), payload.get("issues", []), notes, {}, {}, {}

        batch_results, failures = runner_helpers_mod.collect_batch_results(
            request=CollectBatchResultsRequest(
                selected_indexes=[0],
                failures=[0],
                output_files={0: output_file},
                allowed_dims={"logic_clarity"},
            ),
            extract_payload_fn=lambda raw: json.loads(raw),
            normalize_result_fn=normalize_result,
        )

        assert failures == []
        assert len(batch_results) == 1
        assert batch_results[0].assessments["logic_clarity"] == pytest.approx(88.0)

    def test_collect_batch_results_skips_full_log_fallback_when_stdout_empty(
        self, tmp_path
    ):

        results_dir = tmp_path / "results"
        logs_dir = tmp_path / "logs"
        results_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        raw_path = results_dir / "batch-1.raw.txt"
        log_path = logs_dir / "batch-1.log"
        log_path.write_text(
            "\n".join(
                [
                    "ATTEMPT 1/1",
                    "$ codex exec ...",
                    "Output schema:",
                    "{",
                    '  "assessments": {"logic_clarity": 91.0},',
                    '  "issues": []',
                    "}",
                    "",
                    "STDOUT:",
                    "",
                    "STDERR:",
                    "ERROR: stream disconnected before completion",
                ]
            )
        )

        seen_inputs: list[str] = []

        def extract_payload(raw: str) -> dict[str, object] | None:
            seen_inputs.append(raw)
            return None

        batch_results, failures = runner_helpers_mod.collect_batch_results(
            request=CollectBatchResultsRequest(
                selected_indexes=[0],
                failures=[],
                output_files={0: raw_path},
                allowed_dims={"logic_clarity"},
            ),
            extract_payload_fn=extract_payload,
            normalize_result_fn=lambda payload, _allowed: (  # noqa: ARG005
                payload.get("assessments", {}),
                payload.get("issues", []),
                payload.get("dimension_notes", {}),
                payload.get("dimension_judgment", {}),
                {},
                {},
            ),
        )

        assert batch_results == []
        assert failures == [0]
        assert len(seen_inputs) == 1
        assert "Output schema:" not in seen_inputs[0]

    def test_execute_batches_marks_progress_callback_exceptions_as_failures(self, tmp_path):

        def _broken_progress(*_args, **_kwargs):
            raise RuntimeError("progress callback failed")

        captured: list[tuple[int, str]] = []

        failures = runner_helpers_mod.execute_batches(
            tasks={0: lambda: 0},
            options=runner_helpers_mod.BatchExecutionOptions(
                run_parallel=True,
                max_parallel_workers=1,
                heartbeat_seconds=0.05,
            ),
            progress_fn=_broken_progress,
            error_log_fn=lambda idx, exc: captured.append((idx, str(exc))),
        )

        assert failures == []
        assert any("progress callback failed" in msg for _idx, msg in captured)

    def test_execute_batches_does_not_mask_internal_progress_typeerror(self):

        def _broken_typeerror_progress(event):
            _ = event
            raise TypeError("internal progress bug")

        captured: list[tuple[int, str]] = []
        failures = runner_helpers_mod.execute_batches(
            tasks={0: lambda: 0},
            options=runner_helpers_mod.BatchExecutionOptions(run_parallel=False),
            progress_fn=_broken_typeerror_progress,
            error_log_fn=lambda idx, exc: captured.append((idx, str(exc))),
        )

        assert failures == []
        assert any("internal progress bug" in msg for _idx, msg in captured)

    def test_execute_batches_heartbeat_error_log_failure_is_nonfatal(self):

        def _heartbeat_only_failure(event):
            if getattr(event, "event", "") == "heartbeat":
                raise RuntimeError("heartbeat callback failed")

        def _slow_success():
            time.sleep(0.12)
            return 0

        failures = runner_helpers_mod.execute_batches(
            tasks={0: _slow_success},
            options=runner_helpers_mod.BatchExecutionOptions(
                run_parallel=True,
                max_parallel_workers=1,
                heartbeat_seconds=0.02,
            ),
            progress_fn=_heartbeat_only_failure,
            # Intentionally fragile callback: idx=-1 used by heartbeat is unsupported.
            error_log_fn=lambda idx, exc: {0: []}[idx].append(str(exc)),
        )

        assert failures == []

    def test_print_failures_and_raise_shows_codex_missing_hint(self, tmp_path, capsys):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "$ codex exec --ephemeral ...\n\nRUNNER ERROR:\n[Errno 2] No such file or directory: 'codex'\n"
        )
        with pytest.raises(CommandError) as exc_info:
            runner_helpers_mod.print_failures_and_raise(
                failures=[0],
                packet_path=tmp_path / "packet.json",
                logs_dir=logs_dir,
                colorize_fn=lambda text, _style: text,
            )
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Environment hints:" in err
        assert "Runner CLI not found on PATH" in err

    def test_print_failures_and_raise_shows_codex_auth_hint(self, tmp_path, capsys):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "$ codex exec --ephemeral ...\n\nSTDERR:\nAuthentication failed: please login first.\n"
        )
        with pytest.raises(CommandError) as exc_info:
            runner_helpers_mod.print_failures_and_raise(
                failures=[0],
                packet_path=tmp_path / "packet.json",
                logs_dir=logs_dir,
                colorize_fn=lambda text, _style: text,
            )
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Environment hints:" in err
        assert "codex login" in err

    def test_print_failures_reports_categories_without_exit(self, tmp_path, capsys):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text("$ codex ...\nTIMEOUT after 60s\n")
        (logs_dir / "batch-2.log").write_text(
            "$ codex ...\nSTDERR:\nAuthentication failed: please login first.\n"
        )

        runner_helpers_mod.print_failures(
            failures=[0, 1, 2],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Failure categories:" in err
        assert "timeout=1" in err
        assert "runner auth=1" in err
        assert "missing log=1" in err

    def test_print_failures_reports_stream_disconnect_category(self, tmp_path, capsys):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "$ codex ...\nSTDERR:\nERROR: stream disconnected before completion\n"
        )

        runner_helpers_mod.print_failures(
            failures=[0],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Failure categories:" in err
        assert "stream disconnect=1" in err
        assert "Connectivity tuning:" in err

    def test_print_failures_reports_usage_limit_category_with_unicode_apostrophe(
        self, tmp_path, capsys
    ):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            
                "$ codex ...\nSTDERR:\n"
                "You\u2019ve hit your usage limit. To get more access now, "
                "send a request to your admin or try again at 8:49 PM.\n"
            
        )

        runner_helpers_mod.print_failures(
            failures=[0],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Failure categories:" in err
        assert "usage limit=1" in err
        assert "Environment hints:" in err
        assert "usage quota is exhausted" in err

    def test_print_failures_reports_codex_backend_connectivity_hint(
        self, tmp_path, capsys
    ):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "\n".join(
                [
                    "$ codex ...",
                    "STDERR:",
                    "ERROR: stream disconnected before completion:",
                    "error sending request for url (https://chatgpt.com/backend-api/codex/responses)",
                ]
            )
        )

        runner_helpers_mod.print_failures(
            failures=[0],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Environment hints:" in err
        assert "cannot reach chatgpt.com backend" in err
        assert "--external-start --external-runner claude" in err


    def test_print_failures_reports_sandbox_hint_for_backend_disconnect(
        self, tmp_path, capsys
    ):

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "\n".join(
                [
                    "$ codex ...",
                    "WARNING: proceeding, even though we could not update PATH: Operation not permitted (os error 1)",
                    "STDERR:",
                    "ERROR: stream disconnected before completion:",
                    "error sending request for url (https://chatgpt.com/backend-api/codex/responses)",
                ]
            )
        )

        runner_helpers_mod.print_failures(
            failures=[0],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Sandbox hint:" in err
        assert "restricted sandbox execution" in err

    def test_run_followup_scan_returns_nonzero_code(self, tmp_path):

        mock_run = MagicMock(return_value=MagicMock(returncode=9))
        code = runner_helpers_mod.run_followup_scan(
            lang_name="typescript",
            scan_path=str(tmp_path),
            deps=runner_helpers_mod.FollowupScanDeps(
                project_root=tmp_path,
                timeout_seconds=60,
                python_executable="python",
                subprocess_run=mock_run,
                timeout_error=TimeoutError,
                colorize_fn=lambda text, _: text,
            ),
        )
        assert code == 9

    def test_run_followup_scan_default_respects_queue_gate(self, tmp_path):

        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        runner_helpers_mod.run_followup_scan(
            lang_name="typescript",
            scan_path=str(tmp_path),
            deps=runner_helpers_mod.FollowupScanDeps(
                project_root=tmp_path,
                timeout_seconds=60,
                python_executable="python",
                subprocess_run=mock_run,
                timeout_error=TimeoutError,
                colorize_fn=lambda text, _: text,
            ),
        )

        cmd = mock_run.call_args.args[0]
        assert "--force-rescan" not in cmd
        assert "--attest" not in cmd

    def test_do_run_batches_scan_after_import_exits_on_failed_followup(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["high_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["high_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = True

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.runtime_paths.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.runtime_paths.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.runtime_paths.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator._do_import",
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.execute_batches",
                return_value=[],
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.collect_batch_results",
                return_value=(
                    [
                        {
                            "assessments": {},
                            "dimension_notes": {},
                            "issues": [],
                            "quality": {},
                        }
                    ],
                    [],
                ),
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator._merge_batch_results",
                return_value={"assessments": {}, "dimension_notes": {}, "issues": []},
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.run_followup_scan",
                return_value=7,
            ),
        ):
            with pytest.raises(CommandError) as exc_info:
                do_run_batches(args, empty_state, lang, "fake_sp", config={})

        assert exc_info.value.exit_code == 7

    def test_do_run_batches_success_path_imports_merged_results(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["high_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["high_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False
        args.allow_partial = True
        args.save_run_log = True
        args.run_log_file = None

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.runtime_paths.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.runtime_paths.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.runtime_paths.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.execution_phases.scored_dimensions_for_lang",
                return_value=["high_level_elegance"],
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.execute_batches",
                return_value=[],
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.collect_batch_results",
                return_value=(
                    [
                        runner_parallel_mod.BatchResult(
                            batch_index=1,
                            assessments={"high_level_elegance": 84.0},
                            dimension_notes={},
                            issues=[],
                            quality={},
                        )
                    ],
                    [],
                ),
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator._merge_batch_results",
                return_value={
                    "assessments": {"high_level_elegance": 84.0},
                    "dimension_notes": {},
                    "issues": [],
                    "review_quality": {},
                },
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.run_followup_scan",
            ) as run_followup_scan,
            patch(
                "desloppify.app.commands.review.batch.orchestrator._do_import",
            ) as do_import,
        ):
            do_run_batches(args, empty_state, lang, "fake_sp", config={})

        do_import.assert_called_once()
        run_followup_scan.assert_not_called()

    def test_do_run_batches_keyboard_interrupt_writes_partial_summary(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["high_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["high_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False
        args.allow_partial = False
        args.save_run_log = True
        args.run_log_file = None

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.runtime_paths.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.runtime_paths.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.runtime_paths.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.orchestrator.execute_batches",
                side_effect=KeyboardInterrupt,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                do_run_batches(args, empty_state, lang, "fake_sp", config={})

        assert exc_info.value.code == 130
        summary_files = sorted(runs_dir.glob("*/run_summary.json"))
        assert len(summary_files) == 1
        summary_payload = json.loads(summary_files[0].read_text())
        assert summary_payload["interrupted"] is True
        assert summary_payload["interruption_reason"] == "keyboard_interrupt"
        assert summary_payload["successful_batches"] == []
        assert summary_payload["failed_batches"] == []
        assert summary_payload["batches"]["1"]["status"] == "interrupted"

        run_log_path = Path(summary_payload["run_log"])
        run_log_text = run_log_path.read_text()
        assert "run-interrupted reason=keyboard_interrupt" in run_log_text
