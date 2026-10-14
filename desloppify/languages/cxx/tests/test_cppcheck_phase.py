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


def test_unused_functions_are_reconciled_across_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(cxx_phases, "find_cxx_files", lambda _: ["src/producer.cpp", "src/consumer.cpp"])
    monkeypatch.setattr(cxx_phases, "_CPPCHECK_BATCH_SIZE", 1)
    stale = {"file": "src/producer.cpp", "line": 1,
             "message": "style: unusedFunction: The function 'shared_value' is never used."}
    dead = {"file": "src/producer.cpp", "line": 2,
            "message": "style: unusedFunction: The function 'dead_value' is never used."}
    other = {"file": "src/consumer.cpp", "line": 4,
             "message": "warning: uninitvar: Uninitialized variable: value"}
    monkeypatch.setattr(cxx_phases, "_run_cppcheck_batch", lambda _, files: ToolRunResult(
        entries=[stale] if "producer.cpp" in files[0] else [other], status="ok"))
    calls = []
    def whole(root, files):
        calls.append((root, files))
        return ToolRunResult(entries=[dead], status="ok")
    monkeypatch.setattr(cxx_phases, "_run_cppcheck_whole_program", whole)
    issues, _ = cxx_phases.phase_cppcheck_issue(tmp_path, SimpleNamespace(detector_coverage={}, coverage_warnings=[]))
    assert calls == [(tmp_path, ["src/producer.cpp", "src/consumer.cpp"])]
    assert {issue["summary"] for issue in issues} == {dead["message"], other["message"]}


def test_failed_whole_program_pass_does_not_restore_batch_unused_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(cxx_phases, "find_cxx_files", lambda _: ["src/producer.cpp"])
    stale = {"file": "src/producer.cpp", "line": 1,
             "message": "style: unusedFunction: The function 'shared_value' is never used."}
    monkeypatch.setattr(cxx_phases, "_run_cppcheck_batch", lambda *_: ToolRunResult(entries=[stale], status="ok"))
    monkeypatch.setattr(cxx_phases, "_run_cppcheck_whole_program", lambda *_: ToolRunResult(
        entries=[stale], status="error", error_kind="tool_timeout", message="timeout"))
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    assert cxx_phases.phase_cppcheck_issue(tmp_path, lang) == ([], {})
    assert lang.detector_coverage["cppcheck_issue"]["reason"] == "tool_timeout"


def test_incomplete_whole_program_pass_records_configuration_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(cxx_phases, "find_cxx_files", lambda _: ["src/producer.cpp"])
    stale = {"file": "src/producer.cpp", "line": 1,
             "message": "style: unusedFunction: The function 'shared_value' is never used."}
    notice = {"file": "src/consumer.cpp", "line": 1,
              "message": "error: unknownMacro: Configuration is required."}
    monkeypatch.setattr(cxx_phases, "_run_cppcheck_batch", lambda *_: ToolRunResult(entries=[stale], status="ok"))
    monkeypatch.setattr(cxx_phases, "_run_cppcheck_whole_program", lambda *_: ToolRunResult(entries=[stale, notice], status="ok"))
    lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
    assert cxx_phases.phase_cppcheck_issue(tmp_path, lang) == ([], {})
    assert lang.detector_coverage["cppcheck_issue"]["reason"] == "tool_configuration"


def test_whole_program_database_preserves_paths_and_dialects(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    files = ["dir with spaces/legacy.c", "src/app.cpp", "src/api.h"]
    database_path = []
    def run(command, root, parser):
        import shlex
        argument = next(arg for arg in shlex.split(command) if arg.startswith("--project="))
        database = Path(argument.removeprefix("--project="))
        database_path.append(database)
        rows = json.loads(database.read_text())
        assert [row["file"] for row in rows] == [str((tmp_path / file).resolve()) for file in files]
        assert [row["arguments"][2] for row in rows] == ["c", "c++", "c++"]
        assert all(row["directory"] == str(tmp_path.resolve()) for row in rows)
        return ToolRunResult(entries=[], status="empty")
    monkeypatch.setattr(cxx_phases, "run_tool_result", run)
    cxx_phases._run_cppcheck_whole_program(tmp_path, files)
    assert not database_path[0].exists()


def test_whole_program_database_io_error_is_reduced_coverage(tmp_path, monkeypatch):
    def unavailable(**_kwargs):
        raise OSError("temporary storage unavailable")
    monkeypatch.setattr(cxx_phases.tempfile, "TemporaryDirectory", unavailable)
    result = cxx_phases._run_cppcheck_whole_program(tmp_path, ["src/app.cpp"])
    assert result.status == "error"
    assert result.error_kind == "tool_io_error"
    assert "temporary storage unavailable" in result.message
