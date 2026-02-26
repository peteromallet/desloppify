"""Direct unit tests for modules that were previously only transitively tested.

Tests cover:
  1. desloppify.app.commands.resolve.render
  2. desloppify.app.commands.status_parts.strict_target
  3. desloppify.app.commands._show_terminal
  4. desloppify.app.commands.viz_cmd
  5. desloppify.app.commands.review.entrypoint
  6. desloppify.app.commands.update_skill
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

# ── 1. resolve/render.py ────────────────────────────────────────────────────
from desloppify.app.commands.resolve.render import (
    _delta_suffix,
    _print_next_command,
    _print_resolve_summary,
    _print_score_movement,
    _print_subjective_reset_hint,
    _print_wontfix_batch_warning,
)


class TestDeltaSuffix:
    def test_small_positive_returns_empty(self):
        assert _delta_suffix(0.04) == ""

    def test_small_negative_returns_empty(self):
        assert _delta_suffix(-0.04) == ""

    def test_zero_returns_empty(self):
        assert _delta_suffix(0.0) == ""

    def test_positive_delta(self):
        assert _delta_suffix(1.5) == " (+1.5)"

    def test_negative_delta(self):
        assert _delta_suffix(-2.3) == " (-2.3)"

    def test_boundary_positive(self):
        assert _delta_suffix(0.05) == " (+0.1)"

    def test_boundary_negative(self):
        assert _delta_suffix(-0.05) == " (-0.1)"

    def test_large_positive(self):
        assert _delta_suffix(10.0) == " (+10.0)"


class TestPrintResolveSummary:
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_basic_summary(self, _mock_colorize, capsys):
        _print_resolve_summary(status="fixed", all_resolved=["f1", "f2"])
        out = capsys.readouterr().out
        assert "Resolved 2 finding(s) as fixed:" in out
        assert "f1" in out
        assert "f2" in out

    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_truncation_over_20(self, _mock_colorize, capsys):
        ids = [f"finding-{i}" for i in range(25)]
        _print_resolve_summary(status="wontfix", all_resolved=ids)
        out = capsys.readouterr().out
        assert "... and 5 more" in out
        # The 21st item should NOT be individually listed
        assert "finding-20" not in out


class TestPrintWontfixBatchWarning:
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_no_warning_for_non_wontfix(self, _mock_colorize, capsys):
        _print_wontfix_batch_warning(
            {"findings": {}}, status="fixed", resolved_count=20
        )
        assert capsys.readouterr().out == ""

    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_no_warning_when_count_low(self, _mock_colorize, capsys):
        _print_wontfix_batch_warning(
            {"findings": {}}, status="wontfix", resolved_count=5
        )
        assert capsys.readouterr().out == ""

    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_warning_shown_for_large_wontfix_batch(self, _mock_colorize, capsys):
        findings = {
            f"f{i}": {"status": "wontfix"} for i in range(15)
        }
        findings["open1"] = {"status": "open"}
        state = {"findings": findings}
        _print_wontfix_batch_warning(state, status="wontfix", resolved_count=15)
        out = capsys.readouterr().out
        assert "Wontfix debt" in out
        assert "15 findings" in out


class TestPrintScoreMovement:
    @patch("desloppify.app.commands.resolve.render.state_mod")
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_scores_unavailable(self, _mock_colorize, mock_state, capsys):
        from desloppify.state import ScoreSnapshot
        mock_state.score_snapshot.return_value = ScoreSnapshot(
            overall=None, objective=None, strict=None, verified=None
        )
        _print_score_movement(
            status="fixed",
            prev_overall=50.0,
            prev_objective=60.0,
            prev_strict=40.0,
            prev_verified=30.0,
            state={},
        )
        out = capsys.readouterr().out
        assert "Scores unavailable" in out

    @patch("desloppify.app.commands.resolve.render.state_mod")
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_scores_with_deltas(self, _mock_colorize, mock_state, capsys):
        from desloppify.state import ScoreSnapshot
        mock_state.score_snapshot.return_value = ScoreSnapshot(
            overall=55.0, objective=65.0, strict=45.0, verified=35.0
        )
        _print_score_movement(
            status="fixed",
            prev_overall=50.0,
            prev_objective=60.0,
            prev_strict=40.0,
            prev_verified=30.0,
            state={},
        )
        out = capsys.readouterr().out
        assert "55.0/100" in out
        assert "(+5.0)" in out

    @patch("desloppify.app.commands.resolve.render.state_mod")
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_review_findings_unchanged_hint(self, _mock_colorize, mock_state, capsys):
        from desloppify.state import ScoreSnapshot
        mock_state.score_snapshot.return_value = ScoreSnapshot(
            overall=50.0, objective=60.0, strict=40.0, verified=30.0
        )
        _print_score_movement(
            status="fixed",
            prev_overall=50.0,
            prev_objective=60.0,
            prev_strict=40.0,
            prev_verified=30.0,
            state={},
            has_review_findings=True,
        )
        out = capsys.readouterr().out
        assert "Scores unchanged" in out
        assert "review findings" in out

    @patch("desloppify.app.commands.resolve.render.state_mod")
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_fixed_status_verified_hint(self, _mock_colorize, mock_state, capsys):
        from desloppify.state import ScoreSnapshot
        mock_state.score_snapshot.return_value = ScoreSnapshot(
            overall=55.0, objective=65.0, strict=45.0, verified=35.0
        )
        _print_score_movement(
            status="fixed",
            prev_overall=50.0,
            prev_objective=60.0,
            prev_strict=40.0,
            prev_verified=30.0,
            state={},
        )
        out = capsys.readouterr().out
        assert "Verified score updates after a scan" in out


class TestPrintNextCommand:
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_no_review_remaining(self, _mock_colorize, capsys):
        state = {"findings": {"f1": {"status": "open", "detector": "smells"}}}
        result = _print_next_command(state)
        out = capsys.readouterr().out
        assert "desloppify scan" in out
        assert result == "desloppify scan"

    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_review_remaining(self, _mock_colorize, capsys):
        state = {
            "findings": {
                "f1": {"status": "open", "detector": "review"},
                "f2": {"status": "open", "detector": "review"},
            }
        }
        result = _print_next_command(state)
        out = capsys.readouterr().out
        assert "2 review findings remaining" in out
        assert result == "desloppify issues"

    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_single_review_remaining_no_plural(self, _mock_colorize, capsys):
        state = {
            "findings": {"f1": {"status": "open", "detector": "review"}}
        }
        _print_next_command(state)
        out = capsys.readouterr().out
        assert "1 review finding remaining" in out


class TestPrintSubjectiveResetHint:
    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_no_hint_when_no_review_findings(self, _mock_colorize, capsys):
        state = {
            "findings": {"f1": {"detector": "smells", "status": "open"}},
            "subjective_assessments": {"Code quality": 5.0},
        }
        args = argparse.Namespace()
        _print_subjective_reset_hint(
            args=args, state=state, all_resolved=["f1"], prev_subjective_scores={}
        )
        assert capsys.readouterr().out == ""

    @patch("desloppify.app.commands.resolve.render.colorize", side_effect=lambda t, _c: t)
    def test_hint_shown_for_resolved_review_findings(self, _mock_colorize, capsys):
        state = {
            "findings": {
                "f1": {
                    "detector": "review",
                    "status": "fixed",
                    "detail": {"dimension": "Code quality"},
                },
            },
            "subjective_assessments": {"Code quality": 5.0},
        }
        args = argparse.Namespace()
        _print_subjective_reset_hint(
            args=args, state=state, all_resolved=["f1"], prev_subjective_scores={}
        )
        out = capsys.readouterr().out
        assert "Subjective scores unchanged" in out
        assert "Code quality" in out


# ── 2. status_parts/strict_target.py ────────────────────────────────────────

from desloppify.app.commands.status_parts.strict_target import (  # noqa: E402
    format_strict_target_progress,
)


class TestFormatStrictTargetProgress:
    def test_none_input(self):
        lines, target, gap = format_strict_target_progress(None)
        assert lines == []
        assert target is None
        assert gap is None

    def test_non_dict_input(self):
        lines, target, gap = format_strict_target_progress("not a dict")
        assert lines == []
        assert target is None
        assert gap is None

    def test_warning_only(self):
        lines, target, gap = format_strict_target_progress(
            {"warning": "Low data confidence"}
        )
        assert len(lines) == 1
        assert "Low data confidence" in lines[0][0]
        assert lines[0][1] == "yellow"
        assert target is None

    def test_target_without_current(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80.0}
        )
        assert target == 80.0
        assert gap is None
        assert any("unavailable" in line for line, _ in lines)

    def test_below_target(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80.0, "current": 70.0, "gap": 10.0, "state": "below"}
        )
        assert target == 80.0
        assert gap == 10.0
        assert any("below target" in line for line, _ in lines)
        assert any(color == "yellow" for _, color in lines)

    def test_above_target(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80.0, "current": 90.0, "gap": -10.0, "state": "above"}
        )
        assert target == 80.0
        assert gap == -10.0
        assert any("above target" in line for line, _ in lines)
        assert any(color == "green" for _, color in lines)

    def test_on_target(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80.0, "current": 80.0, "gap": 0.0, "state": "on"}
        )
        assert target == 80.0
        assert gap == 0.0
        assert any("on target" in line for line, _ in lines)

    def test_gap_computed_when_missing(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80.0, "current": 70.0, "state": "below"}
        )
        assert gap == 10.0

    def test_warning_plus_below(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80.0, "current": 70.0, "gap": 10.0, "state": "below", "warning": "Low confidence"}
        )
        assert len(lines) == 2
        assert "Low confidence" in lines[0][0]
        assert "below target" in lines[1][0]

    def test_integer_target(self):
        lines, target, gap = format_strict_target_progress(
            {"target": 80, "current": 75, "gap": 5, "state": "below"}
        )
        assert target == 80.0
        assert isinstance(target, float)


# ── 3. _show_terminal.py ────────────────────────────────────────────────────

from desloppify.app.commands._show_terminal import (  # noqa: E402
    _print_fix_file_sample,
    show_fix_dry_run_samples,
)


class TestShowFixDryRunSamples:
    @patch("desloppify.app.commands._show_terminal.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands._show_terminal._print_fix_file_sample")
    def test_calls_print_for_each_sampled_result(self, mock_print_sample, _mock_colorize, capsys):
        results = [
            {"file": f"f{i}.py", "removed": [f"name{i}"]}
            for i in range(3)
        ]
        entries = []
        show_fix_dry_run_samples(entries, results)
        assert mock_print_sample.call_count == 3

    @patch("desloppify.app.commands._show_terminal.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands._show_terminal._print_fix_file_sample")
    def test_caps_at_5_samples(self, mock_print_sample, _mock_colorize, capsys):
        results = [
            {"file": f"f{i}.py", "removed": [f"name{i}"]}
            for i in range(10)
        ]
        show_fix_dry_run_samples([], results)
        assert mock_print_sample.call_count == 5

    @patch("desloppify.app.commands._show_terminal.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands._show_terminal._print_fix_file_sample")
    def test_skip_note_when_entries_exceed_removed(self, mock_print_sample, _mock_colorize, capsys):
        entries = [{"file": "a.py", "name": "x"}, {"file": "b.py", "name": "y"}]
        results = [{"file": "a.py", "removed": ["x"]}]  # 1 removed, 2 entries
        show_fix_dry_run_samples(entries, results)
        out = capsys.readouterr().out
        assert "1 of 2 entries were skipped" in out


class TestPrintFixFileSample:
    @patch("desloppify.app.commands._show_terminal.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands._show_terminal.rel", side_effect=lambda p: p)
    def test_shows_context_lines(self, _mock_rel, _mock_colorize, capsys, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")
        filepath = str(test_file)
        result = {"file": filepath, "removed": ["var_a"]}
        entries = [{"file": filepath, "name": "var_a", "line": 3}]
        _print_fix_file_sample(result, entries)
        out = capsys.readouterr().out
        assert "var_a" in out
        assert "line 3" in out

    @patch("desloppify.app.commands._show_terminal.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands._show_terminal.rel", side_effect=lambda p: p)
    def test_handles_missing_file(self, _mock_rel, _mock_colorize, capsys):
        result = {"file": "/nonexistent/path.py", "removed": ["x"]}
        entries = [{"file": "/nonexistent/path.py", "name": "x", "line": 1}]
        _print_fix_file_sample(result, entries)
        # Should not crash, just return silently
        assert capsys.readouterr().out == ""

    @patch("desloppify.app.commands._show_terminal.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands._show_terminal.rel", side_effect=lambda p: p)
    def test_caps_at_2_entries_per_file(self, _mock_rel, _mock_colorize, capsys, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n")
        filepath = str(test_file)
        result = {"file": filepath, "removed": ["v1", "v2", "v3"]}
        entries = [
            {"file": filepath, "name": "v1", "line": 2},
            {"file": filepath, "name": "v2", "line": 5},
            {"file": filepath, "name": "v3", "line": 8},
        ]
        _print_fix_file_sample(result, entries)
        out = capsys.readouterr().out
        # Should show v1 and v2, not v3 (capped at 2)
        assert "v1" in out
        assert "v2" in out
        assert "v3" not in out


# ── 4. viz_cmd.py ────────────────────────────────────────────────────────────

from desloppify.app.commands import viz_cmd  # noqa: E402
from desloppify.app.commands.viz_cmd import cmd_tree, cmd_viz  # noqa: E402


class TestVizCmd:
    @patch("desloppify.app.commands.viz_cmd._cmd_viz")
    def test_cmd_viz_delegates(self, mock_inner):
        args = argparse.Namespace()
        cmd_viz(args)
        mock_inner.assert_called_once_with(args)

    @patch("desloppify.app.commands.viz_cmd._cmd_tree")
    def test_cmd_tree_delegates(self, mock_inner):
        args = argparse.Namespace()
        cmd_tree(args)
        mock_inner.assert_called_once_with(args)

    def test_module_all(self):
        assert set(viz_cmd.__all__) == {"cmd_tree", "cmd_viz"}


# ── 5. review/entrypoint.py ─────────────────────────────────────────────────

from desloppify.app.commands.review.entrypoint import cmd_review  # noqa: E402


class TestCmdReviewEntrypoint:
    @patch("desloppify.app.commands.review.entrypoint.do_prepare")
    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_prepare_path(self, mock_runtime, mock_resolve_lang, mock_do_prepare):
        """When no import_file and no run_batches, falls through to do_prepare."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file=None,
            validate_import_file=None,
            external_start=False,
            external_submit=False,
            session_id=None,
        )

        cmd_review(args)

        mock_do_prepare.assert_called_once()

    @patch("desloppify.app.commands.review.entrypoint.do_import")
    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_import_path(self, mock_runtime, mock_resolve_lang, mock_do_import):
        """When import_file is set, calls do_import."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file="/tmp/review.json",
            validate_import_file=None,
            external_start=False,
            external_submit=False,
            session_id=None,
        )

        cmd_review(args)

        mock_do_import.assert_called_once()

    @patch("desloppify.app.commands.review.entrypoint.do_validate_import")
    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_validate_import_path(
        self, mock_runtime, mock_resolve_lang, mock_do_validate_import
    ):
        """When validate_import_file is set, calls do_validate_import."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file=None,
            validate_import_file="/tmp/review.json",
            external_start=False,
            external_submit=False,
            session_id=None,
        )

        cmd_review(args)

        mock_do_validate_import.assert_called_once()

    @patch("desloppify.app.commands.review.entrypoint._do_run_batches")
    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_run_batches_path(self, mock_runtime, mock_resolve_lang, mock_do_run_batches):
        """When run_batches is set, calls _do_run_batches."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=True,
            import_file=None,
            validate_import_file=None,
            external_start=False,
            external_submit=False,
            session_id=None,
        )

        cmd_review(args)

        mock_do_run_batches.assert_called_once()

    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_run_batches_rejects_conflicting_import_modes(
        self, mock_runtime, mock_resolve_lang
    ):
        """--run-batches cannot be mixed with import/validation flags."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=True,
            import_file="/tmp/review.json",
            validate_import_file=None,
            external_start=False,
            external_submit=False,
            session_id=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            cmd_review(args)
        assert exc_info.value.code == 1

    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_import_and_validate_reject_together(self, mock_runtime, mock_resolve_lang):
        """--import and --validate-import are mutually exclusive."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file="/tmp/review.json",
            validate_import_file="/tmp/review.json",
            external_start=False,
            external_submit=False,
            session_id=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            cmd_review(args)
        assert exc_info.value.code == 1

    @patch("desloppify.app.commands.review.entrypoint.do_external_start")
    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_external_start_path(self, mock_runtime, mock_resolve_lang, mock_external_start):
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file=None,
            validate_import_file=None,
            external_start=True,
            external_submit=False,
            session_id=None,
        )

        cmd_review(args)

        mock_external_start.assert_called_once()

    @patch("desloppify.app.commands.review.entrypoint.do_external_submit")
    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_external_submit_path(self, mock_runtime, mock_resolve_lang, mock_external_submit):
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file="/tmp/review.json",
            validate_import_file=None,
            external_start=False,
            external_submit=True,
            session_id="ext_20260223_000000_deadbeef",
            allow_partial=False,
            scan_after_import=False,
            path=".",
            dry_run=False,
        )

        cmd_review(args)

        mock_external_submit.assert_called_once()

    @patch("desloppify.app.commands.review.entrypoint.resolve_lang")
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    def test_external_submit_requires_import_and_session(
        self, mock_runtime, mock_resolve_lang
    ):
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        mock_resolve_lang.return_value = MagicMock(name="python")
        args = argparse.Namespace(
            run_batches=False,
            import_file=None,
            validate_import_file=None,
            external_start=False,
            external_submit=True,
            session_id=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            cmd_review(args)
        assert exc_info.value.code == 2

    @patch("desloppify.app.commands.review.entrypoint.resolve_lang", return_value=None)
    @patch("desloppify.app.commands.review.entrypoint.command_runtime")
    @patch("desloppify.app.commands.review.entrypoint.colorize", side_effect=lambda t, _c: t)
    def test_exits_when_no_lang(self, _mock_colorize, mock_runtime, mock_resolve_lang):
        """When resolve_lang returns None, prints error and exits."""
        rt = MagicMock()
        rt.state = {"findings": {}}
        rt.state_path = "/tmp/state.json"
        rt.config = {}
        mock_runtime.return_value = rt
        args = argparse.Namespace()

        with pytest.raises(SystemExit) as exc_info:
            cmd_review(args)
        assert exc_info.value.code == 1


# ── 6. update_skill.py ──────────────────────────────────────────────────────

from desloppify.app.commands.update_skill import (  # noqa: E402
    _build_section,
    _replace_section,
    cmd_update_skill,
    resolve_interface,
    update_installed_skill,
)


class TestBuildSection:
    def test_skill_only(self):
        result = _build_section("skill content", None)
        assert result == "skill content\n"

    def test_skill_with_overlay(self):
        result = _build_section("skill content", "overlay content")
        assert result == "skill content\n\noverlay content\n"

    def test_strips_trailing_whitespace(self):
        result = _build_section("skill  \n\n", "overlay  \n\n")
        assert result == "skill\n\noverlay\n"


class TestReplaceSection:
    def test_appends_when_no_markers(self):
        result = _replace_section("existing content", "new section")
        assert "existing content" in result
        assert "new section" in result

    def test_replaces_between_markers(self):
        from desloppify.utils import SKILL_BEGIN, SKILL_END
        content = f"before\n{SKILL_BEGIN}\nold content\n{SKILL_END}\nafter"
        result = _replace_section(content, "new section")
        assert "old content" not in result
        assert "new section" in result
        assert "before" in result
        assert "after" in result

    def test_handles_empty_before(self):
        from desloppify.utils import SKILL_BEGIN, SKILL_END
        content = f"{SKILL_BEGIN}\nold\n{SKILL_END}\nafter"
        result = _replace_section(content, "new")
        assert "new" in result
        assert "after" in result

    def test_handles_empty_after(self):
        from desloppify.utils import SKILL_BEGIN, SKILL_END
        content = f"before\n{SKILL_BEGIN}\nold\n{SKILL_END}"
        result = _replace_section(content, "new")
        assert "new" in result
        assert "before" in result


class TestResolveInterface:
    def test_explicit_value(self):
        assert resolve_interface("Claude") == "claude"
        assert resolve_interface("CURSOR") == "cursor"

    def test_none_with_no_install(self):
        with patch(
            "desloppify.app.commands.update_skill.find_installed_skill",
            return_value=None,
        ):
            assert resolve_interface(None) is None

    def test_from_install_overlay(self):
        from desloppify.utils import SkillInstall
        install = SkillInstall(
            rel_path=".claude/skills/desloppify/SKILL.md",
            version=1,
            overlay="claude",
            stale=False,
        )
        result = resolve_interface(None, install=install)
        assert result == "claude"

    def test_from_install_path_match(self):
        from desloppify.utils import SkillInstall
        install = SkillInstall(
            rel_path=".claude/skills/desloppify/SKILL.md",
            version=1,
            overlay=None,
            stale=False,
        )
        result = resolve_interface(None, install=install)
        assert result == "claude"

    def test_from_install_path_match_opencode(self):
        from desloppify.utils import SkillInstall

        install = SkillInstall(
            rel_path=".opencode/skills/desloppify/SKILL.md",
            version=1,
            overlay=None,
            stale=False,
        )
        result = resolve_interface(None, install=install)
        assert result == "opencode"

    def test_from_install_no_match(self):
        from desloppify.utils import SkillInstall
        install = SkillInstall(
            rel_path="unknown/path.md",
            version=1,
            overlay=None,
            stale=False,
        )
        result = resolve_interface(None, install=install)
        assert result is None


class TestCmdUpdateSkill:
    @patch("desloppify.app.commands.update_skill.update_installed_skill")
    @patch("desloppify.app.commands.update_skill.resolve_interface", return_value="claude")
    def test_valid_interface(self, _mock_resolve, mock_update):
        args = argparse.Namespace(interface="claude")
        cmd_update_skill(args)
        mock_update.assert_called_once_with("claude")

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill.resolve_interface", return_value=None)
    def test_no_interface_found(self, _mock_resolve, _mock_colorize, capsys):
        args = argparse.Namespace(interface=None)
        cmd_update_skill(args)
        out = capsys.readouterr().out
        assert "No installed skill document found" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill.resolve_interface", return_value="unknown_thing")
    def test_unknown_interface(self, _mock_resolve, _mock_colorize, capsys):
        args = argparse.Namespace(interface="unknown_thing")
        cmd_update_skill(args)
        out = capsys.readouterr().out
        assert "Unknown interface" in out


class TestUpdateInstalledSkill:
    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_download_failure(self, mock_download, _mock_colorize, capsys):
        import urllib.error
        mock_download.side_effect = urllib.error.URLError("no network")
        result = update_installed_skill("claude")
        assert result is False
        out = capsys.readouterr().out
        assert "Download failed" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_bad_content(self, mock_download, _mock_colorize, capsys):
        mock_download.return_value = "random html garbage"
        result = update_installed_skill("claude")
        assert result is False
        out = capsys.readouterr().out
        assert "doesn't look like a skill document" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_successful_dedicated_install(self, mock_download, _mock_colorize, capsys, tmp_path):
        skill_content = "# Skill\n<!-- desloppify-skill-version: 1 -->\nContent"
        mock_download.side_effect = lambda f: {
            "SKILL.md": skill_content,
            "CLAUDE.md": "overlay",
        }[f]

        with patch("desloppify.app.commands.update_skill.PROJECT_ROOT", tmp_path):
            result = update_installed_skill("claude")

        assert result is True
        written = (tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md").read_text()
        assert "desloppify-skill-version" in written
        out = capsys.readouterr().out
        assert "Updated" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_successful_shared_install(self, mock_download, _mock_colorize, capsys, tmp_path):
        """Non-dedicated install (e.g. codex) replaces section in existing file."""
        skill_content = "# Skill\n<!-- desloppify-skill-version: 1 -->\nContent"
        mock_download.side_effect = lambda f: {
            "SKILL.md": skill_content,
            "CODEX.md": "codex overlay",
        }[f]

        # Pre-create the target file with some existing content
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("# My Project\nExisting content.\n")

        with patch("desloppify.app.commands.update_skill.PROJECT_ROOT", tmp_path):
            result = update_installed_skill("codex")

        assert result is True
        written = agents_file.read_text()
        assert "Existing content" in written
        assert "desloppify-skill-version" in written
