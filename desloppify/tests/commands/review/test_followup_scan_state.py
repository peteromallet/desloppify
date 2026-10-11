"""Follow-up scans must keep the state file used for review import."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from desloppify.app.commands.review.batch.execution_results import import_and_finalize
from desloppify.app.commands.review.runner_process_impl.types import FollowupScanDeps
from desloppify.app.commands.runner.codex_batch import run_followup_scan


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("force_queue_bypass", [False, True])
def test_followup_scan_keeps_state_when_subprocess_cwd_changes(
    tmp_path, monkeypatch, absolute, force_queue_bypass
):
    monkeypatch.chdir(tmp_path)
    state_file = Path(".desloppify/custom scope/state-typescript.json")
    expected_state_file = state_file.resolve()
    if absolute:
        state_file = expected_state_file
    child_root = tmp_path / "project"
    subprocess_run = Mock(return_value=SimpleNamespace(returncode=0))

    code = run_followup_scan(
        lang_name="typescript",
        scan_path="src",
        state_file=state_file,
        deps=FollowupScanDeps(
            project_root=child_root,
            timeout_seconds=10,
            python_executable="python",
            subprocess_run=subprocess_run,
            timeout_error=TimeoutError,
            colorize_fn=lambda text, _style: text,
        ),
        force_queue_bypass=force_queue_bypass,
    )

    assert code == 0
    command = subprocess_run.call_args.args[0]
    assert command[command.index("--state") + 1] == str(expected_state_file)
    assert subprocess_run.call_args.kwargs["cwd"] == str(child_root)
    assert ("--force-rescan" in command) == force_queue_bypass


def test_batch_finalize_passes_the_state_file_used_for_import(tmp_path):
    state_file = tmp_path / ".desloppify/custom/state-typescript.json"
    followup = Mock(return_value=0)
    importer = Mock()
    import_and_finalize(
        do_import_fn=importer,
        run_followup_scan_fn=followup,
        merged_path=tmp_path / "merged.json",
        state={},
        lang=SimpleNamespace(name="typescript"),
        state_file=state_file,
        config={},
        allow_partial=False,
        successful_indexes=[0],
        failure_set=set(),
        append_run_log=lambda _line: None,
        args=SimpleNamespace(scan_after_import=True, path="src", state=None),
    )

    assert importer.call_args.args[3] == state_file
    followup.assert_called_once_with(
        lang_name="typescript", scan_path="src", state_file=state_file
    )
