from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from desloppify.languages._framework.treesitter import C_SPEC, CPP_SPEC
from desloppify.languages.cxx.compile_commands import (
    CompileCommand,
    load_compile_commands,
)
from desloppify.languages.cxx.treesitter import _command_language, _compilation_specs


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (["cc", "native.c"], "c"),
        (["gcc", "native.c"], "c"),
        (["c++", "native.c"], "cpp"),
        (["g++", "native.c"], "cpp"),
        (["clang++-18", "native.c"], "cpp"),
        (["x86_64-linux-gnu-g++-14", "native.c"], "cpp"),
        (["ccache", "/usr/bin/clang++", "native.c"], "cpp"),
        (["clang", "-std=c++17", "native.c"], "c"),
        (["clang", "--driver-mode=g++", "native.c"], "cpp"),
        (["clang++", "--driver-mode=gcc", "native.c"], "c"),
        (["g++", "-std=c17", "native.c"], "cpp"),
        (["g++", "-x", "c", "native.c"], "c"),
        (["gcc", "-xc++", "native.c"], "cpp"),
        (["g++", "-xc", "native.c"], "c"),
        (["gcc", "-x", "c++-cpp-output", "native.c"], "cpp"),
        (["g++", "-x", "cpp-output", "native.c"], "c"),
        (["gcc", "-x", "c++", "-x", "none", "native.c"], "c"),
        (["g++", "-xc", "-xnone", "native.c"], "cpp"),
        (["gcc", "-xc++", "native.c", "-xc"], "cpp"),
        (["gcc", "-xc", "native.c", "-xc++"], "c"),
        (["gcc", "-include", "native.c", "-xc++", "native.c"], "cpp"),
        (["gcc", "-xc++", "--", "native.c"], "cpp"),
        (["clang-cl", "/TP", "native.c"], "cpp"),
        (["cl.exe", "/TC", "native.c"], "c"),
        (["cl", "native.c", "/TP"], "cpp"),
        (["cl", "/TP", "/TC", "native.c"], "c"),
        (["cl", "/TC", "/TP", "native.c"], "cpp"),
        (["cl", "/TP", "/Tcnative.c"], "c"),
        (["cl", "/TC", "/Tpnative.c"], "cpp"),
        (["cl", "/Tc", "native.c", "/TP"], "c"),
        (["cl", "/TC", "-Tp", "native.c"], "cpp"),
        (["cl", "/Tpother.c", "native.c"], "c"),
    ],
)
def test_compiler_language_options(tmp_path, arguments, expected):
    command = CompileCommand(str(tmp_path / "native.c"), tmp_path, arguments)
    assert _command_language(command) == expected


def test_cpp_extension_and_explicit_c_override(tmp_path):
    source = str(tmp_path / "native.cpp")
    assert (
        _command_language(CompileCommand(source, tmp_path, ["gcc", "native.cpp"]))
        == "cpp"
    )
    assert (
        _command_language(
            CompileCommand(source, tmp_path, ["gcc", "-xc", "native.cpp"])
        )
        == "c"
    )


@pytest.mark.parametrize("representation", ["arguments", "command"])
def test_relative_compilation_paths_use_database_root(
    tmp_path, monkeypatch, representation
):
    root = tmp_path / "project"
    root.mkdir()
    (root / "build").mkdir()
    other = tmp_path / "unrelated"
    other.mkdir()
    monkeypatch.chdir(other)
    invocation = (
        ["cc", "-xc++", "-c", "../src/file space.c"]
        if representation == "arguments"
        else "cc -xc++ -c '../src/file space.c'"
    )
    (root / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": "build",
                    "file": "../src/file space.c",
                    representation: invocation,
                }
            ]
        )
    )

    commands = load_compile_commands(root)
    specs, conflicts = _compilation_specs(root)

    source = str(root / "src" / "file space.c")
    assert len(commands) == 1
    assert commands[0].directory == root / "build"
    assert commands[0].source == source
    assert commands[0].arguments[-1] == "../src/file space.c"
    assert specs == {os.path.normcase(source): CPP_SPEC}
    assert conflicts == set()


@pytest.mark.parametrize("payload", [None, b"not json", b"{}", b"null", b"[", b"\xff"])
def test_missing_or_malformed_database(tmp_path, payload):
    if payload is not None:
        (tmp_path / "compile_commands.json").write_bytes(payload)
    assert load_compile_commands(tmp_path) == []
    assert _compilation_specs(tmp_path) == ({}, set())


def test_bad_entries_do_not_hide_valid_commands(tmp_path):
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                None,
                42,
                {},
                {"file": 10},
                {"file": ""},
                {"file": "bad.c", "command": "cc 'unterminated"},
                {"file": "bad.c", "arguments": ["cc", None]},
                {"file": "bad.c", "arguments": ["cc", "bad\u0000.c"]},
                {"file": "bad.c", "command": "cc bad\u0000.c"},
                {"file": "bad\u0000.c", "arguments": ["cc", "bad.c"]},
                {
                    "file": "bad.c",
                    "directory": "bad\u0000",
                    "arguments": ["cc", "bad.c"],
                },
                {"file": "good.c", "arguments": ["cc", "-xc++", "good.c"]},
            ]
        )
    )
    commands = load_compile_commands(tmp_path)
    assert [Path(command.source).name for command in commands] == ["good.c"]
    assert _compilation_specs(tmp_path) == (
        {os.path.normcase(str(tmp_path / "good.c")): CPP_SPEC},
        set(),
    )


def test_headers_keep_cpp_even_with_explicit_c_metadata(tmp_path):
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {"file": "shared.h", "arguments": ["cc", "-xc", "shared.h"]},
                {"file": "native.c", "arguments": ["cc", "-xc", "native.c"]},
            ]
        )
    )
    specs, conflicts = _compilation_specs(tmp_path)
    assert specs == {os.path.normcase(str(tmp_path / "native.c")): C_SPEC}
    assert conflicts == set()
