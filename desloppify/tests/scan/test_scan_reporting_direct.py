"""Direct tests for scan reporting presentation helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.scan.reporting.agent_context as scan_reporting_llm_mod
import desloppify.app.commands.scan.reporting.dimensions as scan_reporting_dimensions_mod
import desloppify.app.commands.scan.reporting.integrity_report as integrity_report_mod
import desloppify.app.commands.scan.reporting.summary as scan_reporting_summary_mod
import desloppify.state as state_mod


def test_auto_update_skill_migrates_legacy_codex_install(monkeypatch, capsys):
    install = scan_reporting_llm_mod.skill_docs_mod.SkillInstall(
        rel_path=".agents/skills/desloppify/SKILL.md",
        absolute_path=Path("C:/repo/.agents/skills/desloppify/SKILL.md"),
        interface="codex",
        scope="project",
        source_kind="legacy_project",
        canonical=False,
        version=4,
        overlay="codex",
        stale=True,
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(scan_reporting_llm_mod, "is_agent_environment", lambda: True)
    monkeypatch.setattr(scan_reporting_llm_mod, "_detect_agent_interface", lambda: "codex")
    monkeypatch.setattr(scan_reporting_llm_mod.skill_docs_mod, "find_installed_skills", lambda interface=None: [install] if interface in {None, "codex"} else [])
    monkeypatch.setattr(scan_reporting_llm_mod.skill_docs_mod, "find_installed_skill", lambda interface=None: install if interface == "codex" else None)
    monkeypatch.setattr(scan_reporting_llm_mod.skill_docs_mod, "select_preferred_install", lambda installs, interface=None: install)
    monkeypatch.setattr(scan_reporting_llm_mod, "update_installed_skill", lambda interface, scope="auto": calls.append((interface, scope)))

    scan_reporting_llm_mod.auto_update_skill()

    assert calls == [("codex", "user")]
    out = capsys.readouterr().out
    assert "Migrating legacy project-scoped skill install" in out


def test_auto_update_skill_skips_current_canonical_install(monkeypatch, capsys):
    install = scan_reporting_llm_mod.skill_docs_mod.SkillInstall(
        rel_path="~/.claude/skills/desloppify/SKILL.md",
        absolute_path=Path("C:/Users/test/.claude/skills/desloppify/SKILL.md"),
        interface="claude",
        scope="user",
        source_kind="canonical_user",
        canonical=True,
        version=5,
        overlay="claude",
        stale=False,
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(scan_reporting_llm_mod, "is_agent_environment", lambda: True)
    monkeypatch.setattr(scan_reporting_llm_mod, "_detect_agent_interface", lambda: "claude")
    monkeypatch.setattr(scan_reporting_llm_mod.skill_docs_mod, "find_installed_skills", lambda interface=None: [install] if interface in {None, "claude"} else [])
    monkeypatch.setattr(scan_reporting_llm_mod.skill_docs_mod, "find_installed_skill", lambda interface=None: install if interface == "claude" else None)
    monkeypatch.setattr(scan_reporting_llm_mod.skill_docs_mod, "select_preferred_install", lambda installs, interface=None: install)
    monkeypatch.setattr(scan_reporting_llm_mod, "update_installed_skill", lambda interface, scope="auto": calls.append((interface, scope)))

    scan_reporting_llm_mod.auto_update_skill()

    assert calls == []
    assert capsys.readouterr().out == ""


def test_show_diff_summary_prints_changes_and_suspects(capsys):
    scan_reporting_summary_mod.show_diff_summary(
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
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=None,
            objective=None,
            strict=None,
            verified=None,
        ),
    )

    scan_reporting_summary_mod.show_score_delta(
        state={"stats": {"open": 1, "total": 2}},
        prev_overall=80.0,
        prev_objective=80.0,
        prev_strict=80.0,
        prev_verified=80.0,
    )
    assert "Scores unavailable" in capsys.readouterr().out


def test_show_score_delta_prints_scores_and_wontfix_gap(monkeypatch, capsys):
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=90.0,
            objective=88.0,
            strict=80.0,
            verified=79.0,
        ),
    )

    scan_reporting_summary_mod.show_score_delta(
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
    assert "gap between overall and strict" in out


def test_show_score_delta_prints_legend_on_first_scan(monkeypatch, capsys):
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=90.0,
            objective=88.0,
            strict=85.0,
            verified=84.0,
        ),
    )

    scan_reporting_summary_mod.show_score_delta(
        state={"stats": {"open": 2, "total": 5, "wontfix": 0}, "scan_count": 1},
        prev_overall=None,
        prev_objective=None,
        prev_strict=None,
        prev_verified=None,
    )
    out = capsys.readouterr().out
    assert "Score guide:" in out
    assert "your north star" in out
    assert "25% mechanical + 75% subjective" in out


def test_show_score_delta_hides_legend_on_subsequent_scans(monkeypatch, capsys):
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=95.0,
            objective=94.0,
            strict=93.0,
            verified=92.0,
        ),
    )
    # Ensure not in agent environment so the non-agent path hides the legend
    monkeypatch.setattr(scan_reporting_summary_mod, "is_agent_environment", lambda: False)

    scan_reporting_summary_mod.show_score_delta(
        state={"stats": {"open": 1, "total": 5, "wontfix": 0}, "scan_count": 5},
        prev_overall=94.0,
        prev_objective=93.0,
        prev_strict=92.0,
        prev_verified=91.0,
    )
    out = capsys.readouterr().out
    assert "Score guide:" not in out


def test_show_score_delta_shows_legend_in_agent_environment(monkeypatch, capsys):
    """Agent environments always see the score legend, even on subsequent scans."""
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=95.0,
            objective=94.0,
            strict=93.0,
            verified=92.0,
        ),
    )
    monkeypatch.setattr(scan_reporting_summary_mod, "is_agent_environment", lambda: True)

    scan_reporting_summary_mod.show_score_delta(
        state={"stats": {"open": 1, "total": 5, "wontfix": 0}, "scan_count": 5},
        prev_overall=94.0,
        prev_objective=93.0,
        prev_strict=92.0,
        prev_verified=91.0,
    )
    out = capsys.readouterr().out
    assert "Score guide:" in out
    assert "your north star" in out


def test_show_score_delta_prints_scores_without_open_breakdown(monkeypatch, capsys):
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=95.0,
            objective=95.0,
            strict=94.0,
            verified=93.0,
        ),
    )

    scan_reporting_summary_mod.show_score_delta(
        state={
            "scan_path": "src",
            "stats": {"open": 1, "total": 1, "wontfix": 0},
            "issues": {
                "a": {"status": "open", "file": "src/a.py"},
                "b": {"status": "open", "file": "scripts/b.py"},
            },
        },
        prev_overall=90.0,
        prev_objective=90.0,
        prev_strict=90.0,
        prev_verified=90.0,
    )
    out = capsys.readouterr().out
    # Scores present, open-count breakdown moved to status
    assert "overall 95.0/100" in out
    assert "open (in-scope)" not in out


def test_show_score_delta_surfaces_subjective_integrity_penalty(monkeypatch, capsys):
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=89.0,
            objective=92.0,
            strict=89.0,
            verified=88.0,
        ),
    )

    scan_reporting_summary_mod.show_score_delta(
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
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=89.0,
            objective=92.0,
            strict=89.0,
            verified=88.0,
        ),
    )

    scan_reporting_summary_mod.show_score_delta(
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


def test_show_post_scan_analysis_surfaces_warnings_and_headline(monkeypatch, capsys):
    import desloppify.intelligence.narrative.core as narrative_mod

    monkeypatch.setattr(
        narrative_mod,
        "compute_narrative",
        lambda *_args, **_kwargs: {
            "headline": "Tighten structural debt first",
            "strategy": {
                "hint": "Parallelize auto-fixers and resolve highest tier issues first",
                "can_parallelize": True,
            },
            "actions": [
                {
                    "command": "desloppify next",
                    "description": "Fix highest priority issue",
                }
            ],
        },
    )

    warnings, narrative = integrity_report_mod.show_post_scan_analysis(
        diff={
            "new": 12,
            "auto_resolved": 1,
            "reopened": 6,
            "chronic_reopeners": ["x", "y"],
        },
        state={"issues": {}, "scan_path": ".", "review_cache": {"files": {}}},
        lang=SimpleNamespace(name="python"),
    )
    out = capsys.readouterr().out
    assert any("reopened" in warning for warning in warnings)
    assert any("cascading" in warning.lower() for warning in warnings)
    assert any("chronic reopener" in warning.lower() for warning in warnings)
    # Slimmed scan: headline + pointers only (no Agent Plan, no review nudge)
    assert "AGENT PLAN" not in out
    assert "Tighten structural debt first" in out
    assert "desloppify next" in out
    assert "desloppify status" in out
    assert narrative["headline"] == "Tighten structural debt first"


def test_show_post_scan_analysis_no_committee_sections(
    monkeypatch, capsys
):
    import desloppify.intelligence.narrative.core as narrative_mod

    monkeypatch.setattr(
        narrative_mod,
        "compute_narrative",
        lambda *_args, **_kwargs: {"headline": None, "strategy": {}, "actions": []},
    )

    integrity_report_mod.show_post_scan_analysis(
        diff={"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []},
        state={"issues": {}, "scan_path": ".", "review_cache": {"files": {}}},
        lang=SimpleNamespace(name="python"),
    )
    out = capsys.readouterr().out
    # Slimmed scan: no committee sections
    assert "AGENT PLAN" not in out
    assert "Subjective integrity:" not in out
    assert "Subjective coverage:" not in out
    assert "Review:" not in out
    assert "complex files have never been reviewed" not in out
    # Pointers are always present
    assert "desloppify next" in out
    assert "desloppify status" in out


def test_show_post_scan_analysis_warns_when_scan_coverage_reduced(monkeypatch, capsys):
    import desloppify.intelligence.narrative.core as narrative_mod
    import desloppify.state as state_mod

    monkeypatch.setattr(
        narrative_mod,
        "compute_narrative",
        lambda *_args, **_kwargs: {"headline": None, "strategy": {}, "actions": []},
    )
    monkeypatch.setattr(
        state_mod,
        "path_scoped_issues",
        lambda *_args, **_kwargs: {},
    )

    warnings, _ = integrity_report_mod.show_post_scan_analysis(
        diff={"new": 0, "auto_resolved": 0, "reopened": 0, "chronic_reopeners": []},
        state={
            "issues": {},
            "scan_path": ".",
            "scan_coverage": {
                "python": {
                    "detectors": {
                        "security": {
                            "status": "reduced",
                            "confidence": 0.6,
                            "summary": "bandit missing",
                            "impact": "Python-specific security checks were skipped.",
                            "remediation": "Install Bandit: pip install bandit",
                        }
                    }
                }
            },
        },
        lang=SimpleNamespace(name="python"),
    )

    out = capsys.readouterr().out
    assert any("Coverage reduced (security)" in warning for warning in warnings)
    assert "Coverage reduced (security)" in out
    assert "Repercussion:" in out
    assert "Install Bandit" in out


def test_show_score_integrity_surfaces_wontfix_and_ignored(monkeypatch, capsys):
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=92.0,
            objective=None,
            strict=70.0,
            verified=None,
        ),
    )

    integrity_report_mod.show_score_integrity(
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
    assert "suppressed 120 issues" in out
    assert "still count against strict and verified scores" in out


def test_show_score_integrity_surfaces_reduced_score_confidence(capsys):
    integrity_report_mod.show_score_integrity(
        state={
            "stats": {
                "open": 0,
                "wontfix": 0,
                "fixed": 0,
                "auto_resolved": 0,
                "false_positive": 0,
            },
            "score_confidence": {
                "status": "reduced",
                "confidence": 0.6,
                "dimensions": ["Security"],
                "detectors": [
                    {
                        "summary": "bandit is not installed",
                        "remediation": "Install Bandit: pip install bandit",
                    }
                ],
            },
        },
        diff={"ignored": 0, "ignore_patterns": 0},
    )
    out = capsys.readouterr().out
    assert "Score Integrity" in out
    assert "Score confidence reduced to 60%" in out
    assert "bandit is not installed" in out


def test_print_llm_summary_respects_env_and_includes_dimension_table(
    monkeypatch,
    capsys,
    tmp_path,
):
    import desloppify.base.registry as registry_mod
    import desloppify.engine._scoring.policy.core as scoring_policy_mod
    monkeypatch.setenv("DESLOPPIFY_AGENT", "1")
    monkeypatch.delenv("CLAUDE_CODE", raising=False)
    monkeypatch.setattr(
        state_mod,
        "score_snapshot",
        lambda _state: state_mod.ScoreSnapshot(
            overall=91.0,
            objective=90.0,
            strict=88.0,
            verified=87.0,
        ),
    )
    monkeypatch.setattr(
        scoring_policy_mod,
        "DIMENSIONS",
        [
            SimpleNamespace(name="File health"),
            SimpleNamespace(name="Code quality"),
        ],
    )
    monkeypatch.setattr(registry_mod, "dimension_action_type", lambda _name: "autofix")

    badge_path = Path(tmp_path / "badge.png")
    badge_path.write_bytes(b"x")
    state = {
        "dimension_scores": {
            "File health": {
                "score": 80.0,
                "strict": 70.0,
                "failing": 2,
                "checks": 1,
                "tier": 1,
            },
            "Naming quality": {
                "score": 75.0,
                "strict": 65.0,
                "failing": 1,
                "checks": 1,
                "tier": 4,
            },
        },
        "stats": {"total": 10, "open": 4, "fixed": 3, "wontfix": 2},
    }

    scan_reporting_llm_mod.print_llm_summary(
        state=state,
        badge_path=badge_path,
        narrative={
            "headline": "Keep reducing high-tier issues",
            "strategy": {"hint": "Use fixers before manual cleanup"},
            "actions": [
                {"command": "desloppify next", "description": "Resolve top issue"}
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
    assert "Top action: `desloppify next` — Resolve top issue" in out
    assert "A scorecard image was saved to" in out
    assert "Score guide:" in out
    assert "your north star" in out


def test_show_scorecard_dimensions_and_dimension_hints(monkeypatch, capsys):
    import desloppify.engine._scoring.policy.core as scoring_policy_mod
    import desloppify.state as state_mod

    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            (
                "File health",
                {
                    "score": 92.0,
                    "strict": 90.0,
                    "checks": 100,
                    "failing": 10,
                    "detectors": {},
                },
            ),
            (
                "Naming quality",
                {
                    "score": 88.0,
                    "strict": 85.0,
                    "checks": 10,
                    "failing": 3,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
        ],
    )
    scan_reporting_dimensions_mod.show_scorecard_subjective_measures({})
    progress_out = capsys.readouterr().out
    assert (
        "Scorecard dimensions (matches scorecard.png)" in progress_out
        or "Subjective measures (matches scorecard.png)" in progress_out
    )
    assert "Naming quality" in progress_out
    if "Scorecard dimensions (matches scorecard.png)" in progress_out:
        assert "File health" in progress_out

    monkeypatch.setattr(
        scoring_policy_mod,
        "DIMENSIONS",
        [SimpleNamespace(name="File health"), SimpleNamespace(name="Code quality")],
    )
    scan_reporting_dimensions_mod.show_dimension_deltas(
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

    scan_reporting_dimensions_mod.show_low_dimension_hints(
        {
            "File health": {"score": 52.0, "strict": 40.0},
            "Naming quality": {"score": 55.0, "strict": 45.0},
        }
    )
    hint_out = capsys.readouterr().out
    assert "Needs attention:" in hint_out
    assert "run `desloppify show structural`" in hint_out
    assert "run `desloppify review --prepare`" in hint_out

    monkeypatch.setattr(
        state_mod,
        "path_scoped_issues",
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
        "scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            (
                "High Level Elegance",
                {
                    "score": 78.0,
                    "strict": 78.0,
                    "failing": 0,
                    "checks": 10,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
            (
                "Mid Level Elegance",
                {
                    "score": 72.0,
                    "strict": 72.0,
                    "failing": 0,
                    "checks": 10,
                    "detectors": {"subjective_assessment": {}},
                },
            ),
        ],
    )
    scan_reporting_dimensions_mod.show_subjective_paths_section(
        {
            "issues": {
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
            "scan_path": ".",
            "strict_score": 90.0,
        },
        {
            "High Level Elegance": {
                "score": 78.0,
                "strict": 78.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
            "Mid Level Elegance": {
                "score": 72.0,
                "strict": 72.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
    )
    subjective_out = capsys.readouterr().out
    assert "Subjective:" in subjective_out
    assert "2 below target (95%)" in subjective_out
    assert "files need review" in subjective_out
    assert "show subjective" in subjective_out

    scan_reporting_dimensions_mod.show_subjective_paths_section(
        {"issues": {}, "scan_path": ".", "strict_score": 96.0},
        {
            "High Level Elegance": {
                "score": 96.0,
                "strict": 96.0,
                "failing": 0,
                "detectors": {"subjective_assessment": {}},
            },
        },
        threshold=97.0,
    )
    subjective_custom_target = capsys.readouterr().out
    assert "Subjective:" in subjective_custom_target
    assert "below target (97%)" in subjective_custom_target
    assert "show subjective" in subjective_custom_target


def test_show_scorecard_dimensions_uses_scorecard_rows(monkeypatch, capsys):
    monkeypatch.setattr(
        scan_reporting_dimensions_mod,
        "scorecard_dimension_rows",
        lambda _state, **_kwargs: [
            ("File health", {"score": 90.0, "strict": 88.0, "detectors": {}}),
            (
                "Naming quality",
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
    scan_reporting_dimensions_mod.show_scorecard_subjective_measures({})
    out = capsys.readouterr().out
    assert (
        "Scorecard dimensions (matches scorecard.png):" in out
        or "Subjective measures (matches scorecard.png):" in out
    )
    assert "Naming quality" in out
    assert "96.0%" in out
    assert "strict  94.0%" in out
    assert "Elegance" in out
    if "Scorecard dimensions (matches scorecard.png):" in out:
        assert "File health" in out

