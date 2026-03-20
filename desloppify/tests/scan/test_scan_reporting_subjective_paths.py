"""Subjective guidance and score-model reporting tests for scan reporting."""

from __future__ import annotations

import desloppify.app.commands.scan.reporting.dimensions as scan_reporting_dimensions_mod


def test_show_score_model_breakdown_prints_recipe_and_drags(capsys):
    state = {
        "dimension_scores": {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "failing": 0,
                "detectors": {},
            },
            "High elegance": {
                "score": 80.0,
                "tier": 4,
                "checks": 10,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        }
    }
    scan_reporting_dimensions_mod.show_score_model_breakdown(state)
    out = capsys.readouterr().out
    assert "Score recipe:" in out
    assert "25% mechanical + 75% subjective" in out
    assert "Biggest weighted drags" in out
    assert "High elegance" in out


def test_subjective_rerun_command_builds_dimension_and_holistic_variants():
    command_dims = scan_reporting_dimensions_mod.subjective_rerun_command(
        [{"cli_keys": ["naming_quality", "logic_clarity"]}],
        max_items=5,
    )
    assert (
        "review --prepare --force-review-rerun --dimensions naming_quality,logic_clarity"
        in command_dims
    )
    assert command_dims.endswith("naming_quality,logic_clarity`")

    command_holistic = scan_reporting_dimensions_mod.subjective_rerun_command(
        [],
        max_items=5,
    )
    assert (
        command_holistic
        == "`desloppify review --prepare --force-review-rerun`"
    )


def test_subjective_rerun_command_prefers_open_review_queue_when_issues_exist():
    command = scan_reporting_dimensions_mod.subjective_rerun_command(
        [{"cli_keys": ["naming_quality"], "failing": 2}],
        max_items=5,
    )
    assert command == "`desloppify show review --status open`"


def test_subjective_integrity_followup_handles_none_threshold_and_target():
    notice = scan_reporting_dimensions_mod.subjective_integrity_followup(
        {
            "subjective_integrity": {
                "status": "warn",
                "target_score": None,
                "matched_dimensions": ["naming_quality"],
            }
        },
        [
            {
                "name": "Naming quality",
                "score": 96.0,
                "strict": 96.0,
                "failing": 0,
                "placeholder": False,
                "cli_keys": ["naming_quality"],
            }
        ],
        threshold=None,
    )
    assert notice is not None
    assert notice["status"] == "warn"
    assert notice["target"] == 85.0


def test_show_subjective_paths_prioritizes_integrity_gap(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(
        state_mod,
        "path_scoped_issues",
        lambda *_args, **_kwargs: {
            "subjective_review::.::holistic_unreviewed": {
                "id": "subjective_review::.::holistic_unreviewed",
                "detector": "subjective_review",
                "status": "open",
                "summary": "No holistic codebase review on record",
                "detail": {"reason": "unreviewed"},
            }
        },
    )
    scan_reporting_dimensions_mod.show_subjective_paths_section(
        {"issues": {}, "scan_path": ".", "strict_score": 80.0},
        {
            "High elegance": {
                "score": 0.0,
                "strict": 0.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
    )
    out = capsys.readouterr().out
    assert "Subjective:" in out
    assert "unassessed" in out
    assert "show subjective" in out


def test_show_subjective_paths_prints_out_of_scope_subjective_breakdown(monkeypatch, capsys):
    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            (
                "Naming quality",
                {
                    "score": 100.0,
                    "strict": 100.0,
                    "failing": 0,
                    "checks": 10,
                    "detectors": {"subjective_assessment": {}},
                },
            )
        ],
    )
    scan_reporting_dimensions_mod.show_subjective_paths_section(
        {
            "scan_path": "src",
            "strict_score": 98.0,
            "issues": {
                "a": {
                    "detector": "subjective_review",
                    "status": "open",
                    "file": "src/a.py",
                    "detail": {"reason": "changed"},
                },
                "b": {
                    "detector": "subjective_review",
                    "status": "open",
                    "file": "scripts/b.py",
                    "detail": {"reason": "unreviewed"},
                },
            },
        },
        {
            "Naming quality": {
                "score": 100.0,
                "strict": 100.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            }
        },
    )
    out = capsys.readouterr().out
    assert "Subjective:" in out
    assert "files need review" in out
    assert "show subjective" in out


def test_show_subjective_paths_shows_target_match_reset_warning(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "path_scoped_issues", lambda *_args, **_kwargs: {})
    scan_reporting_dimensions_mod.show_subjective_paths_section(
        {
            "issues": {},
            "scan_path": ".",
            "strict_score": 94.0,
            "subjective_integrity": {
                "status": "penalized",
                "target_score": 95.0,
                "matched_count": 2,
                "matched_dimensions": ["naming_quality", "logic_clarity"],
                "reset_dimensions": ["naming_quality", "logic_clarity"],
            },
        },
        {
            "Naming quality": {
                "score": 0.0,
                "strict": 0.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
            "Logic clarity": {
                "score": 0.0,
                "strict": 0.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
    )
    out = capsys.readouterr().out
    assert "were reset to 0.0 this scan" in out
    assert "Anti-gaming safeguard applied" in out
    assert (
        "review --prepare --force-review-rerun --dimensions naming_quality,logic_clarity"
        in out
    )


def test_show_subjective_paths_does_not_swallow_stale_only_entries(monkeypatch, capsys):
    """Stale-only entries (above threshold, not unassessed) must not be swallowed by the early exit."""
    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "scorecard_subjective_entries",
        lambda _state, **_kwargs: [
            {
                "name": "High Level Elegance",
                "score": 97.0,
                "strict": 97.0,
                "failing": 0,
                "placeholder": False,
                "stale": True,
                "cli_keys": ["high_level_elegance"],
            }
        ],
    )
    scan_reporting_dimensions_mod.show_subjective_paths_section(
        {"issues": {}, "scan_path": "."},
        {
            "High Level Elegance": {
                "score": 97.0,
                "strict": 97.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
    )
    out = capsys.readouterr().out
    assert "stale" in out
    assert "show subjective" in out
