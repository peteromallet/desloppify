"""Tests for desloppify.app.commands.scan — scan helper functions."""

from types import SimpleNamespace

import pytest

import desloppify.app.commands.scan.scan as scan_cmd_mod
import desloppify.intelligence.narrative as narrative_mod
import desloppify.languages as lang_mod
from desloppify.app.commands.scan.scan import (
    _audit_excluded_dirs,
    _collect_codebase_metrics,
    _effective_include_slow,
    _format_delta,
    _resolve_scan_profile,
    _show_diff_summary,
    _show_dimension_deltas,
    _show_post_scan_analysis,
    _show_score_delta,
    _show_strict_target_progress,
    _warn_explicit_lang_with_no_files,
    cmd_scan,
)
from desloppify.scoring import DIMENSIONS

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


class TestCmdScanExecution:
    """cmd_scan should execute the scan workflow, not just helpers."""

    def test_cmd_scan_runs_pipeline_and_writes_query(self, monkeypatch):
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
            lambda _runtime, _findings, _potentials, _metrics: merge,
        )
        monkeypatch.setattr(
            scan_cmd_mod, "resolve_noise_snapshot", lambda _state, _config: noise
        )
        monkeypatch.setattr(scan_cmd_mod, "_show_diff_summary", lambda _diff: None)
        monkeypatch.setattr(
            scan_cmd_mod,
            "_show_score_delta",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            scan_cmd_mod, "_show_scorecard_subjective_measures", lambda _state: None
        )
        monkeypatch.setattr(
            scan_cmd_mod, "_show_score_model_breakdown", lambda _state: None
        )
        monkeypatch.setattr(
            scan_cmd_mod, "target_strict_score_from_config", lambda _config, fallback=95.0: fallback
        )
        monkeypatch.setattr(
            scan_cmd_mod, "_show_score_integrity", lambda _state, _diff: None
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "_show_post_scan_analysis",
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
            scan_cmd_mod, "emit_scorecard_badge", lambda _args, _config, _state: None
        )
        monkeypatch.setattr(
            scan_cmd_mod,
            "_print_llm_summary",
            lambda *_args, **_kwargs: captured.update(llm_summary_called=True),
        )

        cmd_scan(args)

        assert captured["query"] == {"command": "scan", "ok": True}
        assert captured["llm_summary_called"] is True


# ---------------------------------------------------------------------------
# profile helpers
# ---------------------------------------------------------------------------


class TestScanProfiles:
    def test_csharp_defaults_to_objective(self):
        lang = SimpleNamespace(default_scan_profile="objective")
        assert _resolve_scan_profile(None, lang) == "objective"

    def test_non_csharp_defaults_to_full(self):
        lang = SimpleNamespace(default_scan_profile="full")
        assert _resolve_scan_profile(None, lang) == "full"

    def test_explicit_profile_wins(self):
        lang = SimpleNamespace(default_scan_profile="objective")
        assert _resolve_scan_profile("ci", lang) == "ci"

    def test_ci_forces_slow_off(self):
        assert _effective_include_slow(True, "ci") is False
        assert _effective_include_slow(False, "ci") is False


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
        _show_diff_summary(
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
# _show_score_delta
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
        _show_score_delta(
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
# _show_strict_target_progress
# ---------------------------------------------------------------------------

class TestShowStrictTargetProgress:
    def test_below_default_target(self, capsys):
        target, gap = _show_strict_target_progress(
            {"target": 95.0, "current": 90.0, "gap": 5.0, "state": "below"}
        )
        out = capsys.readouterr().out
        assert target == 95
        assert gap == 5.0
        assert "Strict target: 95.0/100" in out
        assert "below target" in out

    def test_above_custom_target(self, capsys):
        target, gap = _show_strict_target_progress(
            {"target": 96.0, "current": 98.0, "gap": -2.0, "state": "above"}
        )
        out = capsys.readouterr().out
        assert target == 96
        assert gap == -2.0
        assert "Strict target: 96.0/100" in out
        assert "above target" in out

    def test_invalid_config_falls_back_to_default(self, capsys):
        target, gap = _show_strict_target_progress(
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
        target, gap = _show_strict_target_progress({"target": 95.0, "current": None, "gap": None, "state": "unavailable"})
        out = capsys.readouterr().out
        assert target == 95
        assert gap is None
        assert "current strict score unavailable" in out


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
                return [
                    str(tmp_path / "a.py"),
                    str(tmp_path / "b.py"),
                    str(tmp_path / "sub" / "c.py"),
                ]

        result = _collect_codebase_metrics(FakeLang(), tmp_path)
        assert result is not None
        assert result["total_files"] == 3
        assert result["total_loc"] == 6  # 2 + 1 + 3
        assert result["total_directories"] == 2  # tmp_path and sub


# ---------------------------------------------------------------------------
# _warn_explicit_lang_with_no_files
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
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": None, "actions": []},
        )

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 10, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        warnings, narrative = _show_post_scan_analysis(diff, state, FakeLang())
        assert len(warnings) >= 1
        assert any("reopened" in w.lower() for w in warnings)

    def test_cascade_warning(self, monkeypatch, capsys):
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": None, "actions": []},
        )

        class FakeLang:
            name = "python"

        diff = {"new": 15, "auto_resolved": 1, "reopened": 0, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        warnings, _ = _show_post_scan_analysis(diff, state, FakeLang())
        assert any("cascading" in w.lower() for w in warnings)

    def test_chronic_reopeners_warning(self, monkeypatch, capsys):
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": None, "actions": []},
        )

        class FakeLang:
            name = "python"

        diff = {
            "new": 0,
            "auto_resolved": 0,
            "reopened": 0,
            "chronic_reopeners": ["f1", "f2", "f3"],
        }
        state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        warnings, _ = _show_post_scan_analysis(diff, state, FakeLang())
        assert any("chronic" in w.lower() for w in warnings)

    def test_no_warnings_clean_scan(self, monkeypatch, capsys):
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": "All good", "actions": []},
        )

        class FakeLang:
            name = "python"

        diff = {"new": 2, "auto_resolved": 5, "reopened": 0, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 90,
            "objective_score": 90,
            "strict_score": 90,
        }
        warnings, narrative = _show_post_scan_analysis(diff, state, FakeLang())
        assert warnings == []

    def test_shows_top_action(self, monkeypatch, capsys):
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": "Test",
                "actions": [
                    {
                        "command": "desloppify fix unused-imports",
                        "description": "remove dead imports",
                    }
                ],
            },
        )

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "desloppify fix unused-imports" in out

    def test_subjective_run_nudge_when_score_below_90_without_prior_review(self, monkeypatch, capsys):
        import desloppify.intelligence.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
            "dimension_scores": {
                "Naming Quality": {
                    "score": 88.0,
                    "strict": 88.0,
                    "detectors": {"subjective_assessment": {"issues": 2}},
                },
            },
        }
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "Subjective scores below 90" in out
        assert "You can run the subjective scoring with `desloppify review --prepare`" in out
        assert "`desloppify status`" in out
        assert "`desloppify issues`" in out

    def test_subjective_rerun_nudge_when_score_below_90_with_prior_review(self, monkeypatch, capsys):
        import desloppify.intelligence.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
            "review_cache": {"files": {"src/a.py": {"reviewed_at": "2026-01-01T00:00:00+00:00"}}},
            "dimension_scores": {
                "Naming Quality": {
                    "score": 88.0,
                    "strict": 88.0,
                    "detectors": {"subjective_assessment": {"issues": 2}},
                },
            },
        }
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "You can rerun the subjective scoring with `desloppify review --prepare`" in out

    def test_no_subjective_rerun_nudge_when_scores_high(self, monkeypatch, capsys):
        import desloppify.intelligence.narrative as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {
            "findings": {},
            "overall_score": 95,
            "objective_score": 95,
            "strict_score": 95,
            "dimension_scores": {
                "Naming Quality": {
                    "score": 95.0,
                    "strict": 95.0,
                    "detectors": {"subjective_assessment": {"issues": 0}},
                },
            },
        }
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "You can rerun the subjective scoring with `desloppify review --prepare`" not in out

    def test_shows_filtered_narrative_reminders(self, monkeypatch, capsys):
        import desloppify.intelligence.narrative as narrative_mod
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": None,
                "actions": [],
                "reminders": [
                    {"type": "report_scores", "message": "skip this"},
                    {"type": "review_stale", "message": "Design review is stale — run review prepare"},
                    {"type": "ignore_suppression_high", "message": "Ignore suppression is high"},
                ],
            },
        )

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {"findings": {}, "overall_score": 90, "objective_score": 90, "strict_score": 90}
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "Reminders:" in out
        assert "Design review is stale" in out
        assert "Ignore suppression is high" in out
        assert "skip this" not in out

    def test_shows_narrative_plan_fields_when_available(self, monkeypatch, capsys):
        import desloppify.intelligence.narrative as narrative_mod
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": None,
                "actions": [],
                "why_now": "Security work should come first.",
                "primary_action": {"command": "desloppify show security --status open", "description": "review open security findings"},
                "verification_step": {"command": "desloppify scan", "reason": "revalidate after changes"},
                "risk_flags": [{"severity": "high", "message": "40% findings hidden by ignore patterns"}],
                "reminders": [],
            },
        )

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {"findings": {}, "overall_score": 90, "objective_score": 90, "strict_score": 90}
        _show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "Narrative Plan:" in out
        assert "Why now: Security work should come first." in out
        assert "Verify: `desloppify scan`" in out


# ---------------------------------------------------------------------------
# _show_dimension_deltas
# ---------------------------------------------------------------------------


class TestShowDimensionDeltas:
    """_show_dimension_deltas shows which dimensions changed."""

    def test_no_change_no_output(self, monkeypatch, capsys):
        # Need DIMENSIONS to exist
        prev = {d.name: {"score": 95.0, "strict": 90.0} for d in DIMENSIONS}
        current = {d.name: {"score": 95.0, "strict": 90.0} for d in DIMENSIONS}
        _show_dimension_deltas(prev, current)
        out = capsys.readouterr().out
        assert "Moved:" not in out

    def test_shows_changed_dimensions(self, monkeypatch, capsys):
        if not DIMENSIONS:
            pytest.skip("No dimensions defined")
        dim_name = DIMENSIONS[0].name
        prev = {dim_name: {"score": 90.0, "strict": 85.0}}
        current = {dim_name: {"score": 95.0, "strict": 90.0}}
        _show_dimension_deltas(prev, current)
        out = capsys.readouterr().out
        assert "Moved:" in out
        assert dim_name in out
