"""Tests for Next.js `next lint` parser + tool-phase integration."""

from __future__ import annotations

import json
import subprocess  # nosec B404
from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.languages._framework.generic_parts.parsers import (
    ToolParserError,
    parse_next_lint,
)
from desloppify.languages._framework.generic_support.core import make_tool_phase
from desloppify.languages._framework.generic_parts import tool_runner as tool_runner_mod


def test_parse_next_lint_aggregates_per_file_and_relativizes_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scan_path = tmp_path / "apps" / "web"
    scan_path.mkdir(parents=True, exist_ok=True)

    payload = [
        {
            "filePath": str(tmp_path / "app" / "page.tsx"),
            "messages": [
                {
                    "line": 10,
                    "column": 2,
                    "ruleId": "rule-a",
                    "message": "Bad thing",
                    "severity": 2,
                },
                {
                    "line": 11,
                    "column": 1,
                    "ruleId": "rule-b",
                    "message": "Another thing",
                    "severity": 1,
                },
            ],
        },
        {
            "filePath": "relative.js",
            "messages": [{"line": 0, "message": "Line defaults to 1", "severity": 1}],
        },
        {"filePath": "empty.js", "messages": []},
    ]

    raw = "eslint noise\n" + json.dumps(payload) + "\nmore noise"
    entries, meta = parse_next_lint(raw, scan_path)
    assert meta == {"potential": 3}
    assert len(entries) == 2

    first = next(e for e in entries if e["file"] == "app/page.tsx")
    assert first["line"] == 10
    assert first["id"] == "lint"
    assert first["message"].startswith("next lint: Bad thing")
    assert first["detail"]["count"] == 2
    assert len(first["detail"]["messages"]) == 2

    second = next(e for e in entries if e["file"] == "apps/web/relative.js")
    assert second["line"] == 1
    assert second["id"] == "lint"
    assert second["message"].startswith("next lint: Line defaults to 1")
    assert second["detail"]["count"] == 1

def test_parse_next_lint_raises_on_missing_json_array(tmp_path):
    with pytest.raises(ToolParserError):
        parse_next_lint("not json output", tmp_path)


def test_next_lint_tool_phase_emits_issues_and_potential(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scan_path = tmp_path / "apps" / "web"
    scan_path.mkdir(parents=True, exist_ok=True)

    payload = [
        {"filePath": "a.js", "messages": [{"line": 3, "message": "x", "severity": 1}]},
        {"filePath": "b.js", "messages": []},
    ]
    output = json.dumps(payload)

    def fake_run(argv, *, shell, cwd, capture_output, text, timeout):
        assert shell is False
        assert capture_output is True
        assert text is True
        assert timeout == 120
        assert Path(cwd).resolve() == scan_path.resolve()
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(tool_runner_mod.subprocess, "run", fake_run)

    phase = make_tool_phase(
        "next lint",
        "npx --no-install next lint --format json",
        "next_lint",
        "next_lint",
        2,
    )
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])

    issues, signals = phase.run(scan_path, lang)
    assert signals == {"next_lint": 2}
    assert len(issues) == 1
    assert issues[0]["detector"] == "next_lint"
    assert issues[0]["file"] == "apps/web/a.js"
    assert issues[0]["tier"] == 2
    assert issues[0]["detail"]["count"] == 1


def test_next_lint_tool_phase_reports_potential_when_clean(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scan_path = tmp_path / "apps" / "web"
    scan_path.mkdir(parents=True, exist_ok=True)

    payload = [{"filePath": "a.js", "messages": []}]
    output = json.dumps(payload)

    def fake_run(argv, *, shell, cwd, capture_output, text, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(tool_runner_mod.subprocess, "run", fake_run)

    phase = make_tool_phase(
        "next lint",
        "npx --no-install next lint --format json",
        "next_lint",
        "next_lint",
        2,
    )
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])

    issues, signals = phase.run(scan_path, lang)
    assert issues == []
    assert signals == {"next_lint": 1}


def test_next_lint_tool_phase_records_coverage_warning_on_tool_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("missing tool")

    monkeypatch.setattr(tool_runner_mod.subprocess, "run", fake_run)

    phase = make_tool_phase(
        "next lint",
        "npx --no-install next lint --format json",
        "next_lint",
        "next_lint",
        2,
    )
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])

    issues, signals = phase.run(tmp_path, lang)
    assert issues == []
    assert signals == {}
    assert lang.detector_coverage["next_lint"]["reason"] == "tool_not_found"
    assert lang.coverage_warnings and lang.coverage_warnings[0]["detector"] == "next_lint"


def test_next_lint_tool_phase_records_coverage_warning_on_parser_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_run(argv, *, shell, cwd, capture_output, text, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout="not json", stderr="")

    monkeypatch.setattr(tool_runner_mod.subprocess, "run", fake_run)

    phase = make_tool_phase(
        "next lint",
        "npx --no-install next lint --format json",
        "next_lint",
        "next_lint",
        2,
    )
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])

    issues, signals = phase.run(tmp_path, lang)
    assert issues == []
    assert signals == {}
    assert lang.detector_coverage["next_lint"]["reason"] == "parser_error"
    assert lang.coverage_warnings and lang.coverage_warnings[0]["detector"] == "next_lint"
