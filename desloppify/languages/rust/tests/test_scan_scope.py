"""Regression coverage for nested worktrees and member-scoped Rust scans."""

import json
import shlex
import subprocess

import pytest

from desloppify.languages.rust.support import find_workspace_root
from desloppify.languages.rust.tools import (
    CARGO_ERROR_CMD,
    CLIPPY_WARNING_CMD,
    run_rustdoc_result,
    scope_cargo_command,
)


def workspace_with_members(root):
    root.mkdir(parents=True)
    (root / "Cargo.toml").write_text('[workspace]\nmembers = ["a", "b"]\n')
    for name in ("a", "b"):
        package = root / name
        (package / "src").mkdir(parents=True)
        (package / "Cargo.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "0.1.0"\n'
        )
        (package / "src" / "lib.rs").write_text("pub fn value() {}\n")
    return root


def test_workspace_discovery_stops_at_nested_worktree(tmp_path):
    outer = workspace_with_members(tmp_path / "outer")
    worktree = workspace_with_members(outer / ".worktrees" / "cleanup")
    (worktree / ".git").write_text("gitdir: ../../.git/worktrees/cleanup\n")

    assert find_workspace_root(worktree / "a" / "src") == worktree
    assert find_workspace_root(worktree) == worktree
    assert find_workspace_root(outer / "a" / "src") == outer


@pytest.mark.parametrize("command", [CARGO_ERROR_CMD, CLIPPY_WARNING_CMD])
def test_member_commands_preserve_checks_without_selecting_siblings(tmp_path, command):
    workspace = workspace_with_members(tmp_path / "workspace with spaces")
    scoped = scope_cargo_command(command, workspace / "a" / "src")
    args = shlex.split(scoped)

    assert "--workspace" not in args
    assert args[args.index("--manifest-path") + 1] == str(
        workspace / "a" / "Cargo.toml"
    )
    assert "--all-targets" in args
    assert "--all-features" in args
    assert "--message-format=json" in args
    assert scope_cargo_command(command, workspace) == command


@pytest.mark.parametrize("member_scan", [False, True])
def test_rustdoc_scopes_members_and_accepts_metadata_stderr(tmp_path, member_scan):
    workspace = workspace_with_members(tmp_path / "workspace")
    metadata = {
        "workspace_members": ["a-id", "b-id"],
        "packages": [
            {
                "id": f"{name}-id",
                "name": name,
                "manifest_path": str(workspace / name / "Cargo.toml"),
                "targets": [{"kind": ["lib"], "crate_types": ["lib"]}],
            }
            for name in ("a", "b")
        ],
    }
    commands = []

    def runner(args, **kwargs):
        assert kwargs["cwd"] == str(workspace)
        command = args[2] if args[:2] == ["/bin/sh", "-lc"] else " ".join(args)
        commands.append(command)
        if command.startswith("cargo metadata"):
            return subprocess.CompletedProcess(
                args, 0, json.dumps(metadata), "warning: optional workspace metadata\n"
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    scan_path = workspace / "a" / "src" if member_scan else workspace
    result = run_rustdoc_result(scan_path, run_subprocess=runner)

    assert result.status == "empty"
    assert any("--package a " in command for command in commands)
    assert any("--package b " in command for command in commands) is not member_scan


def test_rustdoc_metadata_failure_is_not_hidden(tmp_path):
    workspace = workspace_with_members(tmp_path / "workspace")

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "manifest could not be loaded")

    result = run_rustdoc_result(workspace, run_subprocess=runner)
    assert result.status == "error"
    assert "manifest could not be loaded" in result.message
