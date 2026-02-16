"""Tests for desloppify.commands.scan — scan helper functions."""

import pytest

from desloppify.commands.scan import (
    _audit_excluded_dirs,
    _collect_codebase_metrics,
    _format_delta,
    _show_diff_summary,
    _show_post_scan_analysis,
    _show_dimension_deltas,
    _show_detector_progress,
    _warn_explicit_lang_with_no_files,
    cmd_scan,
)


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestScanModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_scan_callable(self):
        assert callable(cmd_scan)

    def test_helper_functions_callable(self):
        assert callable(_audit_excluded_dirs)
        assert callable(_collect_codebase_metrics)
        assert callable(_format_delta)
        assert callable(_show_diff_summary)
        assert callable(_warn_explicit_lang_with_no_files)


# ---------------------------------------------------------------------------
# _format_delta
# ---------------------------------------------------------------------------

class TestFormatDelta:
    """_format_delta returns (delta_str, color) for score changes."""

    def test_positive_delta(self):
        delta_str, color = _format_delta(80.0, 70.0)
        assert "+10.0" in delta_str
        assert color == "green"

    def test_negative_delta(self):
        delta_str, color = _format_delta(60.0, 70.0)
        assert "-10.0" in delta_str
        assert color == "red"

    def test_zero_delta(self):
        delta_str, color = _format_delta(70.0, 70.0)
        assert delta_str == ""
        assert color == "dim"

    def test_none_prev(self):
        """When prev is None, delta should be 0."""
        delta_str, color = _format_delta(70.0, None)
        assert delta_str == ""
        assert color == "dim"

    def test_fractional_delta(self):
        delta_str, color = _format_delta(70.5, 70.0)
        assert "+0.5" in delta_str
        assert color == "green"


# ---------------------------------------------------------------------------
# _show_diff_summary
# ---------------------------------------------------------------------------

class TestShowDiffSummary:
    """_show_diff_summary prints the one-liner scan diff."""

    def test_all_zeros(self, capsys):
        _show_diff_summary({"new": 0, "auto_resolved": 0, "reopened": 0})
        out = capsys.readouterr().out
        assert "No changes" in out

    def test_new_findings(self, capsys):
        _show_diff_summary({"new": 5, "auto_resolved": 0, "reopened": 0})
        out = capsys.readouterr().out
        assert "+5 new" in out

    def test_resolved_findings(self, capsys):
        _show_diff_summary({"new": 0, "auto_resolved": 3, "reopened": 0})
        out = capsys.readouterr().out
        assert "-3 resolved" in out

    def test_reopened_findings(self, capsys):
        _show_diff_summary({"new": 0, "auto_resolved": 0, "reopened": 2})
        out = capsys.readouterr().out
        assert "2 reopened" in out

    def test_combined(self, capsys):
        _show_diff_summary({"new": 3, "auto_resolved": 2, "reopened": 1})
        out = capsys.readouterr().out
        assert "+3 new" in out
        assert "-2 resolved" in out
        assert "1 reopened" in out

    def test_suspect_detectors_warning(self, capsys):
        _show_diff_summary({
            "new": 0, "auto_resolved": 0, "reopened": 0,
            "suspect_detectors": ["unused", "logs"],
        })
        out = capsys.readouterr().out
        assert "Skipped auto-resolve" in out
        assert "unused" in out


# ---------------------------------------------------------------------------
# _audit_excluded_dirs
# ---------------------------------------------------------------------------

class TestAuditExcludedDirs:
    """_audit_excluded_dirs checks for stale --exclude directories."""

    def test_empty_exclusions(self):
        assert _audit_excluded_dirs((), [], "/fake") == []

    def test_default_exclusions_skipped(self, tmp_path):
        """Directories in DEFAULT_EXCLUSIONS should be skipped."""
        (tmp_path / "node_modules").mkdir()
        result = _audit_excluded_dirs(("node_modules",), [], tmp_path)
        assert result == []

    def test_nonexistent_dir_skipped(self, tmp_path):
        """If excluded dir does not exist, skip it."""
        result = _audit_excluded_dirs(("nonexistent",), [], tmp_path)
        assert result == []

    def test_stale_dir_produces_finding(self, tmp_path):
        """A dir that exists but has no references should produce a finding."""
        stale_dir = tmp_path / "old_lib"
        stale_dir.mkdir()
        # Create a scanned file that does not reference 'old_lib'
        src = tmp_path / "main.py"
        src.write_text("print('hello')\n")

        result = _audit_excluded_dirs(("old_lib",), [str(src)], tmp_path)
        assert len(result) == 1
        assert result[0]["detector"] == "stale_exclude"
        assert "old_lib" in result[0]["summary"]

    def test_referenced_dir_no_finding(self, tmp_path):
        """A dir that is referenced should NOT produce a finding."""
        ref_dir = tmp_path / "utils"
        ref_dir.mkdir()
        src = tmp_path / "main.py"
        src.write_text("from utils import helper\n")

        result = _audit_excluded_dirs(("utils",), [str(src)], tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# _collect_codebase_metrics
# ---------------------------------------------------------------------------

class TestCollectCodebaseMetrics:
    """_collect_codebase_metrics computes LOC/file/dir counts."""

    def test_no_lang(self):
        assert _collect_codebase_metrics(None, "/tmp") is None

    def test_no_file_finder(self):
        class FakeLang:
            file_finder = None
        assert _collect_codebase_metrics(FakeLang(), "/tmp") is None

    def test_counts_files(self, tmp_path):
        # Create some test files
        (tmp_path / "a.py").write_text("line1\nline2\n")
        (tmp_path / "b.py").write_text("line1\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("x\ny\nz\n")

        class FakeLang:
            def file_finder(self, path):
                return [str(tmp_path / "a.py"),
                        str(tmp_path / "b.py"),
                        str(tmp_path / "sub" / "c.py")]

        result = _collect_codebase_metrics(FakeLang(), tmp_path)
        assert result is not None
        assert result["total_files"] == 3
        assert result["total_loc"] == 6  # 2 + 1 + 3
        assert result["total_directories"] == 2  # tmp_path and sub


# ---------------------------------------------------------------------------
# _warn_explicit_lang_with_no_files
# ---------------------------------------------------------------------------

class TestWarnExplicitLangWithNoFiles:
    def test_warns_for_explicit_lang_when_zero_files(self, monkeypatch, capsys, tmp_path):
        class FakeArgs:
            lang = "typescript"

        class FakeLang:
            name = "typescript"

        import desloppify.lang as lang_mod
        monkeypatch.setattr(lang_mod, "auto_detect_lang", lambda _root: "python")

        _warn_explicit_lang_with_no_files(
            FakeArgs(), FakeLang(), tmp_path, {"total_files": 0}
        )
        out = capsys.readouterr().out
        assert "No typescript source files found" in out
        assert "--lang python" in out

    def test_no_warning_when_not_explicit(self, capsys, tmp_path):
        class FakeArgs:
            lang = None

        class FakeLang:
            name = "typescript"

        _warn_explicit_lang_with_no_files(
            FakeArgs(), FakeLang(), tmp_path, {"total_files": 0}
        )
        assert capsys.readouterr().out == ""

    def test_no_warning_when_files_present(self, capsys, tmp_path):
        class FakeArgs:
            lang = "typescript"

        class FakeLang:
            name = "typescript"

        _warn_explicit_lang_with_no_files(
            FakeArgs(), FakeLang(), tmp_path, {"total_files": 5}
        )
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _show_post_scan_analysis
# ---------------------------------------------------------------------------

class TestShowPostScanAnalysis:
    """_show_post_scan_analysis prints warnings and narrative."""

    def test_reopened_warning(self, monkeypatch, capsys):
        import desloppify.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 10, "chronic_reopeners": []}
        state = {"findings": {}, "score": 50}
        warnings, narrative = _show_post_scan_analysis(diff, state, FakeLang())
        assert len(warnings) >= 1
        assert any("reopened" in w.lower() for w in warnings)

    def test_cascade_warning(self, monkeypatch, capsys):
        import desloppify.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 15, "auto_resolved": 1, "reopened": 0, "chronic_reopeners": []}
        state = {"findings": {}, "score": 50}
        warnings, _ = _show_post_scan_analysis(diff, state, FakeLang())
        assert any("cascading" in w.lower() for w in warnings)

    def test_chronic_reopeners_warning(self, monkeypatch, capsys):
        import desloppify.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0,
                "chronic_reopeners": ["f1", "f2", "f3"]}
        state = {"findings": {}, "score": 50}
        warnings, _ = _show_post_scan_analysis(diff, state, FakeLang())
        assert any("chronic" in w.lower() for w in warnings)

    def test_no_warnings_clean_scan(self, monkeypatch, capsys):
        import desloppify.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": "All good", "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 2, "auto_resolved": 5, "reopened": 0, "chronic_reopeners": []}
        state = {"findings": {}, "score": 90}
        warnings, narrative = _show_post_scan_analysis(diff, state, FakeLang())
        assert warnings == []

    def test_shows_top_action(self, monkeypatch, capsys):
        import desloppify.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {
                                "headline": "Test",
                                "actions": [{"command": "desloppify fix unused-imports",
                                             "description": "remove dead imports"}],
                            })

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {"findings": {}, "score": 50}
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "desloppify fix unused-imports" in out


# ---------------------------------------------------------------------------
# _show_dimension_deltas
# ---------------------------------------------------------------------------

class TestShowDimensionDeltas:
    """_show_dimension_deltas shows which dimensions changed."""

    def test_no_change_no_output(self, monkeypatch, capsys):
        # Need DIMENSIONS to exist
        from desloppify.scoring import DIMENSIONS
        prev = {d.name: {"score": 95.0, "strict": 90.0} for d in DIMENSIONS}
        current = {d.name: {"score": 95.0, "strict": 90.0} for d in DIMENSIONS}
        _show_dimension_deltas(prev, current)
        out = capsys.readouterr().out
        assert "Moved:" not in out

    def test_shows_changed_dimensions(self, monkeypatch, capsys):
        from desloppify.scoring import DIMENSIONS
        if not DIMENSIONS:
            pytest.skip("No dimensions defined")
        dim_name = DIMENSIONS[0].name
        prev = {dim_name: {"score": 90.0, "strict": 85.0}}
        current = {dim_name: {"score": 95.0, "strict": 90.0}}
        _show_dimension_deltas(prev, current)
        out = capsys.readouterr().out
        assert "Moved:" in out
        assert dim_name in out
