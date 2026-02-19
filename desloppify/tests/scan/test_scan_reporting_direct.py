"""Direct tests for scan reporting presentation helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.scan.scan_reporting_analysis as scan_reporting_analysis_mod
import desloppify.app.commands.scan.scan_reporting_dimensions as scan_reporting_dimensions_mod
import desloppify.app.commands.scan.scan_reporting_llm as scan_reporting_llm_mod
import desloppify.app.commands.scan.scan_reporting_summary as scan_reporting_summary_mod


def test_show_diff_summary_prints_changes_and_suspects(capsys):
    scan_reporting_summary_mod._show_diff_summary(
        {
            "new": 2,
            "auto_resolved": 1,
            "reopened": 3,
            "suspect_detectors": ["unused", "smells"],
        }
    )
    out = capsys.readouterr().out
    assert "+2 new" in out
    assert "-1 resolved" in out
    assert "3 reopened" in out
    assert "Skipped auto-resolve for: unused, smells" in out


def test_show_score_delta_handles_unavailable_scores(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: None)
    monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: None)
    monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: None)
    monkeypatch.setattr(state_mod, "get_verified_strict_score", lambda _state: None)

    scan_reporting_summary_mod._show_score_delta(
        state={"stats": {"open": 1, "total": 2}},
        prev_overall=80.0,
        prev_objective=80.0,
        prev_strict=80.0,
        prev_verified=80.0,
    )
    assert "Scores unavailable" in capsys.readouterr().out


def test_show_score_delta_prints_scores_and_wontfix_gap(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 90.0)
    monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: 88.0)
    monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 80.0)
    monkeypatch.setattr(state_mod, "get_verified_strict_score", lambda _state: 79.0)

    scan_reporting_summary_mod._show_score_delta(
        state={"stats": {"open": 4, "total": 10, "wontfix": 12}},
        prev_overall=85.0,
        prev_objective=85.0,
        prev_strict=79.0,
        prev_verified=78.0,
    )
    out = capsys.readouterr().out
    assert "overall 90.0/100" in out
    assert "objective 88.0/100" in out
    assert "strict 80.0/100" in out
    assert "verified 79.0/100" in out
    assert "12 wontfix" in out
    assert "gap between overall and strict" in out


def test_show_score_delta_surfaces_subjective_integrity_penalty(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 89.0)
    monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: 92.0)
    monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 89.0)
    monkeypatch.setattr(state_mod, "get_verified_strict_score", lambda _state: 88.0)

    scan_reporting_summary_mod._show_score_delta(
        state={
            "stats": {"open": 2, "total": 10, "wontfix": 0},
            "subjective_integrity": {
                "status": "penalized",
                "target_score": 95.0,
                "matched_count": 2,
            },
        },
        prev_overall=90.0,
        prev_objective=92.0,
        prev_strict=90.0,
        prev_verified=89.0,
    )
    out = capsys.readouterr().out
    assert "Subjective integrity" in out
    assert "reset to 0.0" in out


def test_show_score_delta_escalates_repeated_subjective_integrity_penalty(
    monkeypatch, capsys
):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 89.0)
    monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: 92.0)
    monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 89.0)
    monkeypatch.setattr(state_mod, "get_verified_strict_score", lambda _state: 88.0)

    scan_reporting_summary_mod._show_score_delta(
        state={
            "stats": {"open": 2, "total": 10, "wontfix": 0},
            "scan_history": [
                {"subjective_integrity": {"status": "penalized"}},
                {"subjective_integrity": {"status": "penalized"}},
            ],
            "subjective_integrity": {
                "status": "penalized",
                "target_score": 95.0,
                "matched_count": 2,
            },
        },
        prev_overall=90.0,
        prev_objective=92.0,
        prev_strict=90.0,
        prev_verified=89.0,
    )
    out = capsys.readouterr().out
    assert "Repeated penalty across scans" in out
    assert "review_packet_blind.json" in out


def test_show_post_scan_analysis_surfaces_warnings_and_actions(monkeypatch, capsys):
    import desloppify.intelligence.narrative as narrative_mod
    import desloppify.state as state_mod

    monkeypatch.setattr(
        narrative_mod,
        "compute_narrative",
        lambda *_args, **_kwargs: {
            "headline": "Tighten structural debt first",
            "strategy": {
                "hint": "Parallelize auto-fixers and resolve highest tier findings first",
                "can_parallelize": True,
            },
            "actions": [
                {
                    "command": "desloppify next",
                    "description": "Fix highest priority finding",
                }
            ],
        },
    )
    monkeypatch.setattr(
        state_mod,
        "path_scoped_findings",
        lambda *_args, **_kwargs: {
            "r1": {"status": "open", "detector": "review", "file": "a.py"},
            "s1": {"status": "wontfix", "detector": "smells", "file": "b.py"},
            "s2": {"status": "wontfix", "detector": "smells", "file": "c.py"},
            "s3": {"status": "wontfix", "detector": "structural", "file": "d.py"},
        },
    )

    warnings, narrative = scan_reporting_analysis_mod._show_post_scan_analysis(
        diff={
            "new": 12,
            "auto_resolved": 1,
            "reopened": 6,
            "chronic_reopeners": ["x", "y"],
        },
        state={"findings": {}, "scan_path": ".", "review_cache": {"files": {}}},
        lang=SimpleNamespace(name="python"),
    )
    out = capsys.readouterr().out
    assert any("reopened" in warning for warning in warnings)
    assert any("cascading" in warning.lower() for warning in warnings)
    assert any("chronic reopener" in warning.lower() for warning in warnings)
    assert "Strategy:" in out
    assert "Agent focus: `desloppify next`" in out
    assert "Review: 1 finding pending" in out
    assert "complex files have never been reviewed" in out
    assert "Tighten structural debt first" in out
    assert narrative["headline"] == "Tighten structural debt first"


def test_show_post_scan_analysis_flags_holistic_subjective_integrity(
    monkeypatch, capsys
):
    import desloppify.intelligence.narrative as narrative_mod
    import desloppify.state as state_mod

    monkeypatch.setattr(
        narrative_mod,
        "compute_narrative",
        lambda *_args, **_kwargs: {"headline": None, "strategy": {}, "actions": []},
    )
    monkeypatch.setattr(
        state_mod,
        "path_scoped_findings",
        lambda *_args, **_kwargs: {
            "subjective_review::.::holistic_stale": {
                "id": "subjective_review::.::holistic_stale",
                "status": "open",
                "detector": "subjective_review",
                "file": ".",
                "summary": "Holistic review is stale",
                "detail": {"reason": "stale"},
            }
        },
    )

    scan_reporting_analysis_mod._show_post_scan_analysis(
        diff={"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []},
        state={"findings": {}, "scan_path": ".", "review_cache": {"files": {}}},
        lang=SimpleNamespace(name="python"),
    )
    out = capsys.readouterr().out
    assert "Subjective integrity:" in out
    assert "review --prepare --holistic --refresh" in out


def test_show_score_integrity_surfaces_wontfix_and_ignored(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 92.0)
    monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 70.0)

    scan_reporting_analysis_mod._show_score_integrity(
        state={
            "stats": {
                "open": 10,
                "wontfix": 30,
                "fixed": 4,
                "auto_resolved": 3,
                "false_positive": 1,
            },
            "dimension_scores": {
                "File health": {"score": 95.0, "strict": 60.0},
                "Code quality": {"score": 90.0, "strict": 80.0},
            },
        },
        diff={"ignored": 120, "ignore_patterns": 7},
    )
    out = capsys.readouterr().out
    assert "Score Integrity" in out
    assert "wontfix" in out
    assert "Biggest gaps:" in out
    assert "suppressed 120 findings" in out
    assert "still count against strict and verified scores" in out


def test_print_llm_summary_respects_env_and_includes_dimension_table(
    monkeypatch,
    capsys,
    tmp_path,
):
    import desloppify.core.registry as registry_mod
    import desloppify.scoring as scoring_mod
    import desloppify.state as state_mod

    monkeypatch.setenv("DESLOPPIFY_AGENT", "1")
    monkeypatch.delenv("CLAUDE_CODE", raising=False)
    monkeypatch.setattr(state_mod, "get_overall_score", lambda _state: 91.0)
    monkeypatch.setattr(state_mod, "get_objective_score", lambda _state: 90.0)
    monkeypatch.setattr(state_mod, "get_strict_score", lambda _state: 88.0)
    monkeypatch.setattr(state_mod, "get_verified_strict_score", lambda _state: 87.0)
    monkeypatch.setattr(
        scoring_mod,
        "DIMENSIONS",
        [
            SimpleNamespace(name="File health"),
            SimpleNamespace(name="Code quality"),
        ],
    )
    monkeypatch.setattr(registry_mod, "dimension_action_type", lambda _name: "fix")

    badge_path = Path(tmp_path / "badge.png")
    badge_path.write_bytes(b"x")
    state = {
        "dimension_scores": {
            "File health": {
                "score": 80.0,
                "strict": 70.0,
                "issues": 2,
                "checks": 1,
                "tier": 1,
            },
            "Naming Quality": {
                "score": 75.0,
                "strict": 65.0,
                "issues": 1,
                "checks": 1,
                "tier": 4,
            },
        },
        "stats": {"total": 10, "open": 4, "fixed": 3, "wontfix": 2},
    }

    scan_reporting_llm_mod._print_llm_summary(
        state=state,
        badge_path=badge_path,
        narrative={
            "headline": "Keep reducing high-tier findings",
            "strategy": {"hint": "Use fixers before manual cleanup"},
            "actions": [
                {"command": "desloppify next", "description": "Resolve top finding"}
            ],
        },
        diff={"ignored": 4, "ignore_patterns": 2},
    )
    out = capsys.readouterr().out
    assert "INSTRUCTIONS FOR LLM" in out
    assert "Overall score:   91.0/100" in out
    assert "| Dimension | Health | Strict | Issues | Tier | Action |" in out
    assert "| **Subjective Dimensions** |" in out
    assert "Ignored: 4 (by 2 patterns)" in out
    assert "Top action: `desloppify next` — Resolve top finding" in out
    assert "A scorecard image was saved to" in out


def test_show_scorecard_dimensions_and_dimension_hints(monkeypatch, capsys):
    import desloppify.scoring as scoring_mod
    import desloppify.state as state_mod

    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "_scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            (
                "File health",
                {
                    "score": 92.0,
                    "strict": 90.0,
                    "checks": 100,
                    "issues": 10,
                    "detectors": {},
                },
            ),
            (
                "Naming Quality",
                {
                    "score": 88.0,
                    "strict": 85.0,
                    "checks": 10,
                    "issues": 3,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
        ],
    )
    scan_reporting_dimensions_mod._show_scorecard_subjective_measures({})
    progress_out = capsys.readouterr().out
    assert (
        "Scorecard dimensions (matches scorecard.png)" in progress_out
        or "Subjective measures (matches scorecard.png)" in progress_out
    )
    assert "Naming Quality" in progress_out
    if "Scorecard dimensions (matches scorecard.png)" in progress_out:
        assert "File health" in progress_out

    monkeypatch.setattr(
        scoring_mod,
        "DIMENSIONS",
        [SimpleNamespace(name="File health"), SimpleNamespace(name="Code quality")],
    )
    scan_reporting_dimensions_mod._show_dimension_deltas(
        prev={
            "File health": {"score": 60.0, "strict": 55.0},
            "Code quality": {"score": 80.0, "strict": 75.0},
        },
        current={
            "File health": {"score": 65.0, "strict": 58.0},
            "Code quality": {"score": 75.0, "strict": 70.0},
        },
    )
    delta_out = capsys.readouterr().out
    assert "Moved:" in delta_out
    assert "File health" in delta_out
    assert "Code quality" in delta_out

    scan_reporting_dimensions_mod._show_low_dimension_hints(
        {
            "File health": {"score": 52.0, "strict": 40.0},
            "Naming Quality": {"score": 55.0, "strict": 45.0},
        }
    )
    hint_out = capsys.readouterr().out
    assert "Needs attention:" in hint_out
    assert "run `desloppify show structural`" in hint_out
    assert "run `desloppify review --prepare`" in hint_out

    monkeypatch.setattr(
        state_mod,
        "path_scoped_findings",
        lambda *_args, **_kwargs: {
            "sr1": {
                "detector": "subjective_review",
                "status": "open",
                "detail": {"reason": "changed"},
            },
            "sr2": {
                "detector": "subjective_review",
                "status": "open",
                "detail": {"reason": "unreviewed"},
            },
        },
    )
    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "_scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            (
                "High Level Elegance",
                {
                    "score": 78.0,
                    "strict": 78.0,
                    "issues": 0,
                    "checks": 10,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
            (
                "Mid Level Elegance",
                {
                    "score": 72.0,
                    "strict": 72.0,
                    "issues": 0,
                    "checks": 10,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
        ],
    )
    scan_reporting_dimensions_mod._show_subjective_paths(
        {"findings": {}, "scan_path": ".", "strict_score": 90.0},
        {
            "High Level Elegance": {
                "score": 78.0,
                "strict": 78.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
            "Mid Level Elegance": {
                "score": 72.0,
                "strict": 72.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
        target_strict_score=95.0,
    )
    subjective_out = capsys.readouterr().out
    assert "Subjective path:" in subjective_out
    assert "scan --path . --reset-subjective" in subjective_out
    assert "North star: strict 90.0/100 → target 95.0 (+5.0 needed)" in subjective_out
    assert "Quality below target (<95%)" in subjective_out
    assert (
        "review --prepare --dimensions mid_level_elegance,high_level_elegance"
        in subjective_out
    )
    assert "Coverage debt: 2 files need review" in subjective_out
    assert "show subjective_review --status open" in subjective_out

    scan_reporting_dimensions_mod._show_subjective_paths(
        {"findings": {}, "scan_path": ".", "strict_score": 96.0},
        {
            "High Level Elegance": {
                "score": 96.0,
                "strict": 96.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
        threshold=97.0,
        target_strict_score=97.0,
    )
    subjective_custom_target = capsys.readouterr().out
    assert (
        "North star: strict 96.0/100 → target 97.0 (+1.0 needed)"
        in subjective_custom_target
    )
    assert "Quality below target (<97%)" in subjective_custom_target


def test_show_scorecard_dimensions_uses_scorecard_rows(monkeypatch, capsys):
    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "_scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            ("File health", {"score": 90.0, "strict": 88.0, "detectors": {}}),
            (
                "Naming Quality",
                {
                    "score": 96.0,
                    "strict": 94.0,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
            (
                "Elegance",
                {
                    "score": 82.0,
                    "strict": 80.0,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
        ],
    )
    scan_reporting_dimensions_mod._show_scorecard_subjective_measures({})
    out = capsys.readouterr().out
    assert (
        "Scorecard dimensions (matches scorecard.png):" in out
        or "Subjective measures (matches scorecard.png):" in out
    )
    assert "Naming Quality" in out
    assert "96.0%" in out
    assert "strict  94.0%" in out
    assert "Elegance" in out
    if "Scorecard dimensions (matches scorecard.png):" in out:
        assert "File health" in out


def test_show_score_model_breakdown_prints_recipe_and_drags(capsys):
    state = {
        "dimension_scores": {
            "Code quality": {
                "score": 100.0,
                "tier": 3,
                "checks": 200,
                "issues": 0,
                "detectors": {},
            },
            "High Elegance": {
                "score": 80.0,
                "tier": 4,
                "checks": 10,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
        }
    }
    scan_reporting_dimensions_mod._show_score_model_breakdown(state)
    out = capsys.readouterr().out
    assert "Score recipe:" in out
    assert "40% mechanical + 60% subjective" in out
    assert "Biggest weighted drags" in out
    assert "High Elegance" in out


def test_subjective_rerun_command_builds_dimension_and_holistic_variants():
    command_dims = scan_reporting_dimensions_mod.subjective_rerun_command(
        [{"cli_keys": ["naming_quality", "logic_clarity"]}],
        max_items=5,
    )
    assert (
        "review --prepare --refresh --dimensions naming_quality,logic_clarity"
        in command_dims
    )
    assert command_dims.endswith("&& desloppify scan`")

    command_holistic = scan_reporting_dimensions_mod.subjective_rerun_command(
        [],
        max_items=5,
    )
    assert (
        command_holistic
        == "`desloppify review --prepare --holistic --refresh && desloppify scan`"
    )


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
                "name": "Naming Quality",
                "score": 96.0,
                "strict": 96.0,
                "issues": 0,
                "placeholder": False,
                "cli_keys": ["naming_quality"],
            }
        ],
        threshold=None,
    )
    assert notice is not None
    assert notice["status"] == "warn"
    assert notice["target"] == 95.0


def test_show_subjective_paths_prioritizes_integrity_gap(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(
        state_mod,
        "path_scoped_findings",
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
    scan_reporting_dimensions_mod._show_subjective_paths(
        {"findings": {}, "scan_path": ".", "strict_score": 80.0},
        {
            "High Elegance": {
                "score": 0.0,
                "strict": 0.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
        target_strict_score=95.0,
    )
    out = capsys.readouterr().out
    assert "High-priority integrity gap:" in out
    assert "review --prepare --holistic --refresh" in out
    assert "Unassessed (0% placeholder): High Elegance" in out


def test_show_subjective_paths_shows_target_match_reset_warning(monkeypatch, capsys):
    import desloppify.state as state_mod

    monkeypatch.setattr(state_mod, "path_scoped_findings", lambda *_args, **_kwargs: {})
    scan_reporting_dimensions_mod._show_subjective_paths(
        {
            "findings": {},
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
            "Naming Quality": {
                "score": 0.0,
                "strict": 0.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
            "Logic Clarity": {
                "score": 0.0,
                "strict": 0.0,
                "issues": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
        target_strict_score=95.0,
    )
    out = capsys.readouterr().out
    assert "were reset to 0.0 this scan" in out
    assert "Anti-gaming safeguard applied" in out
    assert "review --prepare --refresh --dimensions naming_quality,logic_clarity" in out
