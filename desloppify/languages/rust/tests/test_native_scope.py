"""Native Cargo scope and partial-coverage regressions using synthetic workspaces."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.languages.rust.commands import cmd_clippy_warning
from desloppify.languages.rust.phases import tool_phase_clippy
from desloppify.languages.rust.support import build_workspace_package_index
from desloppify.languages.rust.tools import (
    CLIPPY_WARNING_CMD,
    parse_cargo_errors,
    parse_clippy_messages,
    parse_rustdoc_messages,
    run_cargo_result,
)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["a", "b"]\n')
    for name in ("a", "b"):
        member = tmp_path / name
        (member / "src").mkdir(parents=True)
        (member / "Cargo.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "0.1.0"\n'
        )
        (member / "src/lib.rs").write_text("pub fn value() {}\n")
    return tmp_path


def diagnostic(filename, *, level="warning", line=1):
    return json.dumps({
        "reason": "compiler-message",
        "message": {
            "level": level,
            "message": "example diagnostic",
            "spans": [{
                "file_name": str(filename), "line_start": line, "is_primary": True,
            }],
        },
    })


@pytest.mark.parametrize("parser", [
    parse_clippy_messages, parse_cargo_errors, parse_rustdoc_messages,
])
def test_native_paths_are_workspace_based_but_scan_relative(workspace, parser):
    output = "\n".join(diagnostic(name, level="error") for name in (
        "a/src/lib.rs", "b/src/lib.rs", "external/dependency/src/lib.rs",
        workspace / "a/src/other.rs", workspace.parent / "outside.rs",
        "a/../b/src/lib.rs",
    ))
    assert [entry["file"] for entry in parser(output, workspace / "a")] == [
        "src/lib.rs", "src/other.rs",
    ]
    assert [entry["file"] for entry in parser(output, workspace / "a/src")] == [
        "lib.rs", "other.rs",
    ]


def test_inline_test_filter_uses_normalized_member_path(workspace):
    (workspace / "a/src/lib.rs").write_text(
        "pub fn value() {}\n#[cfg(test)]\nmod tests {\n fn works() {}\n}\n"
    )
    output = diagnostic("a/src/lib.rs", line=1) + "\n" + diagnostic("a/src/lib.rs", line=4)
    assert [entry["line"] for entry in parse_clippy_messages(output, workspace / "a")] == [1]


@pytest.mark.parametrize("timeout", [False, True])
def test_partial_diagnostics_survive_failed_or_timed_out_cargo(workspace, timeout):
    output = diagnostic("a/src/lib.rs") + "\n" + diagnostic("b/src/lib.rs")

    def runner(args, **kwargs):
        assert args[:2] == ["cargo", "clippy"]
        assert "--workspace" not in args
        assert "--no-deps" in args
        assert "-D" not in args
        assert args[args.index("--manifest-path") + 1] == str(workspace / "a/Cargo.toml")
        assert kwargs["cwd"] == str(workspace)
        assert kwargs["timeout"] == 120
        if timeout:
            raise subprocess.TimeoutExpired(args, 120, output=output.encode())
        return subprocess.CompletedProcess(args, 101, output, "build failed")

    result = run_cargo_result(
        CLIPPY_WARNING_CMD, workspace / "a", parse_clippy_messages, run_subprocess=runner,
    )
    assert result.status == "error"
    assert result.error_kind == ("tool_timeout" if timeout else "tool_failed")
    assert [entry["file"] for entry in result.entries] == ["src/lib.rs"]


def test_dependency_failure_is_not_empty_success(workspace):
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 101, diagnostic("b/src/lib.rs", level="error"), "",
        )

    result = run_cargo_result(
        CLIPPY_WARNING_CMD, workspace / "a", parse_clippy_messages, run_subprocess=runner,
    )
    assert result.status == "error"
    assert result.entries == []


def test_phase_and_direct_command_keep_partial_findings(workspace, monkeypatch, capsys):
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 101, diagnostic("a/src/lib.rs"), "")

    monkeypatch.setattr("desloppify.languages.rust.tools.subprocess.run", runner)
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    issues, potentials = tool_phase_clippy().run(workspace / "a", lang)
    assert len(issues) == 1
    assert potentials == {"clippy_warning": 1}
    assert lang.detector_coverage["clippy_warning"]["status"] == "reduced"
    cmd_clippy_warning(SimpleNamespace(path=str(workspace / "a"), json=True))
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"
    assert result["count"] == 1
    assert result["entries"][0]["file"] == "src/lib.rs"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_scoped_timeout_is_reported(workspace, monkeypatch, value):
    monkeypatch.setenv("DESLOPPIFY_RUST_TOOL_TIMEOUT", value)
    result = run_cargo_result(CLIPPY_WARNING_CMD, workspace / "a", parse_clippy_messages)
    assert result.error_kind == "tool_configuration"


def test_scoped_timeout_overrides_only_rust_runner(workspace, monkeypatch):
    monkeypatch.setenv("DESLOPPIFY_RUST_TOOL_TIMEOUT", "180")

    def runner(args, **kwargs):
        assert kwargs["timeout"] == 180
        return subprocess.CompletedProcess(args, 0, "", "")

    result = run_cargo_result(
        CLIPPY_WARNING_CMD, workspace / "a", parse_clippy_messages, run_subprocess=runner,
    )
    assert result.status == "empty"


def test_package_index_prunes_build_vendor_and_nested_repository_trees(workspace, monkeypatch):
    import os

    for name in ("target", "vendor", ".worktrees/other"):
        directory = workspace / name
        directory.mkdir(parents=True)
        (directory / "Cargo.toml").write_text('[package]\nname = "a"\n')
    (workspace / ".worktrees/other/.git").write_text("gitdir: unused\n")
    real_walk = os.walk
    visited = []

    def walk(*args, **kwargs):
        for item in real_walk(*args, **kwargs):
            visited.append(Path(item[0]).relative_to(workspace).as_posix())
            yield item

    monkeypatch.setattr("desloppify.languages.rust.support.os.walk", walk)
    packages = build_workspace_package_index(workspace)
    assert packages == {"a": workspace / "a", "b": workspace / "b"}
    assert "target" not in visited
    assert "vendor" not in visited
    assert ".worktrees/other" not in visited
