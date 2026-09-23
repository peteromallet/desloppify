"""Generic external tools must honor the scan's configured exclusions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.languages._framework.generic_parts.parsers import (
    parse_json,
    parse_next_lint,
)
from desloppify.languages._framework.generic_parts.tool_factories import (
    make_detect_fn,
    make_tool_phase,
)
from desloppify.languages._framework.generic_parts.tool_runner import run_tool_result


@pytest.mark.parametrize("consumer", ["phase", "detect"])
@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("exclusion", ["ios/.build", "ios/.build/**"])
def test_nested_scan_filters_tool_findings_using_project_exclusions(
    tmp_path: Path, consumer: str, absolute: bool, exclusion: str
):
    scan_path = tmp_path / "ios"
    entries = [
        {"file": ".build/debug/runner.swift", "line": 1, "reason": "generated"},
        {"file": "Atlas/App.swift", "line": 2, "reason": "source"},
        {"file": ".build-tools/Keep.swift", "line": 3, "reason": "similar name"},
    ]
    for entry in entries:
        file = scan_path / entry["file"]
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    if absolute:
        entries = [
            {**entry, "file": str(scan_path / entry["file"])} for entry in entries
        ]
    output = subprocess.CompletedProcess(
        args="swiftlint", returncode=2, stdout=json.dumps(entries), stderr=""
    )
    runtime = RuntimeContext(project_root=tmp_path, exclusions=(exclusion,))

    with runtime_scope(runtime), patch("subprocess.run", return_value=output):
        if consumer == "phase":
            phase = make_tool_phase(
                "swiftlint",
                "swiftlint lint --reporter json",
                "json",
                "swiftlint_violation",
                2,
            )
            findings, potentials = phase.run(scan_path, None)
            assert [finding["summary"] for finding in findings] == [
                "source",
                "similar name",
            ]
            assert potentials == {"swiftlint_violation": 2}
        else:
            detect = make_detect_fn("swiftlint lint --reporter json", parse_json)
            findings = detect(scan_path)
            assert [finding["message"] for finding in findings] == [
                "source",
                "similar name",
            ]


def test_only_excluded_diagnostics_do_not_report_tool_failure(tmp_path: Path):
    generated = tmp_path / "ios/.build/runner.swift"
    generated.parent.mkdir(parents=True)
    generated.touch()
    output = subprocess.CompletedProcess(
        args="swiftlint",
        returncode=2,
        stdout=json.dumps(
            [{"file": ".build/runner.swift", "line": 1, "reason": "generated"}]
        ),
        stderr="",
    )
    runtime = RuntimeContext(project_root=tmp_path, exclusions=("ios/.build",))

    with runtime_scope(runtime):
        result = run_tool_result(
            "swiftlint lint --reporter json",
            tmp_path / "ios",
            parse_json,
            run_subprocess=lambda *_args, **_kwargs: output,
        )

    assert result.entries == []
    assert result.status == "empty"
    assert result.error_kind is None
    assert result.returncode == 2


def test_already_project_relative_parser_paths_are_not_rebased_twice(tmp_path: Path):
    generated = tmp_path / "apps/web/generated/component.tsx"
    generated.parent.mkdir(parents=True)
    generated.touch()
    output = subprocess.CompletedProcess(
        args="next",
        returncode=1,
        stdout=json.dumps(
            [
                {
                    "filePath": str(generated),
                    "messages": [{"line": 1, "message": "generated"}],
                },
                {"filePath": str(tmp_path / "apps/web/clean.tsx"), "messages": []},
            ]
        ),
        stderr="",
    )
    runtime = RuntimeContext(project_root=tmp_path, exclusions=("apps/web/generated",))

    with runtime_scope(runtime):
        result = run_tool_result(
            "next lint --format json",
            tmp_path / "apps/web",
            parse_next_lint,
            run_subprocess=lambda *_args, **_kwargs: output,
        )

    assert result.entries == []
    assert result.status == "empty"
    assert result.meta == {"potential": 2}, (
        "Aggregate metadata cannot be recomputed from retained diagnostics."
    )
