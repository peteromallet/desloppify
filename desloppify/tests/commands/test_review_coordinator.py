"""Tests for review coordinator baseline helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from desloppify.app.commands.review import coordinator as mod


def test_git_baseline_returns_none_tuple_when_status_raises_oserror():
    calls: list[list[str]] = []

    def _run(command, **_kwargs):
        calls.append(command)
        if command[-2:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n")
        raise OSError("git unavailable")

    assert mod.git_baseline(Path("/tmp/project"), subprocess_run=_run) == (None, None)
    assert len(calls) == 2


def test_git_baseline_hashes_status_output_when_both_commands_succeed():
    def _run(command, **_kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n")
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n?? bar.py\n")

    head, status_hash = mod.git_baseline(Path("/tmp/project"), subprocess_run=_run)

    assert head == "abc123"
    assert status_hash == mod._stable_json_sha256(" M foo.py\n?? bar.py\n")
