from __future__ import annotations

from types import SimpleNamespace

from desloppify.languages._framework.base.types import LangSecurityResult
from desloppify.languages._framework.generic_parts.tool_runner import ToolRunResult
from desloppify.languages.cxx import CxxConfig
from desloppify.languages.cxx.detectors import security as security_mod
from desloppify.languages.cxx.detectors.security import detect_cxx_security


def test_detect_cxx_security_falls_back_to_regex_with_reduced_coverage_when_tools_missing(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "src" / "unsafe.cpp"
    source.parent.mkdir(parents=True)
    source.write_text(
        '#include <cstring>\n'
        '#include <cstdlib>\n'
        "void copy(char *dst, const char *src) {\n"
        "    std::strcpy(dst, src);\n"
        "    system(src);\n"
        "}\n"
    )

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=lambda _cmd: None),
        raising=False,
    )

    result = detect_cxx_security([str(source.resolve())], zone_map=None)

    assert isinstance(result, LangSecurityResult)
    assert result.files_scanned == 1
    assert result.coverage is not None
    assert result.coverage.detector == "security"
    assert result.coverage.status == "reduced"
    assert result.coverage.reason == "missing_dependency"
    kinds = {entry["detail"]["kind"] for entry in result.entries}
    assert "unsafe_c_string" in kinds
    assert "command_injection" in kinds
    assert {entry["detail"].get("source") for entry in result.entries} == {"regex"}


def test_detect_cxx_security_normalizes_clang_tidy_findings_when_compile_commands_present(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "src" / "unsafe.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "compile_commands.json").write_text("[]\n")

    def _fake_which(cmd: str) -> str | None:
        return "C:/tools/clang-tidy.exe" if cmd == "clang-tidy" else None

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
        assert str(path.resolve()) == str(tmp_path.resolve())
        assert cmd.startswith("clang-tidy ")
        output = (
            f"{source}:4:5: warning: call to 'strcpy' is insecure because it can overflow "
            "[clang-analyzer-security.insecureAPI.strcpy]\n"
        )
        return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=_fake_which),
        raising=False,
    )
    monkeypatch.setattr(
        security_mod,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    result = detect_cxx_security([str(source.resolve())], zone_map=None)

    assert result.coverage is None
    assert result.files_scanned == 1
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry["detail"]["kind"] == "unsafe_c_string"
    assert entry["detail"]["source"] == "clang-tidy"
    assert entry["detail"]["check_id"] == "clang-analyzer-security.insecureAPI.strcpy"


def test_detect_cxx_security_uses_cppcheck_when_clang_tidy_missing_without_reduced_coverage(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "src" / "unsafe.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "compile_commands.json").write_text("[]\n")

    def _fake_which(cmd: str) -> str | None:
        if cmd == "clang-tidy":
            return None
        if cmd == "cppcheck":
            return "C:/tools/cppcheck.exe"
        return None

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
        assert str(path.resolve()) == str(tmp_path.resolve())
        assert cmd.startswith("cppcheck ")
        output = f"{source}:5:warning:dangerousFunctionSystem:Using 'system' can be unsafe\n"
        return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=_fake_which),
        raising=False,
    )
    monkeypatch.setattr(
        security_mod,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    result = detect_cxx_security([str(source.resolve())], zone_map=None)

    assert result.coverage is None
    assert result.files_scanned == 1
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry["detail"]["kind"] == "command_injection"
    assert entry["detail"]["source"] == "cppcheck"
    assert entry["detail"]["check_id"] == "dangerousFunctionSystem"


def test_detect_cxx_security_retries_cppcheck_per_file_after_batch_timeout(
    tmp_path,
    monkeypatch,
):
    source_a = tmp_path / "src" / "unsafe_a.cpp"
    source_b = tmp_path / "src" / "unsafe_b.cpp"
    source_a.parent.mkdir(parents=True)
    source_a.write_text("int a() { return 0; }\n")
    source_b.write_text("int b() { return 0; }\n")

    calls: list[str] = []

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=lambda cmd: "C:/tools/cppcheck.exe" if cmd == "cppcheck" else None),
        raising=False,
    )

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
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
            output = f"{source_a}:8:warning:dangerousFunctionSystem:Using 'system' can be unsafe\n"
            return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)
        if "unsafe_b.cpp" in cmd:
            return ToolRunResult(entries=[], status="empty", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        security_mod,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    result = detect_cxx_security(
        [str(source_a.resolve()), str(source_b.resolve())],
        zone_map=None,
    )

    assert len(calls) == 3
    assert result.coverage is None
    assert result.files_scanned == 2
    assert len(result.entries) == 1
    assert result.entries[0]["detail"]["source"] == "cppcheck"
    assert result.entries[0]["detail"]["check_id"] == "dangerousFunctionSystem"


def test_detect_cxx_security_retries_clang_tidy_per_file_after_batch_failure(
    tmp_path,
    monkeypatch,
):
    source_a = tmp_path / "src" / "unsafe_a.cpp"
    source_b = tmp_path / "src" / "unsafe_b.cpp"
    source_a.parent.mkdir(parents=True)
    source_a.write_text("int a() { return 0; }\n")
    source_b.write_text("int b() { return 0; }\n")
    (tmp_path / "compile_commands.json").write_text("[]\n")

    calls: list[str] = []

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=lambda cmd: "C:/tools/clang-tidy.exe" if cmd == "clang-tidy" else None),
        raising=False,
    )

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
        assert cmd.startswith("clang-tidy ")
        calls.append(cmd)
        if "unsafe_a.cpp" in cmd and "unsafe_b.cpp" in cmd:
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_failed_unparsed_output",
                message="batch crash",
                returncode=1,
            )
        if "unsafe_a.cpp" in cmd:
            output = (
                f"{source_a}:7:5: warning: call to 'strcpy' is insecure [clang-analyzer-security.insecureAPI.strcpy]\n"
            )
            return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)
        if "unsafe_b.cpp" in cmd:
            return ToolRunResult(entries=[], status="empty", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        security_mod,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    result = detect_cxx_security(
        [str(source_a.resolve()), str(source_b.resolve())],
        zone_map=None,
    )

    assert len(calls) == 3
    assert result.coverage is None
    assert result.files_scanned == 2
    assert len(result.entries) == 1
    assert result.entries[0]["detail"]["source"] == "clang-tidy"
    assert result.entries[0]["detail"]["check_id"] == "clang-analyzer-security.insecureAPI.strcpy"


def test_detect_cxx_security_prefers_clang_tidy_for_duplicate_same_line(tmp_path, monkeypatch):
    source = tmp_path / "src" / "unsafe.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "compile_commands.json").write_text("[]\n")

    def _fake_which(cmd: str) -> str | None:
        if cmd in {"clang-tidy", "cppcheck"}:
            return f"C:/tools/{cmd}.exe"
        return None

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
        if cmd.startswith("clang-tidy "):
            output = (
                f"{source}:5:5: warning: calling 'system' uses a command processor [cert-env33-c]\n"
            )
            return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)
        if cmd.startswith("cppcheck "):
            output = f"{source}:5:warning:dangerousFunctionSystem:Using 'system' can be unsafe\n"
            return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=_fake_which),
        raising=False,
    )
    monkeypatch.setattr(
        security_mod,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    result = detect_cxx_security([str(source.resolve())], zone_map=None)

    assert result.coverage is None
    assert result.files_scanned == 1
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry["detail"]["kind"] == "command_injection"
    assert entry["detail"]["source"] == "clang-tidy"
    assert entry["detail"]["check_id"] == "cert-env33-c"


def test_detect_cxx_security_falls_back_to_regex_when_scan_root_detection_fails(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "src" / "unsafe.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int issue(const char* cmd) { return system(cmd); }\n")

    monkeypatch.setattr(
        security_mod.os.path,
        "commonpath",
        lambda _paths: (_ for _ in ()).throw(ValueError("mixed drives")),
    )
    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=lambda _cmd: None),
        raising=False,
    )

    result = detect_cxx_security([str(source.resolve())], zone_map=None)

    assert result.files_scanned == 1
    assert result.coverage is not None
    assert result.coverage.status == "reduced"
    assert len(result.entries) == 1
    assert result.entries[0]["detail"]["kind"] == "command_injection"
    assert result.entries[0]["detail"]["source"] == "regex"


def test_detect_cxx_security_falls_back_to_regex_for_header_only_scan(
    tmp_path,
    monkeypatch,
):
    header = tmp_path / "include" / "unsafe.hpp"
    header.parent.mkdir(parents=True)
    header.write_text("char* copy(char* dst, const char* src) { return strcpy(dst, src); }\n")
    (tmp_path / "compile_commands.json").write_text("[]\n")

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=lambda cmd: "C:/tools/clang-tidy.exe" if cmd == "clang-tidy" else None),
        raising=False,
    )

    result = detect_cxx_security([str(header.resolve())], zone_map=None)

    assert result.files_scanned == 1
    assert result.coverage is not None
    assert result.coverage.status == "reduced"
    assert len(result.entries) == 1
    assert result.entries[0]["detail"]["kind"] == "unsafe_c_string"
    assert result.entries[0]["detail"]["source"] == "regex"


def test_detect_cxx_security_keeps_distinct_same_line_tool_findings(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "src" / "unsafe.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "compile_commands.json").write_text("[]\n")

    monkeypatch.setattr(
        security_mod,
        "shutil",
        SimpleNamespace(which=lambda cmd: "C:/tools/clang-tidy.exe" if cmd == "clang-tidy" else None),
        raising=False,
    )

    def _fake_run_tool_result(cmd, path, parser, **_kwargs):
        assert cmd.startswith("clang-tidy ")
        output = (
            f"{source}:7:5: warning: call to 'strcpy' is insecure [clang-analyzer-security.insecureAPI.strcpy]\n"
            f"{source}:7:5: warning: call to 'strcat' is insecure [clang-analyzer-security.insecureAPI.strcat]\n"
        )
        return ToolRunResult(entries=parser(output, path), status="ok", returncode=1)

    monkeypatch.setattr(
        security_mod,
        "run_tool_result",
        _fake_run_tool_result,
        raising=False,
    )

    result = detect_cxx_security([str(source.resolve())], zone_map=None)

    assert result.coverage is None
    assert result.files_scanned == 1
    assert len(result.entries) == 2
    assert {entry["detail"]["check_id"] for entry in result.entries} == {
        "clang-analyzer-security.insecureAPI.strcpy",
        "clang-analyzer-security.insecureAPI.strcat",
    }


def test_normalize_tool_entries_ignores_cppcheck_syntax_error_with_fontsystem_name():
    entries = security_mod._normalize_tool_entries(
        [
            {
                "file": r"D:/repo/FontSystem.h",
                "line": 9,
                "severity": "error",
                "check_id": "syntaxError",
                "message": "Code 'namespaceFontSystem{' is invalid C code.",
                "source": "cppcheck",
            }
        ]
    )

    assert entries == []


def test_normalize_tool_entries_ignores_cppcheck_random_prefix_false_positive():
    entries = security_mod._normalize_tool_entries(
        [
            {
                "file": r"D:/repo/RandomFrameAccessPlugin.cpp",
                "line": 44,
                "severity": "warning",
                "check_id": "uninitMemberVar",
                "message": "Member variable 'RandomFrameAccessProcessor::_currSrcImg' is not initialized in the constructor.",
                "source": "cppcheck",
            }
        ]
    )

    assert entries == []


def test_normalize_tool_entries_ignores_generic_buffer_size_message():
    entries = security_mod._normalize_tool_entries(
        [
            {
                "file": r"D:/repo/math.cpp",
                "line": 12,
                "severity": "warning",
                "check_id": "zerodiv",
                "message": "Possible division by zero when buffer size is zero.",
                "source": "cppcheck",
            }
        ]
    )

    assert entries == []


def test_cxx_config_security_hook_returns_lang_result(tmp_path):
    source = tmp_path / "src" / "token.cpp"
    source.parent.mkdir(parents=True)
    source.write_text(
        "#include <cstdlib>\n"
        "int issue(const char* cmd) {\n"
        "    return std::system(cmd);\n"
        "}\n"
    )

    cfg = CxxConfig()
    result = cfg.detect_lang_security_detailed([str(source.resolve())], zone_map=None)

    assert isinstance(result, LangSecurityResult)
    assert result.files_scanned == 1
    assert result.entries
    assert result.entries[0]["detail"]["kind"] == "command_injection"
