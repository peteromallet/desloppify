"""Integration tests for strategist prompt injection and runner wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline_completion import (
    is_full_stage_run,
)
from desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline_execution import (
    DEFAULT_STAGE_HANDLERS,
)
from desloppify.app.commands.plan.triage.runner.stage_prompts import build_stage_prompt
from desloppify.app.commands.plan.triage.runner.stage_prompts_observe import (
    build_observe_batch_prompt,
)


def _triage_input() -> SimpleNamespace:
    return SimpleNamespace(
        review_issues={
            "review::src/a.py::id1": {
                "summary": "Rename symbol",
                "detail": {"dimension": "naming", "file_path": "src/a.py", "description": "rename oldThing"},
            }
        },
        open_issues={
            "review::src/a.py::id1": {
                "summary": "Rename symbol",
                "detail": {"dimension": "naming", "file_path": "src/a.py", "description": "rename oldThing"},
            }
        },
        new_since_last=set(),
        resolved_since_last=set(),
        resolved_issues={},
        existing_clusters={},
        completed_clusters=[],
        dimension_scores={},
        objective_backlog_issues={},
        auto_clusters={},
        previously_dismissed=[],
    )


def _plan_with_briefing() -> dict:
    return {
        "epic_triage_meta": {
            "strategist_briefing": {
                "score_trend": "stable",
                "debt_trend": "stable",
                "observe_guidance": "Watch naming churn in shared files before trusting detector counts.",
                "reflect_guidance": "Do not create a fresh naming mega-cluster without acknowledging the rework loop.",
                "organize_guidance": "Prioritize naming first and avoid touching the same file in multiple clusters.",
                "sense_check_guidance": "Reject value-neutral rename churn if it adds coordination cost.",
                "focus_dimensions": [{"name": "naming", "reason": "high headroom", "trend": "stagnant", "headroom": 20}],
                "avoid_areas": [{"name": "src/shared.py", "reason": "rework loop", "type": "file"}],
                "rework_warnings": [{"dimension": "naming", "resolved": 3, "new_open": 3, "files": ["src/shared.py"]}],
                "file_churn_hotspots": [{"file": "src/shared.py", "count": 4, "detectors": ["review", "smells"]}],
                "anti_patterns": [{"type": "rework", "description": "Repeated naming cleanup in src/shared.py", "evidence": ["same file"]}],
            },
            "triage_stages": {
                "strategize": {
                    "stage": "strategize",
                    "report": '{"score_trend":"stable"}',
                    "confirmed_at": "2026-03-20T00:00:00+00:00",
                }
            },
        },
        "clusters": {},
        "queue_order": [],
        "execution_log": [],
        "commit_log": [],
    }


def test_build_stage_prompt_injects_strategist_sections() -> None:
    plan = _plan_with_briefing()
    triage_input = _triage_input()
    repo_root = Path("/tmp/repo")

    observe = build_stage_prompt(
        "observe",
        triage_input,
        {"strategize": "{}"},
        repo_root=repo_root,
        stages_data=plan["epic_triage_meta"]["triage_stages"],
        plan=plan,
        state={"scan_history": [], "work_items": {}, "dimension_scores": {}},
    )
    assert "## Strategic Context" in observe

    reflect = build_stage_prompt(
        "reflect",
        triage_input,
        {"strategize": "{}", "observe": "obs"},
        repo_root=repo_root,
        stages_data=plan["epic_triage_meta"]["triage_stages"],
        plan=plan,
        state={"scan_history": [], "work_items": {}, "dimension_scores": {}},
    )
    assert "## Strategic Constraints" in reflect
    assert "Focus Dimensions" in reflect

    organize = build_stage_prompt(
        "organize",
        triage_input,
        {"strategize": "{}", "reflect": "ref"},
        repo_root=repo_root,
        stages_data=plan["epic_triage_meta"]["triage_stages"],
        plan=plan,
        state={"scan_history": [], "work_items": {}, "dimension_scores": {}},
    )
    assert "## Strategic Priorities" in organize

    sense = build_stage_prompt(
        "sense-check",
        triage_input,
        {"strategize": "{}", "organize": "org", "enrich": "enr"},
        repo_root=repo_root,
        stages_data=plan["epic_triage_meta"]["triage_stages"],
        plan=plan,
        state={"scan_history": [], "work_items": {}, "dimension_scores": {}},
    )
    assert "## Strategic Flags" in sense


def test_build_observe_batch_prompt_accepts_strategist_guidance() -> None:
    prompt = build_observe_batch_prompt(
        1,
        1,
        ["naming"],
        {
            "review::src/a.py::id1": {
                "summary": "Rename symbol",
                "detail": {"dimension": "naming", "file_path": "src/a.py", "description": "rename oldThing"},
            }
        },
        repo_root=Path("/tmp/repo"),
        strategist_guidance="Strategic note: this dimension has churn.",
    )
    assert "## Strategic Context" in prompt
    assert "Strategic note" in prompt


def test_runner_wiring_includes_strategize_stage() -> None:
    assert "strategize" in DEFAULT_STAGE_HANDLERS
    assert is_full_stage_run(["observe", "reflect", "organize", "enrich", "sense-check"]) is True
    assert is_full_stage_run(["strategize", "observe", "reflect", "organize", "enrich", "sense-check"]) is True
