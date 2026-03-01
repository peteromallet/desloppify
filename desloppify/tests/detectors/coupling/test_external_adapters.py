"""Tests for external tool adapters: Knip, ruff smells, and bandit.

Each adapter must:
  1. Return None (not crash) when the tool is not installed.
  2. Correctly parse the tool's JSON output format.
  3. Produce entries/findings in the structure the phase runners expect.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Knip adapter ────────────────────────────────────────────────────────────
from desloppify.languages.typescript.detectors.knip_adapter import detect_with_knip


class TestKnipAdapter:
    def _run_detect(self, stdout: str):
        """Patch subprocess.run to return a synthetic Knip result."""
        mock_result = MagicMock()
        mock_result.stdout = stdout
        with patch("subprocess.run", return_value=mock_result):
            return detect_with_knip(Path("/fake/project"))

    def test_returns_none_when_knip_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("npx not found")):
            assert detect_with_knip(Path("/fake/project")) is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("npx", 120)):
            assert detect_with_knip(Path("/fake/project")) is None

    def test_returns_none_on_empty_output(self):
        assert self._run_detect(stdout="") is None

    def test_returns_none_on_invalid_json(self):
        assert self._run_detect(stdout="not-json") is None

    def test_empty_knip_output_returns_empty_list(self):
        result = self._run_detect(stdout=json.dumps({"issues": []}))
        assert result == []

    def test_parses_dead_exports(self, tmp_path):
        f = tmp_path / "utils.ts"
        f.write_text("export function unused() {}")
        payload = json.dumps(
            {
                "issues": [
                    {
                        "file": str(f),
                        "exports": [
                            {"name": "unused", "pos": {"start": {"line": 1, "col": 0}}}
                        ],
                    }
                ]
            }
        )
        mock_result = MagicMock()
        mock_result.stdout = payload
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_knip(tmp_path)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "unused"
        assert result[0]["kind"] == "export"
        assert result[0]["line"] == 1

    def test_parses_dead_type_exports(self, tmp_path):
        f = tmp_path / "types.ts"
        f.write_text("export type MyType = string;")
        payload = json.dumps(
            {
                "issues": [
                    {
                        "file": str(f),
                        "types": [{"name": "MyType", "pos": {"start": {"line": 2, "col": 0}}}],
                    }
                ]
            }
        )
        mock_result = MagicMock()
        mock_result.stdout = payload
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_knip(tmp_path)
        assert result is not None
        assert any(e["kind"] == "type" and e["name"] == "MyType" for e in result)

    def test_skips_files_outside_scan_path(self, tmp_path):
        payload = json.dumps(
            {
                "issues": [
                    {
                        "file": "/other/path/file.ts",
                        "exports": [{"name": "gone", "pos": {"start": {"line": 1, "col": 0}}}],
                    }
                ]
            }
        )
        mock_result = MagicMock()
        mock_result.stdout = payload
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_knip(tmp_path)
        assert result == []


# ── Ruff smells adapter ──────────────────────────────────────────────────────


from desloppify.languages.python.detectors.ruff_smells import detect_with_ruff_smells  # noqa: E402,I001


class TestRuffSmellsAdapter:
    def _run_detect(self, stdout: str):
        mock_result = MagicMock()
        mock_result.stdout = stdout

        with patch("subprocess.run", return_value=mock_result):
            return detect_with_ruff_smells(Path("/fake/project"))

    def test_returns_none_when_ruff_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("ruff not found")):
            assert detect_with_ruff_smells(Path("/fake/project")) is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 60)):
            assert detect_with_ruff_smells(Path("/fake/project")) is None

    def test_returns_empty_on_no_diagnostics(self):
        result = self._run_detect(stdout="[]")
        assert result == []

    def test_returns_empty_on_empty_output(self):
        result = self._run_detect(stdout="")
        assert result == []

    def test_returns_none_on_invalid_json(self):
        result = self._run_detect(stdout="not-json")
        assert result is None

    def test_parses_b007_unused_loop_var(self):
        diagnostics = [
            {
                "code": "B007",
                "filename": "/project/util.py",
                "message": "Loop control variable `i` not used in loop body",
                "location": {"row": 10, "column": 4},
            }
        ]
        result = self._run_detect(stdout=json.dumps(diagnostics))
        assert result is not None
        assert len(result) == 1
        entry = result[0]
        assert entry["id"] == "unused_loop_var"
        assert entry["severity"] == "medium"
        assert len(entry["matches"]) == 1
        assert entry["matches"][0]["line"] == 10

    def test_parses_e711_none_comparison(self):
        diagnostics = [
            {
                "code": "E711",
                "filename": "/project/utils.py",
                "message": "Comparison to `None` (use `is`)",
                "location": {"row": 5, "column": 8},
            }
        ]
        result = self._run_detect(stdout=json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "none_comparison" for e in result)

    def test_parses_w605_invalid_escape(self):
        diagnostics = [
            {
                "code": "W605",
                "filename": "/project/parse.py",
                "message": r"Invalid escape sequence: `\d`",
                "location": {"row": 3, "column": 0},
            }
        ]
        result = self._run_detect(stdout=json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "invalid_escape" for e in result)

    def test_groups_multiple_matches_by_code(self):
        diagnostics = [
            {
                "code": "B907",  # unknown — should be skipped
                "filename": "/project/x.py",
                "message": "unknown",
                "location": {"row": 1, "column": 0},
            },
            {
                "code": "E711",
                "filename": "/project/a.py",
                "message": "None comparison",
                "location": {"row": 3, "column": 0},
            },
            {
                "code": "E711",
                "filename": "/project/b.py",
                "message": "None comparison",
                "location": {"row": 7, "column": 0},
            },
        ]
        result = self._run_detect(stdout=json.dumps(diagnostics))
        assert result is not None
        none_entries = [e for e in result if e["id"] == "none_comparison"]
        assert len(none_entries) == 1  # grouped under one code
        assert len(none_entries[0]["matches"]) == 2

    def test_unknown_codes_are_skipped(self):
        diagnostics = [
            {
                "code": "Z999",
                "filename": "/project/x.py",
                "message": "unknown rule",
                "location": {"row": 1, "column": 0},
            }
        ]
        result = self._run_detect(stdout=json.dumps(diagnostics))
        assert result == []

    def test_smell_entry_has_required_fields(self):
        diagnostics = [
            {
                "code": "B904",
                "filename": "/project/ex.py",
                "message": "Use `raise from` in except clause",
                "location": {"row": 20, "column": 8},
            }
        ]
        result = self._run_detect(stdout=json.dumps(diagnostics))
        assert result is not None and len(result) == 1
        entry = result[0]
        assert "id" in entry
        assert "label" in entry
        assert "severity" in entry
        assert "matches" in entry
        assert isinstance(entry["matches"], list)


# ── Bandit adapter ───────────────────────────────────────────────────────────


from desloppify.languages.python.detectors.bandit_adapter import (  # noqa: E402
    _to_security_entry,
    detect_with_bandit,
)


class TestBanditAdapter:
    def _bandit_result(self, results: list[dict], metrics: dict | None = None) -> str:
        return json.dumps({"results": results, "errors": [], "metrics": metrics or {}})

    def _run_detect(self, stdout: str, tmp_path=None):
        mock_result = MagicMock()
        mock_result.stdout = stdout
        path = tmp_path or Path("/fake/project")

        with patch("subprocess.run", return_value=mock_result):
            return detect_with_bandit(path, zone_map=None)

    def test_returns_missing_tool_status_when_bandit_not_installed(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError("bandit not found")):
            result = detect_with_bandit(tmp_path, zone_map=None)
        assert result.status.state == "missing_tool"
        coverage = result.status.coverage()
        assert coverage is not None
        assert coverage.detector == "security"
        assert coverage.status == "reduced"

    def test_returns_timeout_status_on_timeout(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bandit", 120)):
            result = detect_with_bandit(tmp_path, zone_map=None)
        assert result.status.state == "timeout"
        assert result.status.coverage() is not None

    def test_returns_empty_on_no_findings(self):
        result = self._run_detect(stdout=self._bandit_result([]))
        assert result.status.state == "ok"
        assert result.entries == []
        assert result.files_scanned == 0

    def test_returns_empty_on_empty_stdout(self):
        result = self._run_detect(stdout="")
        assert result.status.state == "ok"
        assert result.entries == []

    def test_returns_parse_error_on_invalid_json(self):
        mock_result = MagicMock()
        mock_result.stdout = "not-json"
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_bandit(Path("/fake"), zone_map=None)
        assert result.status.state == "parse_error"
        assert result.entries == []
        assert result.status.coverage() is not None

    def test_parses_high_severity_finding(self):
        raw = [
            {
                "filename": "/project/app.py",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "issue_text": "Use of exec detected.",
                "line_number": 42,
                "test_id": "B102",
                "test_name": "exec_used",
                "code": "exec(user_input)",
                "more_info": "https://bandit.readthedocs.io",
            }
        ]
        result = self._run_detect(stdout=self._bandit_result(raw))
        entries = result.entries
        assert len(entries) == 1
        e = entries[0]
        assert e["confidence"] == "high"
        assert e["tier"] == 4
        assert "B102" in e["summary"]
        assert e["detail"]["kind"] == "B102"
        assert e["detail"]["source"] == "bandit"

    def test_parses_medium_severity_finding(self):
        raw = [
            {
                "filename": "/project/api.py",
                "issue_severity": "MEDIUM",
                "issue_confidence": "HIGH",
                "issue_text": "Consider possible security implications.",
                "line_number": 10,
                "test_id": "B608",
                "test_name": "hardcoded_sql_expressions",
                "code": "query = 'SELECT * FROM users WHERE id=' + uid",
                "more_info": "",
            }
        ]
        result = self._run_detect(stdout=self._bandit_result(raw))
        entries = result.entries
        assert len(entries) == 1
        assert entries[0]["confidence"] == "medium"
        assert entries[0]["tier"] == 3

    def test_suppresses_low_severity_low_confidence(self):
        raw = [
            {
                "filename": "/project/utils.py",
                "issue_severity": "LOW",
                "issue_confidence": "LOW",
                "issue_text": "Very noisy low-signal finding.",
                "line_number": 5,
                "test_id": "B999",
                "test_name": "fake_low_rule",
                "code": "x = 1",
                "more_info": "",
            }
        ]
        result = self._run_detect(stdout=self._bandit_result(raw))
        assert result.entries == []

    def test_skips_cross_lang_overlap_ids(self):
        """B105 (hardcoded_password_string) overlaps with cross-lang detector — skip it."""
        raw = [
            {
                "filename": "/project/config.py",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "issue_text": "Possible hardcoded password.",
                "line_number": 3,
                "test_id": "B105",
                "test_name": "hardcoded_password_string",
                "code": 'password = "abc123"',
                "more_info": "",
            }
        ]
        result = self._run_detect(stdout=self._bandit_result(raw))
        assert result.entries == []

    def test_finding_name_is_stable_and_unique(self):
        raw = [
            {
                "filename": "/project/app.py",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "issue_text": "exec() usage",
                "line_number": 10,
                "test_id": "B102",
                "test_name": "exec_used",
                "code": "exec(x)",
                "more_info": "",
            }
        ]
        result = self._run_detect(stdout=self._bandit_result(raw))
        entries = result.entries
        assert "B102" in entries[0]["name"]
        assert "10" in entries[0]["name"]

    def test_to_security_entry_returns_none_for_empty_filename(self):
        result = _to_security_entry({"filename": "", "test_id": "B102"}, zone_map=None)
        assert result is None

    def test_counts_files_scanned_from_metrics(self):
        metrics = {
            "/project/a.py": {"loc": 10},
            "/project/b.py": {"loc": 20},
            "_totals": {"loc": 30},
        }
        stdout = self._bandit_result([], metrics=metrics)
        result = self._run_detect(stdout=stdout)
        files_scanned = result.files_scanned
        # _totals should be excluded; 2 actual files
        assert files_scanned == 2

    def test_exclude_dirs_passed_to_subprocess(self):
        """When exclude_dirs is provided, bandit receives --exclude flag."""
        captured_cmd = []

        def _capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            mock_result = MagicMock()
            mock_result.stdout = self._bandit_result([])
            return mock_result

        with patch("subprocess.run", side_effect=_capture_run):
            detect_with_bandit(
                Path("/project"),
                zone_map=None,
                exclude_dirs=["/project/.venv", "/project/node_modules"],
            )

        assert "--exclude" in captured_cmd
        idx = captured_cmd.index("--exclude")
        exclude_value = captured_cmd[idx + 1]
        assert "/project/.venv" in exclude_value
        assert "/project/node_modules" in exclude_value

    def test_no_exclude_flag_when_exclude_dirs_empty(self):
        """When exclude_dirs is empty, --exclude is not added."""
        captured_cmd = []

        def _capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            mock_result = MagicMock()
            mock_result.stdout = self._bandit_result([])
            return mock_result

        with patch("subprocess.run", side_effect=_capture_run):
            detect_with_bandit(Path("/project"), zone_map=None, exclude_dirs=[])

        assert "--exclude" not in captured_cmd


class TestBanditExcludeIntegration:
    """Verify PythonConfig passes exclusion dirs to bandit."""

    def test_detect_lang_security_passes_exclusions_to_bandit(self):
        from desloppify.languages.python import PythonConfig

        config = PythonConfig()
        captured_kwargs = {}

        def _fake_bandit(path, zone_map, **kwargs):
            from desloppify.languages.python.detectors.bandit_adapter import (
                BanditRunStatus,
                BanditScanResult,
            )

            captured_kwargs.update(kwargs)
            return BanditScanResult(
                entries=[], files_scanned=0, status=BanditRunStatus(state="ok")
            )

        fake_exclude_dirs = ["/project/src/.venv", "/project/src/__pycache__", "/project/src/vendor"]
        files = ["/project/src/app.py", "/project/src/utils.py"]
        with patch(
            "desloppify.languages.python.detect_with_bandit", _fake_bandit
        ), patch(
            "desloppify.languages.python.collect_exclude_dirs",
            return_value=fake_exclude_dirs,
        ):
            config.detect_lang_security_detailed(files, zone_map=None)

        exclude_dirs = captured_kwargs.get("exclude_dirs", [])
        # Should pass through whatever collect_exclude_dirs returns.
        assert exclude_dirs == fake_exclude_dirs


# ── jscpd adapter ────────────────────────────────────────────────────────────


from desloppify.engine.detectors.jscpd_adapter import (  # noqa: E402
    _parse_jscpd_report,
    detect_with_jscpd,
)


class TestJscpdAdapter:
    def test_returns_none_when_jscpd_not_installed(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError("npx not found")):
            assert detect_with_jscpd(tmp_path) is None

    def test_returns_none_on_timeout(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("npx", 120)):
            assert detect_with_jscpd(tmp_path) is None

    def test_returns_empty_on_no_duplicates(self, tmp_path):
        result = _parse_jscpd_report({"duplicates": []}, tmp_path)
        assert result == []

    def test_returns_none_on_invalid_json_file(self, tmp_path):
        bad_report = tmp_path / "jscpd-report.json"
        bad_report.write_text("not-json")
        with patch("subprocess.run"), patch("tempfile.TemporaryDirectory") as mock_td:
            mock_td.return_value.__enter__.return_value = str(tmp_path)
            mock_td.return_value.__exit__.return_value = None
            result = detect_with_jscpd(tmp_path)
        assert result is None

    def test_clusters_pairs_with_same_fragment_hash(self, tmp_path):
        f1 = str(tmp_path / "a.py")
        f2 = str(tmp_path / "b.py")
        f3 = str(tmp_path / "c.py")
        fragment = "def foo():\n    pass\n    return None\n    # end"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f1, "start": 1},
                    "secondFile": {"name": f2, "start": 5},
                },
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f2, "start": 5},
                    "secondFile": {"name": f3, "start": 10},
                },
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert len(result) == 1  # Clustered into one entry
        assert result[0]["distinct_files"] == 3

    def test_distinct_files_counted_correctly(self, tmp_path):
        f1 = str(tmp_path / "a.py")
        f2 = str(tmp_path / "b.py")
        fragment = "x = 1\ny = 2\nz = 3\nw = 4"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f1, "start": 1},
                    "secondFile": {"name": f2, "start": 10},
                }
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert len(result) == 1
        assert result[0]["distinct_files"] == 2

    def test_skips_files_outside_scan_path(self, tmp_path):
        f_in = str(tmp_path / "a.py")
        f_out = "/other/path/b.py"
        fragment = "x = 1\ny = 2\nz = 3\nw = 4"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f_in, "start": 1},
                    "secondFile": {"name": f_out, "start": 5},
                }
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert result == []

    def test_sample_extracted_from_fragment(self, tmp_path):
        f1 = str(tmp_path / "a.py")
        f2 = str(tmp_path / "b.py")
        fragment = "line1\nline2\nline3\nline4\nline5\nline6"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 6,
                    "firstFile": {"name": f1, "start": 1},
                    "secondFile": {"name": f2, "start": 10},
                }
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert result[0]["sample"] == ["line1", "line2", "line3", "line4"]

    def test_skips_same_file_pairs(self, tmp_path):
        f1 = str(tmp_path / "a.py")
        fragment = "x = 1\ny = 2\nz = 3\nw = 4"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f1, "start": 3},
                    "secondFile": {"name": f1, "start": 30},
                }
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert result == []

    def test_skips_build_lib_source_mirror_pairs(self, tmp_path):
        f_build = str(tmp_path / "build" / "lib" / "pkg" / "module.py")
        f_src = str(tmp_path / "pkg" / "module.py")
        fragment = "x = 1\ny = 2\nz = 3\nw = 4"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f_build, "start": 8},
                    "secondFile": {"name": f_src, "start": 9},
                }
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert result == []

    def test_skips_artifact_paths(self, tmp_path):
        f_artifact = str(tmp_path / ".desloppify" / "cache.py")
        f_src = str(tmp_path / "pkg" / "module.py")
        fragment = "x = 1\ny = 2\nz = 3\nw = 4"
        report = {
            "duplicates": [
                {
                    "fragment": fragment,
                    "lines": 4,
                    "firstFile": {"name": f_artifact, "start": 2},
                    "secondFile": {"name": f_src, "start": 11},
                }
            ]
        }
        result = _parse_jscpd_report(report, tmp_path)
        assert result == []

    def test_detect_command_includes_artifact_ignores(self, tmp_path):
        report_file = tmp_path / "jscpd-report.json"
        report_file.write_text(json.dumps({"duplicates": []}))

        fake_dirs = [
            str(tmp_path / "build"),
            str(tmp_path / "node_modules"),
        ]

        def _fake_run(cmd, **kwargs):
            assert "--ignore" in cmd
            ignore_value = cmd[cmd.index("--ignore") + 1]
            assert "**/.desloppify/**" in ignore_value
            assert "**/.claude/**" in ignore_value
            assert "**/build/**" in ignore_value
            assert "**/node_modules/**" in ignore_value
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_fake_run), patch(
            "desloppify.engine.detectors.jscpd_adapter.collect_exclude_dirs",
            return_value=fake_dirs,
        ), patch(
            "desloppify.engine.detectors.jscpd_adapter.get_exclusions",
            return_value=(),
        ), patch(
            "tempfile.TemporaryDirectory"
        ) as mock_td:
            mock_td.return_value.__enter__.return_value = str(tmp_path)
            mock_td.return_value.__exit__.return_value = None
            result = detect_with_jscpd(tmp_path)
        assert result == []


# ── Extended ruff smells adapter ─────────────────────────────────────────────


class TestRuffSmellsAdapterExtended:
    """Tests for the 7 new ruff rules added in Migration 2."""

    def _run_detect(self, stdout: str):
        mock_result = MagicMock()
        mock_result.stdout = stdout
        with patch("subprocess.run", return_value=mock_result):
            return detect_with_ruff_smells(Path("/fake/project"))

    def test_parses_e722_bare_except(self):
        diagnostics = [
            {
                "code": "E722",
                "filename": "/p/a.py",
                "message": "Do not use bare 'except'",
                "location": {"row": 5, "column": 0},
            }
        ]
        result = self._run_detect(json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "bare_except" for e in result)

    def test_parses_ble001_broad_except(self):
        diagnostics = [
            {
                "code": "BLE001",
                "filename": "/p/a.py",
                "message": "Do not catch blind exception: `Exception`",
                "location": {"row": 8, "column": 4},
            }
        ]
        result = self._run_detect(json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "broad_except" for e in result)

    def test_parses_b006_mutable_default(self):
        diagnostics = [
            {
                "code": "B006",
                "filename": "/p/a.py",
                "message": "Do not use mutable data structures for argument defaults",
                "location": {"row": 3, "column": 0},
            }
        ]
        result = self._run_detect(json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "mutable_default" for e in result)

    def test_parses_ruf012_mutable_class_var(self):
        diagnostics = [
            {
                "code": "RUF012",
                "filename": "/p/a.py",
                "message": "Mutable class attributes should be annotated with `typing.ClassVar`",
                "location": {"row": 10, "column": 4},
            }
        ]
        result = self._run_detect(json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "mutable_class_var" for e in result)

    def test_parses_plw0603_global_keyword(self):
        diagnostics = [
            {
                "code": "PLW0603",
                "filename": "/p/a.py",
                "message": "Using the global statement to update `x`",
                "location": {"row": 7, "column": 4},
            }
        ]
        result = self._run_detect(json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "global_keyword" for e in result)

    def test_parses_f403_star_import(self):
        diagnostics = [
            {
                "code": "F403",
                "filename": "/p/a.py",
                "message": "`from foo import *` used; unable to detect undefined names",
                "location": {"row": 1, "column": 0},
            }
        ]
        result = self._run_detect(json.dumps(diagnostics))
        assert result is not None
        assert any(e["id"] == "star_import" for e in result)


# ── import-linter adapter ────────────────────────────────────────────────────


from desloppify.languages.python.detectors.import_linter_adapter import (  # noqa: E402
    detect_with_import_linter,
)


class TestImportLinterAdapter:
    def _write_config(self, tmp_path):
        (tmp_path / ".importlinter").write_text("[importlinter]\nroot_package=foo\n")

    def test_returns_none_when_lint_imports_not_installed(self, tmp_path):
        self._write_config(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError("lint-imports not found")):
            assert detect_with_import_linter(tmp_path) is None

    def test_returns_none_when_no_importlinter_config(self, tmp_path):
        # No .importlinter file anywhere in the path hierarchy (tmp_path has no .git)
        result = detect_with_import_linter(tmp_path)
        assert result is None

    def test_returns_empty_on_no_violations(self, tmp_path):
        self._write_config(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "All contracts ok.\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_import_linter(tmp_path)
        assert result == []

    def test_parses_single_violation(self, tmp_path):
        self._write_config(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = (
            "Broken contract 'Engine cannot import Languages':\n"
            "    foo.engine.detectors.coupling imports foo.languages.typescript\n"
        )
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_import_linter(tmp_path)
        assert result is not None
        assert len(result) == 1
        assert result[0]["confidence"] == "high"
        assert "foo.engine.detectors.coupling" in result[0]["summary"]
        assert "foo.languages.typescript" in result[0]["summary"]

    def test_parses_multiple_violations(self, tmp_path):
        self._write_config(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = (
            "Broken contract 'Engine cannot import Languages':\n"
            "    foo.engine.a imports foo.languages.b\n"
            "    foo.engine.c imports foo.languages.d\n"
        )
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = detect_with_import_linter(tmp_path)
        assert result is not None
        assert len(result) == 2
        assert result[0]["source_pkg"] == "a"
        assert result[1]["source_pkg"] == "c"

    def test_returns_none_on_timeout(self, tmp_path):
        self._write_config(tmp_path)
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("lint-imports", 60)
        ):
            assert detect_with_import_linter(tmp_path) is None


# ── collect_exclude_dirs ─────────────────────────────────────────────────────


from desloppify.core.source_discovery import collect_exclude_dirs  # noqa: E402


class TestCollectExcludeDirs:
    def test_returns_absolute_paths(self, tmp_path):
        with patch(
            "desloppify.core.source_discovery.get_exclusions", return_value=()
        ):
            result = collect_exclude_dirs(tmp_path)
        assert all(p.startswith(str(tmp_path)) for p in result)

    def test_includes_default_non_glob_entries(self, tmp_path):
        with patch(
            "desloppify.core.source_discovery.get_exclusions", return_value=()
        ):
            result = collect_exclude_dirs(tmp_path)
        basenames = {p.rsplit("/", 1)[-1] for p in result}
        assert "node_modules" in basenames
        assert "__pycache__" in basenames
        assert ".git" in basenames
        assert ".venv" in basenames
        assert "venv" in basenames

    def test_excludes_glob_patterns(self, tmp_path):
        with patch(
            "desloppify.core.source_discovery.get_exclusions", return_value=()
        ):
            result = collect_exclude_dirs(tmp_path)
        # *.egg-info and .venv* are glob patterns and should be excluded
        assert not any("*" in p for p in result)

    def test_includes_runtime_exclusions(self, tmp_path):
        with patch(
            "desloppify.core.source_discovery.get_exclusions",
            return_value=("vendor", "third_party"),
        ):
            result = collect_exclude_dirs(tmp_path)
        basenames = {p.rsplit("/", 1)[-1] for p in result}
        assert "vendor" in basenames
        assert "third_party" in basenames

    def test_skips_runtime_glob_exclusions(self, tmp_path):
        with patch(
            "desloppify.core.source_discovery.get_exclusions",
            return_value=("vendor/**",),
        ):
            result = collect_exclude_dirs(tmp_path)
        # glob pattern should not appear
        assert not any("vendor" in p for p in result)

    def test_deduplicates(self, tmp_path):
        """Runtime exclusion that overlaps with DEFAULT_EXCLUSIONS doesn't produce dupes."""
        with patch(
            "desloppify.core.source_discovery.get_exclusions",
            return_value=("node_modules",),
        ):
            result = collect_exclude_dirs(tmp_path)
        node_entries = [p for p in result if p.endswith("/node_modules")]
        assert len(node_entries) == 1


# ── Ruff --exclude integration ───────────────────────────────────────────────


from desloppify.languages.python.detectors.unused import detect_unused  # noqa: E402


class TestRuffSmellsExcludeFlag:
    """Verify ruff smells passes --exclude to subprocess."""

    def test_ruff_smells_passes_exclude_flag(self, tmp_path):
        captured_cmd = []

        def _capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            mock_result = MagicMock()
            mock_result.stdout = "[]"
            return mock_result

        fake_dirs = [str(tmp_path / ".venv"), str(tmp_path / "node_modules")]
        with patch("subprocess.run", side_effect=_capture_run), patch(
            "desloppify.languages.python.detectors.ruff_smells._collect_exclude_dirs",
            return_value=fake_dirs,
        ):
            detect_with_ruff_smells(tmp_path)

        assert "--exclude" in captured_cmd
        idx = captured_cmd.index("--exclude")
        exclude_value = captured_cmd[idx + 1]
        assert str(tmp_path / ".venv") in exclude_value
        assert str(tmp_path / "node_modules") in exclude_value

    def test_ruff_smells_no_exclude_when_empty(self, tmp_path):
        captured_cmd = []

        def _capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            mock_result = MagicMock()
            mock_result.stdout = "[]"
            return mock_result

        with patch("subprocess.run", side_effect=_capture_run), patch(
            "desloppify.languages.python.detectors.ruff_smells._collect_exclude_dirs",
            return_value=[],
        ):
            detect_with_ruff_smells(tmp_path)

        assert "--exclude" not in captured_cmd


class TestRuffUnusedExcludeFlag:
    """Verify ruff unused passes --exclude to subprocess."""

    def test_ruff_unused_passes_exclude_flag(self, tmp_path):
        captured_cmd = []

        def _capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            mock_result = MagicMock()
            mock_result.stdout = "[]"
            return mock_result

        fake_dirs = [str(tmp_path / ".venv"), str(tmp_path / "__pycache__")]
        with patch("subprocess.run", side_effect=_capture_run), patch(
            "desloppify.languages.python.detectors.unused._collect_exclude_dirs",
            return_value=fake_dirs,
        ), patch(
            "desloppify.languages.python.detectors.unused.find_py_files",
            return_value=[],
        ):
            detect_unused(tmp_path)

        assert "--exclude" in captured_cmd
        idx = captured_cmd.index("--exclude")
        exclude_value = captured_cmd[idx + 1]
        assert str(tmp_path / ".venv") in exclude_value
        assert str(tmp_path / "__pycache__") in exclude_value

    def test_ruff_unused_no_exclude_when_empty(self, tmp_path):
        captured_cmd = []

        def _capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            mock_result = MagicMock()
            mock_result.stdout = "[]"
            return mock_result

        with patch("subprocess.run", side_effect=_capture_run), patch(
            "desloppify.languages.python.detectors.unused._collect_exclude_dirs",
            return_value=[],
        ), patch(
            "desloppify.languages.python.detectors.unused.find_py_files",
            return_value=[],
        ):
            detect_unused(tmp_path)

        assert "--exclude" not in captured_cmd
