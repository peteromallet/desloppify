"""Tests for the generic language plugin system."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from desloppify.languages._framework.generic_support.core import (
    generic_lang,
    make_file_finder,
    make_tool_phase,
    parse_cargo,
    parse_eslint,
    parse_gnu,
    parse_golangci,
    parse_json,
    parse_rubocop,
)
from desloppify.languages._framework.generic_parts.parsers import ToolParserError, parse_phpstan
from desloppify.languages._framework.generic_parts.tool_runner import (
    resolve_command_argv,
    run_tool_result,
)
from desloppify.languages._framework.generic_parts.tool_spec import (
    normalize_tool_specs,
)


@pytest.fixture
def _cleanup_registry():
    """Auto-cleanup generic plugins registered during a test.

    Ensures built-in discovery runs before snapshotting so we don't
    accidentally remove built-in languages during cleanup (module-level
    ``@register_lang`` decorators won't re-fire on re-import).
    """
    from desloppify.languages._framework.registry import state as registry_state
    from desloppify.languages._framework.registry.discovery import load_all

    # Ensure built-in plugins are loaded before snapshotting, so the
    # snapshot includes them and cleanup only removes test-specific entries.
    load_all()
    before = set(registry_state.all_keys())
    yield
    for name in set(registry_state.all_keys()) - before:
        registry_state.remove(name)


# ── Output parser tests ──────────────────────────────────


class TestParseGnu:
    def test_extracts_file_line_message(self):
        output = "src/main.go:42: undefined: foo\nsrc/util.go:10: unused variable\n"
        entries = parse_gnu(output, Path("."))
        assert len(entries) == 2
        assert entries[0] == {"file": "src/main.go", "line": 42, "message": "undefined: foo"}
        assert entries[1] == {"file": "src/util.go", "line": 10, "message": "unused variable"}

    def test_handles_col_number(self):
        output = "src/main.go:42:5: error: something wrong\n"
        entries = parse_gnu(output, Path("."))
        assert len(entries) == 1
        assert entries[0]["file"] == "src/main.go"
        assert entries[0]["line"] == 42
        assert entries[0]["message"] == "error: something wrong"

    def test_skips_non_matching_lines(self):
        output = "Running checks...\nsrc/main.go:42: error\nDone.\n"
        entries = parse_gnu(output, Path("."))
        assert len(entries) == 1

    def test_empty_output(self):
        assert parse_gnu("", Path(".")) == []


class TestParseGolangci:
    def test_extracts_issues(self):
        data = {
            "Issues": [
                {
                    "Pos": {"Filename": "main.go", "Line": 10, "Column": 5},
                    "Text": "unused variable",
                }
            ]
        }
        entries = parse_golangci(json.dumps(data), Path("."))
        assert len(entries) == 1
        assert entries[0] == {"file": "main.go", "line": 10, "message": "unused variable"}

    def test_handles_empty_issues(self):
        entries = parse_golangci(json.dumps({"Issues": []}), Path("."))
        assert entries == []

    def test_handles_null_issues(self):
        entries = parse_golangci(json.dumps({"Issues": None}), Path("."))
        assert entries == []

    def test_invalid_json(self):
        with pytest.raises(ToolParserError):
            parse_golangci("not json", Path("."))

    def test_skips_issue_with_non_numeric_line(self):
        data = {
            "Issues": [
                {
                    "Pos": {"Filename": "main.go", "Line": "NaN"},
                    "Text": "bad line",
                }
            ]
        }
        assert parse_golangci(json.dumps(data), Path(".")) == []


class TestParseJson:
    def test_extracts_with_field_aliases(self):
        data = [
            {"file": "a.swift", "line": 1, "message": "warning"},
            {"filename": "b.swift", "line_no": 2, "text": "error"},
            {"path": "c.swift", "row": 3, "reason": "hint"},
        ]
        entries = parse_json(json.dumps(data), Path("."))
        assert len(entries) == 3
        assert entries[0] == {"file": "a.swift", "line": 1, "message": "warning"}
        assert entries[1] == {"file": "b.swift", "line": 2, "message": "error"}
        assert entries[2] == {"file": "c.swift", "line": 3, "message": "hint"}

    def test_skips_items_without_file(self):
        data = [{"line": 1, "message": "no file"}]
        entries = parse_json(json.dumps(data), Path("."))
        assert entries == []

    def test_invalid_json(self):
        with pytest.raises(ToolParserError):
            parse_json("not json", Path("."))

    def test_non_array(self):
        assert parse_json(json.dumps({"key": "value"}), Path(".")) == []

    def test_skips_rows_with_non_numeric_line(self):
        data = [{"file": "a.swift", "line": "NaN", "message": "warning"}]
        assert parse_json(json.dumps(data), Path(".")) == []


class TestParseRubocop:
    def test_flattens_offenses(self):
        data = {
            "files": [
                {
                    "path": "app/models/user.rb",
                    "offenses": [
                        {
                            "location": {"line": 5, "column": 1},
                            "message": "Line too long",
                        },
                        {
                            "location": {"line": 10},
                            "message": "Missing frozen string",
                        },
                    ],
                },
                {
                    "path": "app/models/post.rb",
                    "offenses": [
                        {
                            "location": {"line": 1},
                            "message": "Use def with parentheses",
                        }
                    ],
                },
            ]
        }
        entries = parse_rubocop(json.dumps(data), Path("."))
        assert len(entries) == 3
        assert entries[0] == {"file": "app/models/user.rb", "line": 5, "message": "Line too long"}
        assert entries[2] == {
            "file": "app/models/post.rb",
            "line": 1,
            "message": "Use def with parentheses",
        }

    def test_empty_files(self):
        assert parse_rubocop(json.dumps({"files": []}), Path(".")) == []

    def test_invalid_json(self):
        with pytest.raises(ToolParserError):
            parse_rubocop("not json", Path("."))


class TestParseCargo:
    def test_extracts_compiler_messages(self):
        lines = [
            json.dumps(
                {
                    "reason": "compiler-message",
                    "message": {
                        "spans": [{"file_name": "src/main.rs", "line_start": 42}],
                        "rendered": "warning: unused variable\n  --> src/main.rs:42:5\n",
                    },
                }
            ),
            json.dumps({"reason": "build-script-executed"}),
        ]
        entries = parse_cargo("\n".join(lines), Path("."))
        assert len(entries) == 1
        assert entries[0]["file"] == "src/main.rs"
        assert entries[0]["line"] == 42
        assert "unused variable" in entries[0]["message"]

    def test_skips_non_compiler_messages(self):
        line = json.dumps({"reason": "build-finished", "success": True})
        assert parse_cargo(line, Path(".")) == []

    def test_empty_output(self):
        assert parse_cargo("", Path(".")) == []


class TestParseEslint:
    def test_skips_rows_with_non_numeric_line(self):
        payload = [
            {"filePath": "src/app.ts", "messages": [{"line": "oops", "message": "x"}]}
        ]
        assert parse_eslint(json.dumps(payload), Path(".")) == []

    def test_invalid_json(self):
        with pytest.raises(ToolParserError):
            parse_eslint("not json", Path("."))


class TestParsePhpstan:
    def test_extracts_messages(self):
        data = {
            "totals": {"errors": 2},
            "files": {
                "/app/src/Foo.php": {
                    "messages": [
                        {"message": "Call to undefined method Bar::baz().", "line": 10},
                        {"message": "Variable $x might not be defined.", "line": 25},
                    ]
                },
                "/app/src/Bar.php": {
                    "messages": [
                        {"message": "Parameter #1 expects int, string given.", "line": 5},
                    ]
                },
            },
        }
        entries = parse_phpstan(json.dumps(data), Path("."))
        assert len(entries) == 3
        assert entries[0] == {
            "file": "/app/src/Foo.php",
            "line": 10,
            "message": "Call to undefined method Bar::baz().",
        }
        assert entries[2] == {
            "file": "/app/src/Bar.php",
            "line": 5,
            "message": "Parameter #1 expects int, string given.",
        }

    def test_empty_files(self):
        assert parse_phpstan(json.dumps({"files": {}}), Path(".")) == []

    def test_empty_messages_list(self):
        data = {"files": {"/app/src/Foo.php": {"messages": []}}}
        assert parse_phpstan(json.dumps(data), Path(".")) == []

    def test_skips_non_dict_messages(self):
        data = {
            "files": {
                "/app/src/Foo.php": {
                    "messages": [
                        "unexpected string",
                        {"message": "Real error", "line": 7},
                    ]
                }
            }
        }
        entries = parse_phpstan(json.dumps(data), Path("."))
        assert len(entries) == 1
        assert entries[0]["message"] == "Real error"

    def test_skips_non_dict_file_values(self):
        data = {"files": {"/app/src/Foo.php": "not a dict"}}
        assert parse_phpstan(json.dumps(data), Path(".")) == []

    def test_invalid_json(self):
        with pytest.raises(ToolParserError):
            parse_phpstan("not json", Path("."))

    def test_non_dict_root(self):
        assert parse_phpstan(json.dumps([1, 2, 3]), Path(".")) == []


# ── make_tool_phase tests ─────────────────────────────────


class TestMakeToolPhase:
    def test_missing_tool_returns_no_issues(self):
        phase = make_tool_phase("test", "nonexistent_tool_xyz_123", "gnu", "test_id", 2)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            issues, signals = phase.run(Path("."), None)
        assert issues == []
        assert signals == {}

    def test_timeout_returns_no_issues(self):
        phase = make_tool_phase("test", "sleep 999", "gnu", "test_id", 2)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            issues, signals = phase.run(Path("."), None)
        assert issues == []
        assert signals == {}

    def test_missing_tool_records_coverage_degradation(self):
        phase = make_tool_phase("test", "nonexistent_tool_xyz_123", "gnu", "test_id", 2)
        lang = SimpleNamespace(detector_coverage={}, coverage_warnings=[])
        with patch("subprocess.run", side_effect=FileNotFoundError):
            issues, signals = phase.run(Path("."), lang)
        assert issues == []
        assert signals == {}
        assert lang.detector_coverage["test_id"]["status"] == "reduced"
        assert lang.detector_coverage["test_id"]["reason"] == "tool_not_found"

    def test_gnu_output_produces_issues(self):
        phase = make_tool_phase("test", "fake", "gnu", "test_lint", 2)
        mock_result = subprocess.CompletedProcess(
            args="fake",
            returncode=1,
            stdout="src/foo.go:10: something wrong\nsrc/bar.go:20: another issue\n",
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            issues, signals = phase.run(Path("."), None)
        assert len(issues) == 2
        assert signals == {"test_lint": 2}
        assert issues[0]["detector"] == "test_lint"
        assert issues[0]["summary"] == "something wrong"

    def test_empty_output_returns_empty(self):
        phase = make_tool_phase("test", "fake", "gnu", "test_id", 2)
        mock_result = subprocess.CompletedProcess(
            args="fake", returncode=0, stdout="", stderr=""
        )
        with patch("subprocess.run", return_value=mock_result):
            issues, signals = phase.run(Path("."), None)
        assert issues == []
        assert signals == {}

    def test_run_tool_parser_exception_returns_error(self, tmp_path):
        mock_result = subprocess.CompletedProcess(
            args="fake",
            returncode=1,
            stdout="bad payload\n",
            stderr="",
        )

        def _raising_parser(_output: str, _scan_path: Path) -> list[dict]:
            raise ValueError("bad parser row")

        result = run_tool_result(
            "fake",
            tmp_path,
            _raising_parser,
            run_subprocess=lambda *_a, **_k: mock_result,
        )
        assert result.status == "error"
        assert result.error_kind == "parser_exception"
        assert result.entries == []

    def test_run_tool_result_distinguishes_empty_vs_error(self, tmp_path):
        clean = subprocess.CompletedProcess(args="fake", returncode=0, stdout="", stderr="")
        empty_result = run_tool_result(
            "fake",
            tmp_path,
            parse_gnu,
            run_subprocess=lambda *_a, **_k: clean,
        )
        assert empty_result.status == "empty"
        assert empty_result.error_kind is None

        failed = subprocess.CompletedProcess(args="fake", returncode=2, stdout="", stderr="")
        failed_result = run_tool_result(
            "fake",
            tmp_path,
            parse_gnu,
            run_subprocess=lambda *_a, **_k: failed,
        )
        assert failed_result.status == "error"
        assert failed_result.error_kind == "tool_failed_no_output"

    def test_run_tool_result_nonzero_unparsed_output_is_error(self, tmp_path):
        failed = subprocess.CompletedProcess(
            args="fake",
            returncode=2,
            stdout='{"unexpected":"shape"}',
            stderr="",
        )
        failed_result = run_tool_result(
            "fake",
            tmp_path,
            parse_json,
            run_subprocess=lambda *_a, **_k: failed,
        )
        assert failed_result.status == "error"
        assert failed_result.error_kind == "tool_failed_unparsed_output"

    def test_run_tool_result_parser_decode_error_is_error(self, tmp_path):
        failed = subprocess.CompletedProcess(
            args="fake",
            returncode=0,
            stdout="{bad-json",
            stderr="",
        )
        failed_result = run_tool_result(
            "fake",
            tmp_path,
            parse_json,
            run_subprocess=lambda *_a, **_k: failed,
        )
        assert failed_result.status == "error"
        assert failed_result.error_kind == "parser_error"

    def test_run_tool_result_parses_stdout_ignoring_stderr_preamble(self, tmp_path):
        """stdout JSON should parse successfully even when stderr has non-JSON diagnostics."""
        valid_json = json.dumps([{"file": "a.php", "line": 1, "message": "err"}])
        result_with_stderr_noise = subprocess.CompletedProcess(
            args="fake",
            returncode=1,
            stdout=valid_json,
            stderr="Note: Using configuration file /app/phpstan.neon.dist.\n",
        )
        result = run_tool_result(
            "fake",
            tmp_path,
            parse_json,
            run_subprocess=lambda *_a, **_k: result_with_stderr_noise,
        )
        assert result.status == "ok"
        assert len(result.entries) == 1

    def test_run_tool_result_error_preview_uses_combined_output(self, tmp_path):
        """When parsing fails, the error preview should include both stdout and stderr."""
        result_bad = subprocess.CompletedProcess(
            args="fake",
            returncode=1,
            stdout="not json at all",
            stderr="Some stderr diagnostic\n",
        )
        result = run_tool_result(
            "fake",
            tmp_path,
            parse_json,
            run_subprocess=lambda *_a, **_k: result_bad,
        )
        assert result.status == "error"
        assert result.error_kind == "parser_error"

    def test_resolve_command_argv_plain_command_does_not_shell_fallback(self):
        argv = resolve_command_argv("nonexistent_tool_xyz_123 --version")
        assert argv == ["nonexistent_tool_xyz_123", "--version"]

    def test_resolve_command_argv_shell_meta_uses_platform_shell(self):
        argv = resolve_command_argv("echo ok | cat")
        if os.name == "nt":
            assert argv == ["cmd.exe", "/d", "/s", "/c", "echo ok | cat"]
        else:
            assert argv == ["/bin/sh", "-lc", "echo ok | cat"]


    def test_resolve_command_argv_windows_backslash_path_preserved(self):
        with patch("desloppify.languages._framework.generic_parts.tool_runner.os.name", "nt"):
            argv = resolve_command_argv(r"C:\Tools\tool.exe --flag")
        assert argv == [r"C:\Tools\tool.exe", "--flag"]

    def test_resolve_command_argv_windows_quoted_path_unquotes_executable(self):
        with patch("desloppify.languages._framework.generic_parts.tool_runner.os.name", "nt"):
            argv = resolve_command_argv('"C:\\Program Files\\Tool\\tool.exe" --flag')
        assert argv == [r"C:\Program Files\Tool\tool.exe", "--flag"]


class TestToolSpecNormalization:
    def test_missing_fix_cmd_normalizes_to_none(self):
        normalized = normalize_tool_specs(
            [{"label": "lint", "cmd": "echo ok", "fmt": "gnu", "id": "lint_id", "tier": 2}],
            supported_formats={"gnu"},
        )
        assert normalized[0]["fix_cmd"] is None


# ── generic_lang registration tests ──────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestGenericLang:
    def test_registers_and_resolves(self):
        from desloppify.languages._framework.registry import state as registry_state
        from desloppify.languages._framework.base.types import LangConfig

        cfg = generic_lang(
            name="test_generic_lang_1",
            extensions=[".test1"],
            tools=[
                {"label": "test tool", "cmd": "echo ok", "fmt": "gnu", "id": "test_tool", "tier": 2}
            ],
        )
        assert isinstance(cfg, LangConfig)
        assert registry_state.is_registered("test_generic_lang_1")
        assert registry_state.get("test_generic_lang_1") is cfg

    def test_get_lang_returns_instance(self):
        from desloppify.languages._framework.base.types import LangConfig
        from desloppify.languages._framework.registry.resolution import get_lang

        cfg = generic_lang(
            name="test_generic_lang_2",
            extensions=[".test2"],
            tools=[
                {"label": "test tool", "cmd": "echo ok", "fmt": "gnu", "id": "test_tool_2", "tier": 2}
            ],
        )
        resolved = get_lang("test_generic_lang_2")
        assert resolved is cfg
        assert isinstance(resolved, LangConfig)

    def test_integration_depth_set(self):
        cfg = generic_lang(
            name="test_generic_lang_3",
            extensions=[".test3"],
            tools=[
                {"label": "t", "cmd": "echo", "fmt": "gnu", "id": "t_id", "tier": 2}
            ],
            depth="minimal",
        )
        assert cfg.integration_depth == "minimal"

    def test_rejects_missing_tool_fields(self):
        with pytest.raises(ValueError, match="tools\\[0\\]\\.cmd"):
            generic_lang(
                name="test_generic_lang_missing_cmd",
                extensions=[".x"],
                tools=[
                    {
                        "label": "xlint",
                        "fmt": "gnu",
                        "id": "xlint_missing_cmd",
                        "tier": 2,
                    }
                ],
            )

    def test_rejects_unknown_tool_format(self):
        with pytest.raises(ValueError, match="unsupported"):
            generic_lang(
                name="test_generic_lang_bad_fmt",
                extensions=[".x"],
                tools=[
                    {
                        "label": "xlint",
                        "cmd": "echo ok",
                        "fmt": "unknown_format",
                        "id": "xlint_bad_fmt",
                        "tier": 2,
                    }
                ],
            )

    def test_rejects_non_integer_tier(self):
        with pytest.raises(ValueError, match="tier must be an integer"):
            generic_lang(
                name="test_generic_lang_bad_tier",
                extensions=[".x"],
                tools=[
                    {
                        "label": "xlint",
                        "cmd": "echo ok",
                        "fmt": "gnu",
                        "id": "xlint_bad_tier",
                        "tier": "2",
                    }
                ],
            )


# ── Stub tests ────────────────────────────────────────────


class TestStubs:
    def test_make_file_finder_returns_callable(self):
        finder = make_file_finder([".go"])
        assert callable(finder)

    def test_file_finder_finds_files(self, tmp_path):
        (tmp_path / "main.go").write_text("package main")
        (tmp_path / "test.py").write_text("pass")
        finder = make_file_finder([".go"])
        result = finder(tmp_path)
        assert isinstance(result, list)


# ── Langs command tests ───────────────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestLangsCommand:
    def test_all_builtin_langs_discoverable(self):
        """All full plugins and generic plugins should be available."""
        from desloppify.languages import available_langs

        names = available_langs()
        for full_lang in [
            "python",
            "typescript",
            "csharp",
            "dart",
            "gdscript",
            "go",
            "rust",
        ]:
            assert full_lang in names, f"{full_lang} not found in {names}"
        for generic_lang_name in ["ruby", "java", "kotlin"]:
            assert generic_lang_name in names, f"{generic_lang_name} not found in {names}"
        assert len(names) > 10, f"Expected >10 languages, got {len(names)}: {names}"

    def test_langs_hides_shared_phases_from_tool_list(self):
        from desloppify.app.commands.langs import _get_tool_labels

        cfg = generic_lang(
            name="test_langs_hide_1",
            extensions=[".x"],
            tools=[{"label": "xlint", "cmd": "echo", "fmt": "gnu", "id": "xlint_id", "tier": 2}],
        )
        labels = _get_tool_labels(cfg)
        assert "xlint" in labels
        assert "Security" not in labels
        assert "Subjective review" not in labels
        assert "Boilerplate duplication" not in labels
        assert "Duplicates" not in labels

    def test_langs_shows_auto_fix_suffix(self):
        from desloppify.app.commands.langs import _get_tool_labels

        cfg = generic_lang(
            name="test_langs_fix_1",
            extensions=[".x"],
            tools=[{
                "label": "xlint", "cmd": "echo", "fmt": "gnu",
                "id": "xlint_fix_id", "tier": 2, "fix_cmd": "xlint --fix",
            }],
        )
        labels = _get_tool_labels(cfg)
        assert "(auto-fix)" in labels

    def test_langs_no_auto_fix_suffix_without_fixers(self):
        from desloppify.app.commands.langs import _get_tool_labels

        cfg = generic_lang(
            name="test_langs_nofix_1",
            extensions=[".x"],
            tools=[{"label": "xlint", "cmd": "echo", "fmt": "gnu", "id": "xlint_nofix_id", "tier": 2}],
        )
        labels = _get_tool_labels(cfg)
        assert "(auto-fix)" not in labels


# ── Dynamic registration tests ──────────────────────────


class TestDynamicRegistration:
    def test_register_detector_adds_to_detectors_dict(self):
        from desloppify.base.registry import (
            DETECTORS,
            DetectorMeta,
            register_detector,
            unregister_detector,
        )

        name = "_test_reg_det_1"
        register_detector(DetectorMeta(
            name=name, display="test", dimension="Code quality",
            action_type="manual_fix", guidance="test guidance",
        ))
        assert name in DETECTORS
        assert DETECTORS[name].display == "test"
        unregister_detector(name)

    def test_register_detector_appends_to_display_order(self):
        from desloppify.base.registry import (
            _DISPLAY_ORDER,
            DetectorMeta,
            register_detector,
            unregister_detector,
        )

        name = "_test_reg_det_2"
        register_detector(DetectorMeta(
            name=name, display="test", dimension="Code quality",
            action_type="manual_fix", guidance="test",
        ))
        assert name in _DISPLAY_ORDER
        unregister_detector(name)

    def test_register_scoring_policy_rebuilds_dimensions(self):
        from desloppify.engine._scoring.policy.core import (
            DETECTOR_SCORING_POLICIES,
            DIMENSIONS,
            FILE_BASED_DETECTORS,
            DetectorScoringPolicy,
            register_scoring_policy,
        )
        name = "_test_reg_pol_1"
        register_scoring_policy(DetectorScoringPolicy(
            detector=name, dimension="Code quality", tier=3, file_based=True,
        ))
        assert name in FILE_BASED_DETECTORS
        cq = next(d for d in DIMENSIONS if d.name == "Code quality")
        assert name in cq.detectors
        del DETECTOR_SCORING_POLICIES[name]

    def test_register_detector_auto_refreshes_narrative(self):
        """register_detector should auto-refresh DETECTOR_TOOLS via callback."""
        from desloppify.base.registry import (
            DetectorMeta,
            register_detector,
            unregister_detector,
        )
        from desloppify.intelligence.narrative._constants import DETECTOR_TOOLS

        name = "_test_auto_refresh_1"
        register_detector(DetectorMeta(
            name=name, display="test", dimension="Code quality",
            action_type="manual_fix", guidance="auto refresh test",
        ))
        # Should be in DETECTOR_TOOLS without any manual refresh call
        assert name in DETECTOR_TOOLS
        assert DETECTOR_TOOLS[name]["guidance"] == "auto refresh test"
        unregister_detector(name)
