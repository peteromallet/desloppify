"""Ktlint JSON, fixer selection and bounded formatting regressions."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import subprocess

import pytest

from desloppify.base.exception_sets import CommandError
from desloppify.base.runtime_state import runtime_scope
from desloppify.languages import get_lang
from desloppify.languages._framework.generic_parts.parsers import (
    PARSERS,
    ToolParserError,
)


def _report(filename="Example.kt"):
    return json.dumps([{"file": filename, "errors": [
        {"line": 1, "column": 12, "message": "Unexpected whitespace", "rule": "standard:parameter-list-spacing"},
        {"line": 1, "column": 12, "message": "Unexpected spacing after (", "rule": "standard:paren-spacing"},
    ]}])


def test_nested_ktlint_errors_have_distinct_identities(tmp_path):
    assert "ktlint" in PARSERS
    entries = PARSERS["ktlint"](_report(), tmp_path)
    assert len(entries) == 2
    assert [entry["file"] for entry in entries] == ["Example.kt", "Example.kt"]
    assert [entry["line"] for entry in entries] == [1, 1]
    assert entries[0]["id"] != entries[1]["id"]
    assert entries[0]["detail"]["column"] == 12
    assert entries[0]["detail"]["rule"] == "standard:parameter-list-spacing"


@pytest.mark.parametrize("output", ["not JSON", "WARN message\n[]", "{}", '[{"file":"Example.kt","errors":{}}]'])
def test_malformed_ktlint_output_is_not_treated_as_clean(tmp_path, output):
    assert "ktlint" in PARSERS
    with pytest.raises(ToolParserError):
        PARSERS["ktlint"](output, tmp_path)


def test_empty_ktlint_output_is_clean(tmp_path):
    assert "ktlint" in PARSERS
    assert PARSERS["ktlint"]("[]", tmp_path) == []


def test_kotlin_only_selects_registered_fixer(monkeypatch):
    from desloppify.app.commands.autofix import fixer_selection
    from desloppify.engine._work_queue.helpers import primary_command_for_issue

    lang = get_lang("kotlin")
    monkeypatch.setattr(fixer_selection, "resolve_lang", lambda args: lang)
    _, fixer = fixer_selection.resolve_fixer_config(argparse.Namespace(), "ktlint-violation")
    assert fixer is lang.fixers["ktlint-violation"]
    assert primary_command_for_issue(
        {"id": "k1", "detector": "ktlint_violation"}, supported_fixers=set(lang.fixers),
    ) == "desloppify autofix ktlint-violation --dry-run"
    with pytest.raises(CommandError, match="Unknown fixer: unused-imports"):
        fixer_selection.resolve_fixer_config(argparse.Namespace(), "unused-imports")


@pytest.fixture
def kotlin_project(tmp_path):
    with runtime_scope() as runtime:
        runtime.project_root = tmp_path
        runtime.exclusions = ("generated",)
        files = {}
        for name in ("Example.kt", "Other.kt", "generated/Bindings.kt", "build/Generated.kt", "odd[1].kt"):
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fun sample( ){println("hello")}\n')
            files[name] = path
        yield tmp_path, files


def test_formatter_never_receives_excluded_or_unselected_files(kotlin_project, monkeypatch):
    from desloppify.languages.kotlin import fixers

    root, files = kotlin_project
    calls = []
    original = {name: path.read_bytes() for name, path in files.items()}
    original_mode = stat.S_IMODE(files["Example.kt"].stat().st_mode)
    formatted = 'fun sample() {\n    println("hello")\n}\n'

    def run(argv, **kwargs):
        calls.append(argv)
        assert "--stdin" in argv
        assert "--log-level=none" in argv
        assert argv[argv.index("--stdin-path") + 1] == str(files["Example.kt"])
        return subprocess.CompletedProcess(argv, 0, formatted if "--format" in argv else "", "[]")

    monkeypatch.setattr(fixers.subprocess, "run", run)
    entries = [{"file": str(files[name]), "line": 1} for name in (
        "Example.kt", "generated/Bindings.kt", "build/Generated.kt",
    )]
    result = get_lang("kotlin").fixers["ktlint-violation"].fix(entries)
    assert len(calls) == 2
    assert len(result.entries) == 1
    assert result.skip_reasons == {"excluded_file": 2}
    assert files["Example.kt"].read_text() == formatted
    assert stat.S_IMODE(files["Example.kt"].stat().st_mode) == original_mode
    for name in ("Other.kt", "generated/Bindings.kt", "build/Generated.kt", "odd[1].kt"):
        assert files[name].read_bytes() == original[name]


@pytest.mark.parametrize("failure", ["empty", "bad-json", "timeout", "missing-tool"])
def test_formatter_failures_preserve_source(kotlin_project, monkeypatch, failure):
    from desloppify.languages.kotlin import fixers

    root, files = kotlin_project
    source = files["Example.kt"]
    original = source.read_bytes()

    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 120)
        if failure == "missing-tool":
            raise FileNotFoundError("ktlint")
        stdout = "" if failure == "empty" else "fun sample() = Unit\n"
        return subprocess.CompletedProcess(argv, 0, stdout, "not JSON")

    monkeypatch.setattr(fixers.subprocess, "run", run)
    result = get_lang("kotlin").fixers["ktlint-violation"].fix(
        [{"file": str(source), "line": 1}],
    )
    assert result.entries == []
    assert result.skip_reasons == {"tool_failed": 1}
    assert source.read_bytes() == original


def test_concurrent_source_change_is_preserved(kotlin_project, monkeypatch):
    from desloppify.languages.kotlin import fixers

    root, files = kotlin_project
    source = files["Example.kt"]
    edited = "fun changed() = Unit\n"

    def run(argv, **kwargs):
        source.write_text(edited)
        return subprocess.CompletedProcess(argv, 0, "fun sample() = Unit\n" if "--format" in argv else "", "[]")

    monkeypatch.setattr(fixers.subprocess, "run", run)
    result = get_lang("kotlin").fixers["ktlint-violation"].fix(
        [{"file": str(source), "line": 1}],
    )
    assert result.entries == []
    assert result.skip_reasons == {"file_changed": 1}
    assert source.read_text() == edited


requires_ktlint = pytest.mark.skipif(shutil.which("ktlint") is None, reason="ktlint is not installed")


@requires_ktlint
def test_actual_ktlint_output_is_detected_and_exclusions_apply(kotlin_project):
    root, files = kotlin_project
    fixer = get_lang("kotlin").fixers["ktlint-violation"]
    entries = fixer.detect(root)
    assert entries
    assert {entry["file"] for entry in entries} == {
        str(files[name]) for name in ("Example.kt", "Other.kt", "odd[1].kt")
    }


@requires_ktlint
def test_format_only_selected_eligible_files_without_path_argument(kotlin_project):
    root, files = kotlin_project
    fixer = get_lang("kotlin").fixers["ktlint-violation"]
    original = {name: path.read_bytes() for name, path in files.items()}
    entries = [{"file": str(files[name]), "line": 1} for name in (
        "Example.kt", "odd[1].kt", "generated/Bindings.kt", "build/Generated.kt",
    )]
    result = fixer.fix(entries)
    assert {entry["file"] for entry in result.entries} == {str(files["Example.kt"]), str(files["odd[1].kt"])}
    for name in ("Example.kt", "odd[1].kt"):
        assert files[name].read_text() == 'fun sample() {\n    println("hello")\n}\n'
    for name in ("Other.kt", "generated/Bindings.kt", "build/Generated.kt"):
        assert files[name].read_bytes() == original[name]


@requires_ktlint
def test_dry_run_does_not_write(kotlin_project):
    root, files = kotlin_project
    source = files["Example.kt"]
    original = source.read_bytes()
    result = get_lang("kotlin").fixers["ktlint-violation"].fix(
        [{"file": str(source), "line": 1}], dry_run=True,
    )
    assert result.entries
    assert source.read_bytes() == original


@requires_ktlint
def test_invalid_kotlin_is_never_truncated(kotlin_project):
    root, files = kotlin_project
    source = files["Example.kt"]
    source.write_text("fun broken( {\n")
    original = source.read_bytes()
    result = get_lang("kotlin").fixers["ktlint-violation"].fix(
        [{"file": str(source), "line": 1}],
    )
    assert result.entries == []
    assert result.skip_reasons
    assert source.read_bytes() == original


@requires_ktlint
def test_uncorrectable_violations_are_not_auto_resolved(kotlin_project):
    root, files = kotlin_project
    source = files["Example.kt"]
    source.write_text('fun BAD_NAME() { println("hello") }\n')
    fixer = get_lang("kotlin").fixers["ktlint-violation"]
    entries = [entry for entry in fixer.detect(root) if entry["file"] == str(source)]
    assert entries
    result = fixer.fix(entries)
    assert len(result.entries) == 1
    assert "removed" not in result.entries[0]
    assert "remaining violations" in result.entries[0]["summary"]
    assert source.read_text() == 'fun BAD_NAME() {\n    println("hello")\n}\n'
