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


def test_information_records_are_classified_non_actionable():
    assert cxx_phases._is_information_record(
        {"file": "src/a.cpp", "line": 1,
         "message": "information: Include file: \"hashmap.hpp\" not found."}
    )
    assert cxx_phases._is_information_record(
        {"file": "src/a.cpp", "line": 1,
         "message": "information: Active checkers: 173/186"}
    )
    assert not cxx_phases._is_information_record(
        {"file": "src/a.cpp", "line": 1, "message": "error: uninitialized variable"}
    )


def test_compile_db_include_dirs_harvests_matching_entries(tmp_path):
    import json

    db = tmp_path / "compile_commands.json"
    db.write_text(json.dumps([
        {"file": "/repo/src/a.cpp",
         "command": "c++ -I/repo/include -I /opt/vendor/utils -c src/a.cpp"},
        {"file": "/repo/src/b.cpp",
         "arguments": ["c++", "-I/repo/other", "-c", "src/b.cpp"]},
    ]))
    dirs = cxx_phases._compile_db_include_dirs(
        tmp_path, ["src/a.cpp", "src/b.cpp", "include/h.hpp"])
    assert dirs == ["/opt/vendor/utils", "/repo/include", "/repo/other"]


def test_compile_db_include_dirs_missing_or_broken_db(tmp_path):
    assert cxx_phases._compile_db_include_dirs(tmp_path, ["src/a.cpp"]) == []
    (tmp_path / "compile_commands.json").write_text("{not json")
    assert cxx_phases._compile_db_include_dirs(tmp_path, ["src/a.cpp"]) == []
