"""Post-scan narrative/output helper tests for scan command."""

from __future__ import annotations

import pytest

import desloppify.intelligence.narrative.core as narrative_mod
from desloppify.app.commands.scan.cmd import show_dimension_deltas, show_post_scan_analysis
from desloppify.engine._scoring.policy.core import DIMENSIONS


class TestShowPostScanAnalysis:
    """show_post_scan_analysis prints warnings and narrative."""

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
            "issues": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        warnings, narrative = show_post_scan_analysis(diff, state, FakeLang())
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
            "issues": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        warnings, _ = show_post_scan_analysis(diff, state, FakeLang())
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
            "issues": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        warnings, _ = show_post_scan_analysis(diff, state, FakeLang())
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
            "issues": {},
            "overall_score": 90,
            "objective_score": 90,
            "strict_score": 90,
        }
        warnings, narrative = show_post_scan_analysis(diff, state, FakeLang())
        assert warnings == []

    def test_shows_headline_and_pointers(self, monkeypatch, capsys):
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": "Test headline",
                "actions": [
                    {
                        "command": "desloppify autofix unused-imports",
                        "description": "remove dead imports",
                    }
                ],
            },
        )

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {
            "issues": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
        }
        show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        # Slimmed scan: headline + two pointers, no Agent Plan
        assert "Test headline" in out
        assert "desloppify next" in out
        assert "desloppify status" in out
        assert "AGENT PLAN" not in out

    def test_subjective_score_nudge_removed_from_post_scan(self, monkeypatch, capsys):
        """Subjective score nudges were removed — verify they no longer appear."""
        import desloppify.intelligence.narrative.core as narrative_mod
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": None, "actions": []})

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {
            "issues": {},
            "overall_score": 50,
            "objective_score": 50,
            "strict_score": 50,
            "dimension_scores": {
                "Naming quality": {
                    "score": 88.0,
                    "strict": 88.0,
                    "detectors": {"subjective_assessment": {"failing": 2}},
                },
            },
        }
        show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        assert "Subjective scores below 90" not in out

    def test_reminders_and_plan_fields_removed_from_scan(self, monkeypatch, capsys):
        """Reminders and narrative plan fields are no longer shown in scan output."""
        import desloppify.intelligence.narrative.core as narrative_mod
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {
                "headline": None,
                "actions": [],
                "reminders": [
                    {"type": "review_stale", "message": "Design review is stale"},
                ],
                "why_now": "Security work should come first.",
                "primary_action": {"command": "desloppify show security", "description": "review security"},
                "risk_flags": [{"severity": "high", "message": "40% issues hidden"}],
            },
        )

        class FakeLang:
            name = "python"

        diff = {"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []}
        state = {"issues": {}, "overall_score": 90, "objective_score": 90, "strict_score": 90}
        show_post_scan_analysis(diff, state, FakeLang())
        out = capsys.readouterr().out
        # These sections moved to status — scan only shows headline + pointers
        assert "Reminders:" not in out
        assert "Narrative Plan:" not in out
        assert "Risk:" not in out
        assert "desloppify next" in out
        assert "desloppify status" in out


# ---------------------------------------------------------------------------
# show_dimension_deltas
# ---------------------------------------------------------------------------


class TestShowDimensionDeltas:
    """show_dimension_deltas shows which dimensions changed."""

    def test_no_change_no_output(self, monkeypatch, capsys):
        # Need DIMENSIONS to exist
        prev = {d.name: {"score": 95.0, "strict": 90.0} for d in DIMENSIONS}
        current = {d.name: {"score": 95.0, "strict": 90.0} for d in DIMENSIONS}
        show_dimension_deltas(prev, current)
        out = capsys.readouterr().out
        assert "Moved:" not in out

    def test_shows_changed_dimensions(self, monkeypatch, capsys):
        if not DIMENSIONS:
            pytest.skip("No dimensions defined")
        dim_name = DIMENSIONS[0].name
        prev = {dim_name: {"score": 90.0, "strict": 85.0}}
        current = {dim_name: {"score": 95.0, "strict": 90.0}}
        show_dimension_deltas(prev, current)
        out = capsys.readouterr().out
        assert "Moved:" in out
        assert dim_name in out
