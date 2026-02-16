"""Tests for desloppify.commands.status — display helpers."""


from desloppify.commands.status import (
    _build_detector_transparency,
    _show_dimension_table,
    _show_detector_transparency,
    _show_focus_suggestion,
    _show_ignore_summary,
    _show_structural_areas,
    cmd_status,
)


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestStatusModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_status_callable(self):
        assert callable(cmd_status)

    def test_show_dimension_table_callable(self):
        assert callable(_show_dimension_table)

    def test_show_focus_suggestion_callable(self):
        assert callable(_show_focus_suggestion)

    def test_show_structural_areas_callable(self):
        assert callable(_show_structural_areas)

    def test_show_ignore_summary_callable(self):
        assert callable(_show_ignore_summary)

    def test_build_detector_transparency_callable(self):
        assert callable(_build_detector_transparency)

    def test_show_detector_transparency_callable(self):
        assert callable(_show_detector_transparency)


# ---------------------------------------------------------------------------
# _show_structural_areas
# ---------------------------------------------------------------------------

class TestShowStructuralAreas:
    """_show_structural_areas groups T3/T4 debt by area."""

    def _make_finding(self, fid, *, file, tier, status="open"):
        return {
            "id": fid, "file": file, "tier": tier, "status": status,
            "detector": "test", "confidence": "medium", "summary": "test",
        }

    def test_no_output_when_fewer_than_5_structural(self, capsys):
        """Should produce no output when structural findings < 5."""
        state = {"findings": {
            "f1": self._make_finding("f1", file="src/a/foo.ts", tier=3),
            "f2": self._make_finding("f2", file="src/b/bar.ts", tier=4),
        }}
        _show_structural_areas(state)
        assert capsys.readouterr().out == ""

    def test_no_output_when_single_area(self, capsys):
        """Needs at least 2 areas to be worth showing."""
        state = {"findings": {
            f"f{i}": self._make_finding(f"f{i}", file=f"src/area/{chr(97+i)}.ts", tier=3)
            for i in range(6)
        }}
        _show_structural_areas(state)
        # All files in same area "src/area" -> should not print
        assert capsys.readouterr().out == ""

    def test_output_when_multiple_areas(self, capsys):
        """Shows structural debt when 5+ findings across 2+ areas."""
        findings = {}
        for i in range(3):
            fid = f"a{i}"
            findings[fid] = self._make_finding(fid, file=f"src/alpha/{chr(97+i)}.ts", tier=3)
        for i in range(3):
            fid = f"b{i}"
            findings[fid] = self._make_finding(fid, file=f"src/beta/{chr(97+i)}.ts", tier=4)
        state = {"findings": findings}
        _show_structural_areas(state)
        out = capsys.readouterr().out
        assert "Structural Debt" in out

    def test_excludes_non_structural_tiers(self, capsys):
        """T1 and T2 findings should not be counted."""
        findings = {}
        for i in range(10):
            fid = f"f{i}"
            findings[fid] = self._make_finding(fid, file=f"src/a/{i}.ts", tier=1)
        state = {"findings": findings}
        _show_structural_areas(state)
        assert capsys.readouterr().out == ""

    def test_includes_wontfix_status(self, capsys):
        """wontfix findings should be counted as structural debt."""
        findings = {}
        for i in range(3):
            fid = f"a{i}"
            findings[fid] = self._make_finding(
                fid, file=f"src/alpha/{chr(97+i)}.ts", tier=3, status="wontfix")
        for i in range(3):
            fid = f"b{i}"
            findings[fid] = self._make_finding(
                fid, file=f"src/beta/{chr(97+i)}.ts", tier=4, status="open")
        state = {"findings": findings}
        _show_structural_areas(state)
        out = capsys.readouterr().out
        assert "Structural Debt" in out


class TestShowIgnoreSummary:
    def test_prints_last_scan_and_recent_suppression(self, capsys):
        _show_ignore_summary(
            ["smells::*", "logs::*"],
            {
                "last_ignored": 12,
                "last_raw_findings": 40,
                "last_suppressed_pct": 30.0,
                "recent_scans": 3,
                "recent_ignored": 20,
                "recent_raw_findings": 100,
                "recent_suppressed_pct": 20.0,
            },
        )
        out = capsys.readouterr().out
        assert "Ignore list (2)" in out
        assert "12/40 findings hidden (30.0%)" in out
        assert "Recent (3 scans): 20/100 findings hidden (20.0%)" in out

    def test_prints_zero_hidden_when_no_last_raw(self, capsys):
        _show_ignore_summary(
            ["smells::*"],
            {
                "last_ignored": 0,
                "last_raw_findings": 0,
                "recent_scans": 1,
                "recent_ignored": 0,
                "recent_raw_findings": 0,
                "recent_suppressed_pct": 0.0,
            },
        )
        out = capsys.readouterr().out
        assert "Ignore suppression (last scan): 0 findings hidden" in out

    def test_include_suppressed_prints_detector_breakdown(self, capsys):
        _show_ignore_summary(
            ["smells::*"],
            {
                "last_ignored": 5,
                "last_raw_findings": 10,
                "last_suppressed_pct": 50.0,
                "recent_scans": 1,
            },
            include_suppressed=True,
            ignore_integrity={"ignored_by_detector": {"smells": 4, "logs": 1}},
        )
        out = capsys.readouterr().out
        assert "Suppressed by detector (last scan)" in out
        assert "smells:4" in out


class TestDetectorTransparency:
    def test_builds_detector_rows(self):
        state = {
            "scan_path": ".",
            "findings": {
                "logs::a.py::x": {
                    "id": "logs::a.py::x",
                    "detector": "logs",
                    "file": "a.py",
                    "status": "open",
                    "zone": "production",
                },
                "smells::tests/a.py::x": {
                    "id": "smells::tests/a.py::x",
                    "detector": "smells",
                    "file": "tests/a.py",
                    "status": "wontfix",
                    "zone": "test",
                },
            },
        }
        transparency = _build_detector_transparency(
            state,
            ignore_integrity={"ignored_by_detector": {"logs": 2, "security": 1}},
        )
        rows = {row["detector"]: row for row in transparency["rows"]}
        assert rows["logs"]["visible"] == 1
        assert rows["logs"]["suppressed"] == 2
        assert rows["logs"]["excluded"] == 0
        assert rows["smells"]["excluded"] == 1
        assert rows["security"]["suppressed"] == 1
        assert transparency["totals"]["suppressed"] == 3
        assert transparency["totals"]["excluded"] == 1

    def test_show_prints_when_hidden_exists(self, capsys):
        _show_detector_transparency(
            {
                "rows": [
                    {"detector": "logs", "visible": 2, "suppressed": 3, "excluded": 0, "total_detected": 5},
                ],
                "totals": {"visible": 2, "suppressed": 3, "excluded": 0},
            }
        )
        out = capsys.readouterr().out
        assert "Strict Transparency" in out
        assert "Hidden strict failures: 3/5 (60.0%)" in out

    def test_show_silent_when_no_hidden(self, capsys):
        _show_detector_transparency(
            {
                "rows": [
                    {"detector": "logs", "visible": 2, "suppressed": 0, "excluded": 0, "total_detected": 2},
                ],
                "totals": {"visible": 2, "suppressed": 0, "excluded": 0},
            }
        )
        assert capsys.readouterr().out == ""


class TestFocusSuggestion:
    def test_subjective_focus_uses_run_without_prior_review(self, capsys):
        dim_scores = {
            "Naming Quality": {
                "score": 80.0,
                "strict": 80.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {"issues": 0}},
            }
        }
        _show_focus_suggestion(dim_scores, {"potentials": {}})
        out = capsys.readouterr().out
        assert "run subjective review to improve" in out
        assert "`desloppify review --prepare`" in out

    def test_subjective_focus_uses_rerun_with_prior_review(self, capsys):
        dim_scores = {
            "Naming Quality": {
                "score": 80.0,
                "strict": 80.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {"issues": 0}},
            }
        }
        state = {
            "potentials": {},
            "review_cache": {"files": {"src/a.py": {"reviewed_at": "2026-01-01T00:00:00+00:00"}}},
        }
        _show_focus_suggestion(dim_scores, state)
        out = capsys.readouterr().out
        assert "re-review to improve" in out
        assert "`desloppify review --prepare`" in out


class TestCmdStatusNarrativeReminders:
    def test_cmd_status_prints_narrative_reminders(self, monkeypatch, capsys):
        import desloppify.commands.status as status_mod
        import desloppify.state as state_mod
        import desloppify.narrative as narrative_mod
        import desloppify.commands._helpers as helpers_mod
        import desloppify.utils as utils_mod

        monkeypatch.setattr(status_mod, "state_path", lambda _args: "/tmp/fake.json")
        monkeypatch.setattr(status_mod, "_write_query", lambda payload: None)
        monkeypatch.setattr(utils_mod, "check_tool_staleness", lambda _state: None)
        monkeypatch.setattr(helpers_mod, "resolve_lang", lambda _args: None)

        fake_state = {
            "last_scan": "2026-02-16T00:00:00+00:00",
            "scan_count": 1,
            "stats": {"by_tier": {}},
            "findings": {},
            "dimension_scores": {},
            "codebase_metrics": {},
            "potentials": {},
        }
        monkeypatch.setattr(state_mod, "load_state", lambda _sp: fake_state)
        monkeypatch.setattr(state_mod, "suppression_metrics", lambda _state: {})
        monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 90.0)
        monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: 90.0)
        monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 90.0)
        monkeypatch.setattr(state_mod, "get_strict_all_detected_score", lambda _state: 90.0)
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": None,
                "reminders": [
                    {"type": "report_scores", "message": "skip"},
                    {"type": "review_stale", "message": "Design review is 45 days old — run: desloppify review --prepare"},
                ],
            },
        )

        class FakeArgs:
            json = False
            lang = None
            path = "."
            state = None
            _config = {}

        status_mod.cmd_status(FakeArgs())
        out = capsys.readouterr().out
        assert "Reminders:" in out
        assert "Design review is 45 days old" in out
        assert "skip" not in out

    def test_cmd_status_prints_narrative_plan_fields(self, monkeypatch, capsys):
        import desloppify.commands.status as status_mod
        import desloppify.state as state_mod
        import desloppify.narrative as narrative_mod
        import desloppify.commands._helpers as helpers_mod
        import desloppify.utils as utils_mod

        monkeypatch.setattr(status_mod, "state_path", lambda _args: "/tmp/fake.json")
        monkeypatch.setattr(status_mod, "_write_query", lambda payload: None)
        monkeypatch.setattr(utils_mod, "check_tool_staleness", lambda _state: None)
        monkeypatch.setattr(helpers_mod, "resolve_lang", lambda _args: None)

        fake_state = {
            "last_scan": "2026-02-16T00:00:00+00:00",
            "scan_count": 1,
            "stats": {"by_tier": {}},
            "findings": {},
            "dimension_scores": {},
            "codebase_metrics": {},
            "potentials": {},
        }
        monkeypatch.setattr(state_mod, "load_state", lambda _sp: fake_state)
        monkeypatch.setattr(state_mod, "suppression_metrics", lambda _state: {})
        monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 90.0)
        monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: 90.0)
        monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 90.0)
        monkeypatch.setattr(state_mod, "get_strict_all_detected_score", lambda _state: 90.0)
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": None,
                "why_now": "Code quality is the current bottleneck.",
                "primary_action": {"command": "desloppify next", "description": "work highest-priority issue"},
                "verification_step": {"command": "desloppify scan", "reason": "validate trend"},
                "risk_flags": [{"severity": "medium", "message": "Review context is stale"}],
                "reminders": [],
            },
        )

        class FakeArgs:
            json = False
            lang = None
            path = "."
            state = None
            _config = {}

        status_mod.cmd_status(FakeArgs())
        out = capsys.readouterr().out
        assert "Narrative Plan:" in out
        assert "Why now: Code quality is the current bottleneck." in out
        assert "Do: `desloppify next`" in out
