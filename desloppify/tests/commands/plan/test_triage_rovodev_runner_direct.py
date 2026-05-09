"""Direct unit tests for the Rovo Dev triage runner and pipeline wrapper."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline as codex_pipeline_mod
import desloppify.app.commands.plan.triage.runner.rovodev_pipeline as rovodev_pipeline_mod
import desloppify.app.commands.plan.triage.runner.rovodev_runner as rovodev_runner_mod
import desloppify.app.commands.plan.triage.runner.stage_runner_override as override_mod
from desloppify.app.commands.plan.triage.runner.codex_runner import (
    TriageStageRunResult,
)


def test_run_triage_stage_rovodev_returns_typed_result_for_empty_prompt(
    tmp_path: Path,
) -> None:
    """Empty prompts short-circuit with a deterministic typed result."""
    output_file = tmp_path / "out.txt"
    log_file = tmp_path / "out.log"

    result = rovodev_runner_mod.run_triage_stage_rovodev(
        prompt="   ",
        repo_root=tmp_path,
        output_file=output_file,
        log_file=log_file,
    )

    assert isinstance(result, TriageStageRunResult)
    assert result.exit_code == 2
    assert result.reason == "empty_prompt"
    assert "Empty triage prompt" in log_file.read_text()


def test_run_triage_stage_rovodev_delegates_to_run_rovodev_batch(
    tmp_path: Path,
) -> None:
    """The triage runner forwards real prompts to the rovodev batch runner."""
    output_file = tmp_path / "out.txt"
    log_file = tmp_path / "out.log"
    output_file.write_text("ok")  # so the default validate_output_fn passes

    with patch.object(
        rovodev_runner_mod,
        "run_rovodev_batch",
        return_value=0,
    ) as mock_run:
        result = rovodev_runner_mod.run_triage_stage_rovodev(
            prompt="evaluate clarity",
            repo_root=tmp_path,
            output_file=output_file,
            log_file=log_file,
            timeout_seconds=120,
        )

    assert result.ok
    assert result.exit_code == 0
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["prompt"] == "evaluate clarity"
    assert call_kwargs["output_file"] == output_file
    assert call_kwargs["log_file"] == log_file
    # The runner deps must use the rovodev validate_output_fn (callable).
    assert callable(call_kwargs["deps"].validate_output_fn)


def test_run_triage_stage_rovodev_records_command_preview(tmp_path: Path) -> None:
    """The log file is seeded with the runner command preview before execution."""
    output_file = tmp_path / "out.txt"
    log_file = tmp_path / "out.log"
    output_file.write_text("ok")

    with patch.object(rovodev_runner_mod, "run_rovodev_batch", return_value=0):
        rovodev_runner_mod.run_triage_stage_rovodev(
            prompt="hi",
            repo_root=tmp_path,
            output_file=output_file,
            log_file=log_file,
        )

    log_text = log_file.read_text()
    assert "RUNNER COMMAND PREVIEW" in log_text
    assert "rovodev" in log_text


def test_run_triage_stage_rovodev_propagates_runner_failure(tmp_path: Path) -> None:
    """A non-zero runner exit becomes a typed failure result."""
    output_file = tmp_path / "out.txt"
    log_file = tmp_path / "out.log"

    with patch.object(rovodev_runner_mod, "run_rovodev_batch", return_value=7):
        result = rovodev_runner_mod.run_triage_stage_rovodev(
            prompt="evaluate",
            repo_root=tmp_path,
            output_file=output_file,
            log_file=log_file,
        )

    assert not result.ok
    assert result.exit_code == 7
    assert result.reason == "runner_exit_7"


def test_run_rovodev_pipeline_overrides_then_restores_runner(tmp_path: Path) -> None:
    """The wrapper sets the override for the call and restores it afterwards."""
    args = argparse.Namespace(stage_timeout_seconds=60, dry_run=True)

    sentinel_state_before_runner = override_mod._STAGE_RUNNER_OVERRIDE
    sentinel_state_before_label = override_mod._RUNNER_NAME_OVERRIDE

    captured: dict[str, object] = {}

    def fake_pipeline(args, *, stages_to_run, services=None) -> None:  # noqa: ARG001
        captured["runner"] = override_mod._STAGE_RUNNER_OVERRIDE
        captured["label"] = override_mod._RUNNER_NAME_OVERRIDE

    with patch.object(codex_pipeline_mod, "run_codex_pipeline", side_effect=fake_pipeline):
        rovodev_pipeline_mod.run_rovodev_pipeline(
            args, stages_to_run=["observe"], services=MagicMock()
        )

    assert captured["runner"] is rovodev_runner_mod.run_triage_stage_rovodev
    assert captured["label"] == "rovodev"
    # The wrapper must restore the previous module-level state.
    assert override_mod._STAGE_RUNNER_OVERRIDE is sentinel_state_before_runner
    assert override_mod._RUNNER_NAME_OVERRIDE is sentinel_state_before_label


def test_run_rovodev_pipeline_restores_override_on_exception(tmp_path: Path) -> None:
    """If the inner pipeline raises, the overrides are still restored."""
    args = argparse.Namespace(stage_timeout_seconds=60, dry_run=True)

    sentinel_runner = override_mod._STAGE_RUNNER_OVERRIDE
    sentinel_label = override_mod._RUNNER_NAME_OVERRIDE

    with patch.object(
        codex_pipeline_mod,
        "run_codex_pipeline",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            rovodev_pipeline_mod.run_rovodev_pipeline(
                args, stages_to_run=["observe"], services=MagicMock()
            )

    assert override_mod._STAGE_RUNNER_OVERRIDE is sentinel_runner
    assert override_mod._RUNNER_NAME_OVERRIDE is sentinel_label


def test_triage_parser_accepts_rovodev_runner() -> None:
    from desloppify.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(
        ["plan", "triage", "--run-stages", "--runner", "rovodev"]
    )
    assert args.runner == "rovodev"
    assert args.run_stages is True


def test_triage_runner_commands_includes_rovodev() -> None:
    from desloppify.engine._plan.triage.playbook import (
        TRIAGE_RUNNERS,
        triage_run_stages_command,
        triage_runner_commands,
    )

    assert "rovodev" in TRIAGE_RUNNERS
    cmds = triage_runner_commands()
    runner_labels = {label for label, _cmd in cmds}
    assert "Rovo Dev" in runner_labels
    rovodev_cmd = triage_run_stages_command(runner="rovodev")
    assert rovodev_cmd == "desloppify plan triage --run-stages --runner rovodev"


def test_triage_run_stages_command_with_only_stages_for_rovodev() -> None:
    from desloppify.engine._plan.triage.playbook import triage_run_stages_command

    cmd = triage_run_stages_command(runner="rovodev", only_stages=["observe", "reflect"])
    assert cmd == "desloppify plan triage --run-stages --runner rovodev --only-stages observe,reflect"


def test_workflow_dispatches_rovodev_runner() -> None:
    """`_run_staged_runner` routes ``--runner rovodev`` to the rovodev pipeline."""
    import desloppify.app.commands.plan.triage.workflow as workflow_mod

    args = argparse.Namespace(
        runner="rovodev",
        only_stages=None,
        stage_timeout_seconds=60,
        dry_run=True,
    )
    services = MagicMock()
    with patch.object(workflow_mod, "run_rovodev_pipeline") as mock_rovodev, patch.object(
        workflow_mod, "run_codex_pipeline"
    ) as mock_codex, patch.object(
        workflow_mod, "run_claude_orchestrator"
    ) as mock_claude:
        workflow_mod._run_staged_runner(args, services=services)

    mock_rovodev.assert_called_once()
    mock_codex.assert_not_called()
    mock_claude.assert_not_called()


def test_workflow_unknown_runner_message_lists_rovodev() -> None:
    """Unknown runner errors should mention rovodev as a valid choice."""
    import desloppify.app.commands.plan.triage.workflow as workflow_mod
    from desloppify.base.exception_sets import CommandError

    args = argparse.Namespace(runner="nope", only_stages=None)
    with pytest.raises(CommandError) as excinfo:
        workflow_mod._run_staged_runner(args, services=MagicMock())

    assert "rovodev" in str(excinfo.value)


def test_active_stage_runner_propagates_override_to_observe_and_sense() -> None:
    """Regression: parallel sub-runners (observe, sense-check) must honour
    the per-pipeline stage runner override. Before this fix, ``run_observe``
    and ``run_sense_check`` imported ``run_triage_stage`` directly, so
    ``--runner rovodev`` would silently fall back to ``codex exec`` for
    those stages and fail with exit 127 on systems without ``codex``
    installed.
    """
    import desloppify.app.commands.plan.triage.runner.orchestrator_codex_observe as observe_mod
    import desloppify.app.commands.plan.triage.runner.orchestrator_codex_sense as sense_mod
    from desloppify.app.commands.plan.triage.runner.codex_runner import (
        run_triage_stage as codex_default,
    )

    # Both sub-runners must consult the central registry (not the codex
    # default directly).
    assert observe_mod.active_stage_runner is override_mod.active_stage_runner
    assert sense_mod.active_stage_runner is override_mod.active_stage_runner

    # Default behaviour: no override → codex stage runner.
    assert override_mod._STAGE_RUNNER_OVERRIDE is None
    assert override_mod.active_stage_runner() is codex_default

    # With override installed: the active runner is the override.
    sentinel = object()
    override_mod.set_stage_runner_override(sentinel, "rovodev")
    try:
        assert override_mod.active_stage_runner() is sentinel
        assert override_mod.active_runner_name() == "rovodev"
    finally:
        override_mod.set_stage_runner_override(None, None)
    assert override_mod.active_stage_runner() is codex_default
