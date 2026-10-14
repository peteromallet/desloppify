from __future__ import annotations

from types import SimpleNamespace

from desloppify.languages._framework.generic_parts.tool_runner import ToolRunResult
from desloppify.languages.cxx import phases as cxx_phases


def test_phase_cppcheck_retries_per_file_after_batch_timeout(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        cxx_phases,
        "find_cxx_files",
        lambda _path: ["src/unsafe_a.cpp", "src/unsafe_b.cpp"],
        raising=False,
    )

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
        assert path == tmp_path
        assert cmd.startswith("cppcheck ")
        calls.append(cmd)
        if "unsafe_a.cpp" in cmd and "unsafe_b.cpp" in cmd:
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_timeout",
                message="timeout",
                returncode=1,
            )
        if "unsafe_a.cpp" in cmd:
            return ToolRunResult(
                entries=[
                    {
                        "file": "src/unsafe_a.cpp",
                        "line": 8,
                        "message": "Using 'system' can be unsafe",
                    }
                ],
                status="ok",
                returncode=1,
            )
        if "unsafe_b.cpp" in cmd:
            return ToolRunResult(entries=[], status="empty", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        cxx_phases,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    issues, signals = cxx_phases.phase_cppcheck_issue(tmp_path, lang)

    assert len(calls) == 3
    assert len(issues) == 1
    assert issues[0]["detector"] == "cppcheck_issue"
    assert issues[0]["summary"] == "Using 'system' can be unsafe"
    assert signals == {"cppcheck_issue": 1}
    assert lang.detector_coverage == {}
    assert lang.coverage_warnings == []


def test_phase_cppcheck_records_reduced_coverage_when_single_file_retry_still_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cxx_phases,
        "find_cxx_files",
        lambda _path: ["src/unsafe_a.cpp", "src/unsafe_b.cpp"],
        raising=False,
    )

    def _fake_run_tool_result(cmd, _path, _parser, **_kwargs):
        if "unsafe_a.cpp" in cmd and "unsafe_b.cpp" in cmd:
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_timeout",
                message="timeout",
                returncode=1,
            )
        if "unsafe_a.cpp" in cmd:
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_timeout",
                message="timeout",
                returncode=1,
            )
        if "unsafe_b.cpp" in cmd:
            return ToolRunResult(entries=[], status="empty", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        cxx_phases,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    issues, signals = cxx_phases.phase_cppcheck_issue(tmp_path, lang)

    assert issues == []
    assert signals == {}
    assert lang.detector_coverage["cppcheck_issue"]["status"] == "reduced"
    assert lang.detector_coverage["cppcheck_issue"]["reason"] == "tool_timeout"
    assert lang.coverage_warnings[0]["detector"] == "cppcheck_issue"

def test_phase_cppcheck_uses_unique_issue_ids_for_same_line(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cxx_phases,
        "find_cxx_files",
        lambda _path: ["src/unsafe.cpp"],
        raising=False,
    )

    def _fake_run_tool_result(_cmd, _path, _parser, **_kwargs):
        return ToolRunResult(
            entries=[
                {
                    "file": "src/unsafe.cpp",
                    "line": 8,
                    "message": "Using 'system' can be unsafe",
                },
                {
                    "file": "src/unsafe.cpp",
                    "line": 8,
                    "message": "Buffer overflow risk",
                },
            ],
            status="ok",
            returncode=1,
        )

    monkeypatch.setattr(
        cxx_phases,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    issues, signals = cxx_phases.phase_cppcheck_issue(tmp_path, lang)

    assert len(issues) == 2
    assert issues[0]["id"] != issues[1]["id"]
    assert signals == {"cppcheck_issue": 2}


def test_cppcheck_assigns_cpp_to_headers_without_reclassifying_c_sources(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cxx_phases, "find_cxx_files", lambda _path: ["src/api.h", "src/app.cpp", "src/legacy.c"])
    def run(cmd, _path, _parser):
        calls.append(cmd)
        return ToolRunResult(entries=[], status="empty", returncode=0)
    monkeypatch.setattr(cxx_phases, "run_tool_result", run)
    cxx_phases.phase_cppcheck_issue(tmp_path, SimpleNamespace(detector_coverage={}, coverage_warnings=[]))
    assert len(calls) == 2
    assert "--language=c " in calls[0] and "legacy.c" in calls[0] and "api.h" not in calls[0]
    assert "--language=c++ " in calls[1] and "api.h" in calls[1] and "app.cpp" in calls[1] and "legacy.c" not in calls[1]


def test_cppcheck_analysis_notices_reduce_coverage_without_creating_code_defects(tmp_path, monkeypatch):
    monkeypatch.setattr(cxx_phases, "find_cxx_files", lambda _path: ["src/app.cpp"])
    messages = [
        'information: missingInclude: Include file: "sdk.h" not found.',
        'information: checkersReport: Active checkers: 100/200',
        'error: unknownMacro: Configuration is required for SOME_API.',
        'error: syntaxError: Cannot parse this configuration.',
        'error: preprocessorErrorDirective: #error unsupported platform',
        'error: bufferAccessOutOfBounds: Array index 3 is out of bounds.',
        'warning: uninitvar: Uninitialized variable: value',
    ]
    monkeypatch.setattr(cxx_phases, "run_tool_result", lambda *_args: ToolRunResult(
        entries=[{"file": "src/app.cpp", "line": index + 1, "message": message} for index, message in enumerate(messages)],
        status="ok", returncode=0))
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    issues, signals = cxx_phases.phase_cppcheck_issue(tmp_path, lang)
    assert len(issues) == 2
    assert "bufferAccessOutOfBounds" in issues[0]["summary"]
    assert "uninitvar" in issues[1]["summary"]
    assert signals == {"cppcheck_issue": 2}
    assert lang.detector_coverage["cppcheck_issue"]["reason"] == "tool_configuration"
    assert len(lang.coverage_warnings) == 1
