"""Tests for Rust cargo diagnostic parsing helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from desloppify.languages.rust.tools import (
    build_rustdoc_warning_cmd,
    parse_cargo_errors,
    parse_clippy_messages,
    parse_rustdoc_messages,
    run_rustdoc_result,
)


def test_parse_clippy_messages_ignores_non_json_noise():
    message = {
        "reason": "compiler-message",
        "message": {
            "level": "warning",
            "message": "unused variable: `name`",
            "spans": [
                {
                    "is_primary": True,
                    "file_name": "src/lib.rs",
                    "line_start": 7,
                }
            ],
        },
    }
    output = "\n".join(
        [
            "Compiling demo v0.1.0",
            "[]",
            json.dumps(message),
        ]
    )

    entries = parse_clippy_messages(output, Path("."))

    assert entries == [
        {
            "file": "src/lib.rs",
            "line": 7,
            "message": "unused variable: `name`",
        }
    ]


def test_parse_cargo_errors_prefers_primary_span_and_includes_error_code():
    message = {
        "reason": "compiler-message",
        "message": {
            "level": "error",
            "message": "cannot find value `answer` in this scope",
            "code": {"code": "E0425"},
            "spans": [
                {
                    "is_primary": False,
                    "file_name": "src/other.rs",
                    "line_start": 3,
                },
                {
                    "is_primary": True,
                    "file_name": "src/lib.rs",
                    "line_start": 11,
                },
            ],
        },
    }

    entries = parse_cargo_errors(json.dumps(message), Path("."))

    assert entries == [
        {
            "file": "src/lib.rs",
            "line": 11,
            "message": "[E0425] cannot find value `answer` in this scope",
        }
    ]


def test_parse_rustdoc_messages_includes_lint_code():
    message = {
        "reason": "compiler-message",
        "message": {
            "level": "warning",
            "message": "no documentation found for this crate's top-level module",
            "code": {"code": "rustdoc::missing_crate_level_docs"},
            "spans": [
                {
                    "is_primary": True,
                    "file_name": "crates/lib/src/lib.rs",
                    "line_start": 1,
                }
            ],
        },
    }

    entries = parse_rustdoc_messages(json.dumps(message), Path("."))

    assert entries == [
        {
            "file": "crates/lib/src/lib.rs",
            "line": 1,
            "message": (
                "[rustdoc::missing_crate_level_docs] "
                "no documentation found for this crate's top-level module"
            ),
        }
    ]


def test_build_rustdoc_warning_cmd_targets_one_package():
    command = build_rustdoc_warning_cmd("demo-crate")

    assert "cargo rustdoc" in command
    assert "--package demo-crate" in command
    assert "--workspace" not in command
    assert "--lib" in command


def test_run_rustdoc_result_scans_each_workspace_library_package(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    commands: list[str] = []

    metadata = {
        "workspace_members": ["pkg-a 0.1.0 (path+file:///workspace/pkg-a)", "pkg-b 0.1.0 (path+file:///workspace/pkg-b)", "pkg-c 0.1.0 (path+file:///workspace/pkg-c)"],
        "packages": [
            {
                "id": "pkg-a 0.1.0 (path+file:///workspace/pkg-a)",
                "name": "pkg-a",
                "targets": [{"kind": ["lib"], "crate_types": ["lib"]}],
            },
            {
                "id": "pkg-b 0.1.0 (path+file:///workspace/pkg-b)",
                "name": "pkg-b",
                "targets": [{"kind": ["bin"], "crate_types": ["bin"]}],
            },
            {
                "id": "pkg-c 0.1.0 (path+file:///workspace/pkg-c)",
                "name": "pkg-c",
                "targets": [{"kind": ["proc-macro"], "crate_types": ["proc-macro"]}],
            },
        ],
    }
    rustdoc_message = lambda file_name, line_no: json.dumps(
        {
            "reason": "compiler-message",
            "message": {
                "level": "warning",
                "message": "missing docs",
                "spans": [
                    {
                        "is_primary": True,
                        "file_name": file_name,
                        "line_start": line_no,
                    }
                ],
            },
        }
    )

    def runner(args, **kwargs):
        command = args[2] if args[:2] == ["/bin/sh", "-lc"] else " ".join(args)
        commands.append(command)
        if command == "cargo metadata --format-version=1 --no-deps":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(metadata), stderr="")
        if "--package pkg-a" in command:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout=rustdoc_message("pkg-a/src/lib.rs", 3),
                stderr="",
            )
        if "--package pkg-c" in command:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout=rustdoc_message("pkg-c/src/lib.rs", 8),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    result = run_rustdoc_result(workspace, run_subprocess=runner)

    assert result.status == "ok"
    assert result.entries == [
        {"file": "pkg-a/src/lib.rs", "line": 3, "message": "missing docs"},
        {"file": "pkg-c/src/lib.rs", "line": 8, "message": "missing docs"},
    ]
    assert commands[0] == "cargo metadata --format-version=1 --no-deps"
    assert any("--package pkg-a" in command for command in commands)
    assert not any("--package pkg-b" in command for command in commands)
    assert any("--package pkg-c" in command for command in commands)


def test_run_rustdoc_result_returns_error_for_unparsed_package_failure(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    metadata = {
        "workspace_members": ["pkg-a 0.1.0 (path+file:///workspace/pkg-a)"],
        "packages": [
            {
                "id": "pkg-a 0.1.0 (path+file:///workspace/pkg-a)",
                "name": "pkg-a",
                "targets": [{"kind": ["lib"], "crate_types": ["lib"]}],
            }
        ],
    }

    def runner(args, **kwargs):
        command = args[2] if args[:2] == ["/bin/sh", "-lc"] else " ".join(args)
        if command == "cargo metadata --format-version=1 --no-deps":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(metadata), stderr="")
        if "--package pkg-a" in command:
            return subprocess.CompletedProcess(args=args, returncode=2, stdout="not json", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    result = run_rustdoc_result(workspace, run_subprocess=runner)

    assert result.status == "error"
    assert result.error_kind == "tool_failed_unparsed_output"
    assert result.message is not None
    assert result.message.startswith("pkg-a:")
