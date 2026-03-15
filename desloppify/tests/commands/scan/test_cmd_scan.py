"""Tests for desloppify.app.commands.scan — scan helper functions."""

from types import SimpleNamespace

import pytest

import desloppify.app.commands.scan.artifacts as scan_artifacts_mod
import desloppify.app.commands.scan.cmd as scan_cmd_mod
import desloppify.app.commands.scan.preflight as scan_preflight_mod
import desloppify.languages as lang_mod
from desloppify.app.commands.scan.helpers import (
    audit_excluded_dirs,
    collect_codebase_metrics,
    effective_include_slow,
    resolve_scan_profile,
    warn_explicit_lang_with_no_files,
    format_delta,
)
from desloppify.app.commands.scan.reporting.summary import (
    show_strict_target_progress,
)
from desloppify.app.commands.scan.cmd import (
    cmd_scan,
    show_diff_summary,
    show_score_delta,
)
from desloppify.base.exception_sets import CommandError

# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


class TestScanModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_scan_callable(self):
        assert callable(cmd_scan)

    def test_helper_functions_callable(self):
        assert callable(audit_excluded_dirs)
        assert callable(collect_codebase_metrics)
        assert callable(format_delta)
        assert callable(show_diff_summary)
        assert callable(warn_explicit_lang_with_no_files)


class TestCmdScanExecution:
    """cmd_scan should execute the scan workflow, not just helpers."""

    def test_cmd_scan_runs_pipeline_and_writes_query(self, monkeypatch):
        monkeypatch.setattr(scan_preflight_mod, "scan_queue_preflight", lambda _: None)
        args = SimpleNamespace(path=".")
        runtime = SimpleNamespace(
            lang_label=" (python)",
            reset_subjective_count=0,
            state={"dimension_scores": {}},
            config={},
            effective_include_slow=True,
            profile="full",
            lang=SimpleNamespace(name="python"),
        )
        merge = SimpleNamespace(
            diff={"new": 0, "auto_resolved": 0, "reopened": 0},
            prev_overall=None,
            prev_objective=None,
            prev_strict=None,
            prev_verified=None,
            prev_dim_scores={},
        )
        noise = SimpleNamespace(
            budget_warning=None,
            hidden_total=0,
            global_noise_budget=0,
            noise_budget=0,
            hidden_by_detector={},
        )
        captured = {"query": None, "llm_summary_called": False}

        monkeypatch.setattr(scan_cmd_mod, "prepare_scan_runtime", lambda _args: runtime)
        monkeypatch.setattr(
            scan_cmd_mod, "run_scan_generation", lambda _runtime: ([], {}, None)
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "merge_scan_results",
            lambda _runtime, _issues, _potentials, _metrics: merge,
        )
        monkeypatch.setattr(
            scan_cmd_mod, "resolve_noise_snapshot", lambda _state, _config: noise
        )
        monkeypatch.setattr(scan_cmd_mod, "show_diff_summary", lambda _diff: None)
        monkeypatch.setattr(
            scan_cmd_mod,
            "show_score_delta",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            scan_cmd_mod, "show_scorecard_subjective_measures", lambda _state: None
        )
        monkeypatch.setattr(
            scan_cmd_mod, "show_score_model_breakdown", lambda _state: None
        )
        monkeypatch.setattr(
            scan_cmd_mod, "target_strict_score_from_config", lambda _config, fallback=95.0: fallback
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "show_post_scan_analysis",
            lambda *_args, **_kwargs: ([], {"headline": None, "actions": []}),
        )
        monkeypatch.setattr(
            scan_cmd_mod, "persist_reminder_history", lambda _runtime, _narrative: None
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "build_scan_query_payload",
            lambda *_args, **_kwargs: {"command": "scan", "ok": True},
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "write_query",
            lambda payload, **_kwargs: captured.update(query=payload),
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "emit_scorecard_badge",
            lambda _args, _config, _state: (None, None),
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "print_llm_summary",
            lambda *_args, **_kwargs: captured.update(llm_summary_called=True),
        )

        cmd_scan(args)

        assert captured["query"] == {"command": "scan", "ok": True}
        assert captured["llm_summary_called"] is True

    def test_cmd_scan_prints_coverage_preflight_warning(self, monkeypatch, capsys):
        monkeypatch.setattr(scan_preflight_mod, "scan_queue_preflight", lambda _: None)
        args = SimpleNamespace(path=".")
        runtime = SimpleNamespace(
            lang_label=" (python)",
            reset_subjective_count=0,
            state={"dimension_scores": {}},
            config={},
            effective_include_slow=True,
            profile="full",
            lang=SimpleNamespace(name="python"),
            coverage_warnings=[
                {
                    "detector": "security",
                    "summary": "bandit is not installed.",
                    "impact": "Python-specific security checks are skipped.",
                    "remediation": "Install Bandit: pip install bandit",
                }
            ],
        )
        merge = SimpleNamespace(
            diff={"new": 0, "auto_resolved": 0, "reopened": 0},
            prev_overall=None,
            prev_objective=None,
            prev_strict=None,
            prev_verified=None,
            prev_dim_scores={},
        )
        noise = SimpleNamespace(
            budget_warning=None,
            hidden_total=0,
            global_noise_budget=0,
            noise_budget=0,
            hidden_by_detector={},
        )

        monkeypatch.setattr(scan_cmd_mod, "prepare_scan_runtime", lambda _args: runtime)
        monkeypatch.setattr(
            scan_cmd_mod, "run_scan_generation", lambda _runtime: ([], {}, None)
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "merge_scan_results",
            lambda _runtime, _issues, _potentials, _metrics: merge,
        )
        monkeypatch.setattr(
            scan_cmd_mod, "resolve_noise_snapshot", lambda _state, _config: noise
        )
        monkeypatch.setattr(scan_cmd_mod, "show_diff_summary", lambda _diff: None)
        monkeypatch.setattr(scan_cmd_mod, "show_score_delta", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(scan_cmd_mod, "show_scorecard_subjective_measures", lambda _state: None)
        monkeypatch.setattr(scan_cmd_mod, "show_score_model_breakdown", lambda _state: None)
        monkeypatch.setattr(
            scan_cmd_mod, "target_strict_score_from_config", lambda _config, fallback=95.0: fallback
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "show_post_scan_analysis",
            lambda *_args, **_kwargs: ([], {"headline": None, "actions": []}),
        )
        monkeypatch.setattr(scan_cmd_mod, "persist_reminder_history", lambda _runtime, _narrative: None)
        monkeypatch.setattr(
            scan_cmd_mod,
            "build_scan_query_payload",
            lambda *_args, **_kwargs: {"command": "scan", "ok": True},
        )
        monkeypatch.setattr(scan_cmd_mod, "write_query", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            scan_cmd_mod,
            "emit_scorecard_badge",
            lambda *_args, **_kwargs: (None, None),
        )
        monkeypatch.setattr(scan_cmd_mod, "print_llm_summary", lambda *_args, **_kwargs: None)

        cmd_scan(args)

        out = capsys.readouterr().out
        assert "Coverage preflight:" in out
        assert "Repercussion:" in out
        assert "Install Bandit" in out

    def test_cmd_scan_exits_on_state_contract_error(self, monkeypatch, capsys):
        monkeypatch.setattr(scan_preflight_mod, "scan_queue_preflight", lambda _: None)
        args = SimpleNamespace(path=".")
        monkeypatch.setattr(
            scan_cmd_mod,
            "prepare_scan_runtime",
            lambda _args: (_ for _ in ()).throw(
                scan_cmd_mod.ScanStateContractError("state.issues must be an object")
            ),
        )
        monkeypatch.setattr(scan_cmd_mod, "colorize", lambda text, _style: text)

        with pytest.raises(CommandError) as exc:
            cmd_scan(args)
        assert exc.value.exit_code == 2
        assert "state.issues must be an object" in str(exc.value)


class TestScorecardBadgeContract:
    def test_missing_scorecard_support_is_soft_skip_when_not_requested(self, monkeypatch):
        monkeypatch.setattr(
            scan_artifacts_mod,
            "_load_scorecard_helpers",
            lambda: (None, None),
        )
        args = SimpleNamespace(badge_path=None)
        _path, result = scan_artifacts_mod.emit_scorecard_badge(args, {}, {})
        assert result.ok is True
        assert result.status == "skipped"

    def test_missing_scorecard_support_is_error_when_explicitly_requested(self, monkeypatch):
        monkeypatch.setattr(
            scan_artifacts_mod,
            "_load_scorecard_helpers",
            lambda: (None, None),
        )
        args = SimpleNamespace(badge_path="badge.png")
        _path, result = scan_artifacts_mod.emit_scorecard_badge(args, {}, {})
        assert result.ok is False
        assert result.error_kind == "scorecard_dependency_missing"


# ---------------------------------------------------------------------------
# profile helpers
# ---------------------------------------------------------------------------


class TestScanProfiles:
    def test_csharp_defaults_to_objective(self):
        lang = SimpleNamespace(default_scan_profile="objective")
        assert resolve_scan_profile(None, lang) == "objective"

    def test_non_csharp_defaults_to_full(self):
        lang = SimpleNamespace(default_scan_profile="full")
        assert resolve_scan_profile(None, lang) == "full"

    def test_explicit_profile_wins(self):
        lang = SimpleNamespace(default_scan_profile="objective")
        assert resolve_scan_profile("ci", lang) == "ci"

    def test_ci_forces_slow_off(self):
        assert effective_include_slow(True, "ci") is False
        assert effective_include_slow(False, "ci") is False


# ---------------------------------------------------------------------------
# format_delta
# ---------------------------------------------------------------------------


class TestFormatDelta:
    """format_delta returns (delta_str, color) for score changes."""

    def test_positive_delta(self):
        delta_str, color = format_delta(80.0, 70.0)
        assert "+10.0" in delta_str
        assert color == "green"

    def test_negative_delta(self):
        delta_str, color = format_delta(60.0, 70.0)
        assert "-10.0" in delta_str
        assert color == "red"

    def test_zero_delta(self):
        delta_str, color = format_delta(70.0, 70.0)
        assert delta_str == ""
        assert color == "dim"

    def test_none_prev(self):
        """When prev is None, delta should be 0."""
        delta_str, color = format_delta(70.0, None)
        assert delta_str == ""
        assert color == "dim"

    def test_fractional_delta(self):
        delta_str, color = format_delta(70.5, 70.0)
        assert "+0.5" in delta_str
        assert color == "green"


# ---------------------------------------------------------------------------
# show_diff_summary
# ---------------------------------------------------------------------------


class TestShowDiffSummary:
    """show_diff_summary prints the one-liner scan diff."""

    def test_all_zeros(self, capsys):
        show_diff_summary({"new": 0, "auto_resolved": 0, "reopened": 0})
        out = capsys.readouterr().out
        assert "No changes" in out

    def test_new_issues(self, capsys):
        show_diff_summary({"new": 5, "auto_resolved": 0, "reopened": 0})
        out = capsys.readouterr().out
        assert "+5 new" in out

    def test_resolved_issues(self, capsys):
        show_diff_summary({"new": 0, "auto_resolved": 3, "reopened": 0})
        out = capsys.readouterr().out
        assert "-3 resolved" in out

    def test_reopened_issues(self, capsys):
        show_diff_summary({"new": 0, "auto_resolved": 0, "reopened": 2})
        out = capsys.readouterr().out
        assert "2 reopened" in out

    def test_combined(self, capsys):
        show_diff_summary({"new": 3, "auto_resolved": 2, "reopened": 1})
        out = capsys.readouterr().out
        assert "+3 new" in out
        assert "-2 resolved" in out
        assert "1 reopened" in out

    def test_suspect_detectors_warning(self, capsys):
        show_diff_summary(
            {
                "new": 0,
                "auto_resolved": 0,
                "reopened": 0,
                "suspect_detectors": ["unused", "logs"],
            }
        )
        out = capsys.readouterr().out
        assert "Skipped auto-resolve" in out
        assert "unused" in out


# ---------------------------------------------------------------------------
# show_score_delta
# ---------------------------------------------------------------------------

class TestShowScoreDelta:
    def test_marks_delta_non_comparable(self, capsys):
        state = {
            "stats": {"open": 3, "wontfix": 0, "total": 10},
            "overall_score": 90.0,
            "objective_score": 88.0,
            "strict_score": 87.0,
            "verified_strict_score": 86.0,
        }
        show_score_delta(
            state,
            prev_overall=80.0,
            prev_objective=78.0,
            prev_strict=77.0,
            non_comparable_reason="tool code changed (abc -> def)",
        )
        out = capsys.readouterr().out
        assert "Δ non-comparable" in out
        assert "tool code changed" in out


# ---------------------------------------------------------------------------
# show_strict_target_progress
# ---------------------------------------------------------------------------

class TestShowStrictTargetProgress:
    def test_below_default_target(self, capsys):
        target, gap = show_strict_target_progress(
            {"target": 95.0, "current": 90.0, "gap": 5.0, "state": "below"}
        )
        out = capsys.readouterr().out
        assert target == 95
        assert gap == 5.0
        assert "Strict target: 95.0/100" in out
        assert "below target" in out

    def test_above_custom_target(self, capsys):
        target, gap = show_strict_target_progress(
            {"target": 96.0, "current": 98.0, "gap": -2.0, "state": "above"}
        )
        out = capsys.readouterr().out
        assert target == 96
        assert gap == -2.0
        assert "Strict target: 96.0/100" in out
        assert "above target" in out

    def test_invalid_config_falls_back_to_default(self, capsys):
        target, gap = show_strict_target_progress(
            {
                "target": 95.0,
                "current": 94.0,
                "gap": 1.0,
                "state": "below",
                "warning": "Invalid config `target_strict_score='not-a-number'`; using 95",
            }
        )
        out = capsys.readouterr().out
        assert target == 95
        assert gap == 1.0
        assert "Invalid config `target_strict_score='not-a-number'`; using 95" in out
        assert "below target" in out

    def test_unavailable_strict_score(self, capsys):
        target, gap = show_strict_target_progress({"target": 95.0, "current": None, "gap": None, "state": "unavailable"})
        out = capsys.readouterr().out
        assert target == 95
        assert gap is None
        assert "current strict score unavailable" in out


# ---------------------------------------------------------------------------
# audit_excluded_dirs
# ---------------------------------------------------------------------------


class TestAuditExcludedDirs:
    """audit_excluded_dirs checks for stale --exclude directories."""

    def test_empty_exclusions(self):
        assert audit_excluded_dirs((), [], "/fake") == []

    def test_default_exclusions_skipped(self, tmp_path):
        """Directories in DEFAULT_EXCLUSIONS should be skipped."""
        (tmp_path / "node_modules").mkdir()
        result = audit_excluded_dirs(("node_modules",), [], tmp_path)
        assert result == []

    def test_nonexistent_dir_skipped(self, tmp_path):
        """If excluded dir does not exist, skip it."""
        result = audit_excluded_dirs(("nonexistent",), [], tmp_path)
        assert result == []

    def test_stale_dir_produces_issue(self, tmp_path):
        """A dir that exists but has no references should produce a issue."""
        stale_dir = tmp_path / "old_lib"
        stale_dir.mkdir()
        # Create a scanned file that does not reference 'old_lib'
        src = tmp_path / "main.py"
        src.write_text("print('hello')\n")

        result = audit_excluded_dirs(("old_lib",), [str(src)], tmp_path)
        assert len(result) == 1
        assert result[0]["detector"] == "stale_exclude"
        assert "old_lib" in result[0]["summary"]

    def test_referenced_dir_no_issue(self, tmp_path):
        """A dir that is referenced should NOT produce a issue."""
        ref_dir = tmp_path / "utils"
        ref_dir.mkdir()
        src = tmp_path / "main.py"
        src.write_text("from utils import helper\n")

        result = audit_excluded_dirs(("utils",), [str(src)], tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# collect_codebase_metrics
# ---------------------------------------------------------------------------


class TestCollectCodebaseMetrics:
    """collect_codebase_metrics computes LOC/file/dir counts."""

    def test_no_lang(self):
        assert collect_codebase_metrics(None, "/tmp") is None

    def test_no_file_finder(self):
        class FakeLang:
            file_finder = None

        assert collect_codebase_metrics(FakeLang(), "/tmp") is None

    def test_counts_files(self, tmp_path):
        # Create some test files
        (tmp_path / "a.py").write_text("line1\nline2\n")
        (tmp_path / "b.py").write_text("line1\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("x\ny\nz\n")

        class FakeLang:
            def file_finder(self, path):
                return [
                    str(tmp_path / "a.py"),
                    str(tmp_path / "b.py"),
                    str(tmp_path / "sub" / "c.py"),
                ]

        result = collect_codebase_metrics(FakeLang(), tmp_path)
        assert result is not None
        assert result["total_files"] == 3
        assert result["total_loc"] == 6  # 2 + 1 + 3
        assert result["total_directories"] == 2  # tmp_path and sub

    def test_uses_precomputed_file_list_when_provided(self, tmp_path):
        file_path = tmp_path / "a.py"
        file_path.write_text("line1\nline2\n")

        class FakeLang:
            def file_finder(self, _path):
                raise AssertionError("file_finder should not run when files are provided")

        result = collect_codebase_metrics(
            FakeLang(),
            tmp_path,
            files=[str(file_path)],
        )
        assert result is not None
        assert result["total_files"] == 1
        assert result["total_loc"] == 2


# ---------------------------------------------------------------------------
# warn_explicit_lang_with_no_files
# ---------------------------------------------------------------------------


class TestWarnExplicitLangWithNoFiles:
    def test_warns_for_explicit_lang_when_zero_files(
        self, monkeypatch, capsys, tmp_path
    ):
        class FakeArgs:
            lang = "typescript"

        class FakeLang:
            name = "typescript"

        monkeypatch.setattr(lang_mod, "auto_detect_lang", lambda _root: "python")

        warn_explicit_lang_with_no_files(
            FakeArgs(), FakeLang(), tmp_path, {"total_files": 0}
        )
        out = capsys.readouterr().out
        assert "No typescript source files found" in out
        assert "Omit `--lang` to auto-detect." in out

    def test_no_warning_when_not_explicit(self, capsys, tmp_path):
        class FakeArgs:
            lang = None

        class FakeLang:
            name = "typescript"

        warn_explicit_lang_with_no_files(
            FakeArgs(), FakeLang(), tmp_path, {"total_files": 0}
        )
        assert capsys.readouterr().out == ""

    def test_no_warning_when_files_present(self, capsys, tmp_path):
        class FakeArgs:
            lang = "typescript"

        class FakeLang:
            name = "typescript"

        warn_explicit_lang_with_no_files(
            FakeArgs(), FakeLang(), tmp_path, {"total_files": 5}
        )
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# show_post_scan_analysis
# ---------------------------------------------------------------------------

