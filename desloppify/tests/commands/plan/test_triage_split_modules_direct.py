"""Direct coverage tests for split triage validation/orchestrator modules."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.app.commands.plan.triage.confirmations.basic as confirmations_basic_mod
import desloppify.app.commands.plan.triage.confirmations.enrich as confirmations_enrich_mod
import desloppify.app.commands.plan.triage.confirmations.organize as confirmations_organize_mod
import desloppify.app.commands.plan.triage.display.layout as display_layout_mod
import desloppify.app.commands.plan.triage.lifecycle as triage_lifecycle_mod
import desloppify.app.commands.plan.triage.runner.codex_runner as codex_runner_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_claude as orchestrator_claude_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_codex_observe as orchestrator_observe_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline as orchestrator_pipeline_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline_completion as orchestrator_pipeline_completion_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline_context as orchestrator_pipeline_context_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline_execution as orchestrator_pipeline_execution_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_codex_sense as orchestrator_sense_mod
import desloppify.app.commands.plan.triage.runner.orchestrator_common as orchestrator_common_mod
import desloppify.app.commands.plan.triage.validation.completion_policy as completion_policy_mod
import desloppify.app.commands.plan.triage.validation.completion_stages as completion_stages_mod
import desloppify.app.commands.plan.triage.validation.enrich_checks as enrich_checks_mod
from desloppify.app.commands.plan.triage.runner.orchestrator_codex_pipeline_execution import (
    StageExecutionResult,
)
from desloppify.base.exception_sets import CommandError
from desloppify.engine.plan_triage import build_triage_snapshot


def _fake_cli_command() -> str:
    """Return a platform-appropriate fake helper path for tests."""
    if os.name == "nt":
        return r"C:\tmp\run_desloppify.cmd"
    return "/tmp/run_desloppify.sh"


def _expected_helper_name() -> str:
    """Return the generated helper filename for the current platform."""
    return "run_desloppify.cmd" if os.name == "nt" else "run_desloppify.sh"


def _make_stage_context(
    tmp_path: Path,
    **overrides,
) -> orchestrator_pipeline_context_mod.StageRunContext:
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir(exist_ok=True)
    defaults = {
        "stage": "reflect",
        "stage_start": time.monotonic(),
        "args": argparse.Namespace(state=None),
        "services": SimpleNamespace(load_plan=lambda: {"epic_triage_meta": {"triage_stages": {}}}),
        "plan": {},
        "triage_input": {},
        "prior_reports": {},
        "repo_root": tmp_path,
        "prompts_dir": tmp_path / "prompts",
        "output_dir": tmp_path / "output",
        "logs_dir": tmp_path / "logs",
        "cli_command": _fake_cli_command(),
        "timeout_seconds": 60,
        "dry_run": False,
        "append_run_log": lambda _line: None,
    }
    defaults.update(overrides)
    return orchestrator_pipeline_context_mod.StageRunContext(**defaults)


def test_completion_policy_helpers_cover_success_and_fail_paths(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        completion_policy_mod,
        "scoped_manual_clusters_with_issues",
        lambda _plan, _state=None: ["c1"],
    )
    monkeypatch.setattr(completion_policy_mod, "active_triage_issue_scope", lambda _plan, _state=None: None)
    monkeypatch.setattr(
        completion_policy_mod,
        "open_review_ids_from_state",
        lambda _state: {"review::a.py::id1"},
    )
    monkeypatch.setattr(completion_policy_mod, "triage_coverage", lambda _plan, open_review_ids: (1, 1, []))
    monkeypatch.setattr(completion_policy_mod, "unenriched_clusters", lambda _plan, _state=None: [])
    monkeypatch.setattr(completion_policy_mod, "unclustered_review_issues", lambda _plan, _state: [])
    assert completion_policy_mod._completion_clusters_valid({"clusters": {}}, state={}) is True
    readiness = completion_policy_mod.evaluate_completion_readiness(
        {"clusters": {}},
        state={},
    )
    assert readiness.ok is True
    assert readiness.organized == 1
    assert readiness.total == 1

    assert completion_policy_mod._resolve_completion_strategy("keep", meta={}) == "keep"
    assert completion_policy_mod._resolve_completion_strategy(None, meta={}) is None
    assert completion_policy_mod._completion_strategy_valid("same") is True
    assert completion_policy_mod._completion_strategy_valid("x" * 220) is True
    assert completion_policy_mod._completion_strategy_valid("too short") is False

    assert completion_policy_mod._require_prior_strategy_for_confirm({"strategy_summary": "ok"}) is True
    assert completion_policy_mod._require_prior_strategy_for_confirm({}) is False
    assert completion_policy_mod._confirm_note_valid("x" * 100) is True
    assert completion_policy_mod._confirm_note_valid("short") is False

    assert (
        completion_policy_mod._resolve_confirm_existing_strategy(
            "same",
            has_only_additions=False,
            meta={},
        )
        == "same"
    )
    assert (
        completion_policy_mod._resolve_confirm_existing_strategy(
            None,
            has_only_additions=True,
            meta={},
        )
        == "same"
    )
    assert completion_policy_mod._confirm_strategy_valid("x" * 220) is True
    assert completion_policy_mod._confirm_strategy_valid("short") is False

    monkeypatch.setattr(
        completion_policy_mod,
        "extract_issue_citations",
        lambda _note, valid_ids: set(valid_ids),
    )
    si = SimpleNamespace(
        new_since_last={"review::a.py::id1"},
        open_issues={"review::a.py::id1": {}},
    )
    assert completion_policy_mod._note_cites_new_issues_or_error("review::a.py::id1", si) is True
    monkeypatch.setattr(completion_policy_mod, "extract_issue_citations", lambda _note, _ids: set())
    assert completion_policy_mod._note_cites_new_issues_or_error("no citation", si) is False

    out = capsys.readouterr().out
    assert "Strategy too short" in out


def test_runner_validate_completion_uses_shared_completion_boundary(monkeypatch, tmp_path: Path) -> None:
    import desloppify.app.commands.plan.triage.runner.stage_validation as stage_validation_mod

    monkeypatch.setattr(
        stage_validation_mod,
        "evaluate_completion_readiness",
        lambda _plan, _state, require_confirmed_stages=False: completion_policy_mod.CompletionReadiness(
            ok=True,
            message="Advisory: shared boundary hit",
            organized=2,
            total=2,
        ),
    )

    ok, message = stage_validation_mod.validate_completion({}, {}, tmp_path)

    assert ok is True
    assert message == "Advisory: shared boundary hit"


def test_completion_stage_helpers_include_gate_and_auto_confirm_defaults(monkeypatch, capsys) -> None:
    plan = {"clusters": {"a": {"issue_ids": ["id1"], "action_steps": []}}}

    assert (
        completion_stages_mod._require_organize_stage_for_complete(
            plan=plan,
            meta={},
            stages={},
        )
        is False
    )
    assert (
        completion_stages_mod._require_enrich_stage_for_complete(
            plan=plan,
            meta={},
            stages={"organize": {}},
        )
        is False
    )
    assert (
        completion_stages_mod._require_sense_check_stage_for_complete(
            plan=plan,
            meta={},
            stages={"enrich": {}},
        )
        is False
    )

    assert (
        completion_stages_mod._auto_confirm_stage_for_complete(
            plan=plan,
            stages={},
            stage="organize",
            attestation=None,
        )
        is False
    )
    assert (
        completion_stages_mod._auto_confirm_enrich_for_complete(
            plan=plan,
            stages={},
            attestation=None,
        )
        is False
    )
    assert (
        completion_stages_mod._auto_confirm_stage_for_complete(
            plan=plan,
            stages={},
            stage="sense-check",
            attestation=None,
        )
        is False
    )

    out = capsys.readouterr().out
    assert "Cannot complete" in out


def test_enrich_checks_helpers_cover_main_signals(tmp_path, capsys) -> None:
    plan = {
        "clusters": {
            "manual": {
                "issue_ids": ["i1", "i2", "i3"],
                "action_steps": [
                    {"title": "Fix A", "detail": "short", "issue_refs": []},
                    {
                        "title": "Fix B",
                        "detail": "edit src/missing/file.ts and update behavior",
                        "issue_refs": ["review::a.py::1"],
                    },
                    {
                        "title": "Fix C",
                        "detail": (
                            "update src/a/file.ts and src/b/file.ts and src/c/file.ts and "
                            "src/d/file.ts and src/e/file.ts and src/f/file.ts"
                        ),
                        "issue_refs": ["review::a.py::2"],
                        "effort": "small",
                    },
                ],
            }
        },
        "issues": {"review::a.py::2": {"status": "wontfix"}},
    }

    assert enrich_checks_mod._require_organize_stage_for_enrich({"observe": {}, "reflect": {}}) is False
    assert enrich_checks_mod._underspecified_steps(plan) == [("manual", 1, 3)]
    assert enrich_checks_mod._steps_without_effort(plan) == [("manual", 2, 3)]
    assert enrich_checks_mod._steps_missing_issue_refs(plan) == [("manual", 1, 3)]
    assert enrich_checks_mod._clusters_with_high_step_ratio(plan) == []

    bad_paths = enrich_checks_mod._steps_with_bad_paths(plan, tmp_path)
    assert bad_paths
    vague = enrich_checks_mod._steps_with_vague_detail(plan, tmp_path)
    assert vague
    stale_refs = enrich_checks_mod._steps_referencing_skipped_issues(plan)
    assert stale_refs == [("manual", 3, ["review::a.py::2"])]

    assert enrich_checks_mod._enrich_report_or_error("x" * 120) == "x" * 120
    assert enrich_checks_mod._enrich_report_or_error("short") is None

    out = capsys.readouterr().out
    assert "Report too short" in out


def test_confirmation_modules_stage_presence_guards(capsys) -> None:
    args = argparse.Namespace()
    confirmations_basic_mod.confirm_observe(args, {}, {}, None)
    confirmations_basic_mod.confirm_reflect(args, {}, {}, None)
    confirmations_enrich_mod.confirm_enrich(args, {}, {}, None)
    confirmations_enrich_mod.confirm_sense_check(args, {}, {}, None)
    confirmations_organize_mod.confirm_organize(args, {}, {}, None)
    out = capsys.readouterr().out
    assert "Cannot confirm" in out


def test_confirmation_pipeline_structures_enrich_level_results(monkeypatch) -> None:
    import desloppify.app.commands.plan.triage.validation.enrich_quality as enrich_quality_mod

    monkeypatch.setattr(
        enrich_quality_mod,
        "_underspecified_steps",
        lambda _plan: [("cluster-a", 2, 4)],
    )
    monkeypatch.setattr(
        enrich_quality_mod,
        "_steps_with_bad_paths",
        lambda _plan, _root: [("cluster-a", 1, ["src/missing.py"])],
    )
    monkeypatch.setattr(
        enrich_quality_mod,
        "_steps_without_effort",
        lambda _plan: [("cluster-a", 1, 4)],
    )
    monkeypatch.setattr(
        enrich_quality_mod,
        "_steps_missing_issue_refs",
        lambda _plan: [("cluster-a", 3, 4)],
    )
    monkeypatch.setattr(
        enrich_quality_mod,
        "_steps_with_vague_detail",
        lambda _plan, _root: [("cluster-a", 2, "Fix")],
    )
    monkeypatch.setattr(
        enrich_quality_mod,
        "_steps_referencing_skipped_issues",
        lambda _plan: [("cluster-a", 2, ["review::a.py::id1"])],
    )
    monkeypatch.setattr("desloppify.base.discovery.paths.get_project_root", lambda: Path("."))

    report = confirmations_enrich_mod._collect_enrich_level_confirmation_checks(
        {"clusters": {}},
        include_stale_issue_ref_warning=True,
    )

    assert [issue.code for issue in report.failures] == [
        "underspecified",
        "bad_paths",
        "missing_effort",
        "missing_issue_refs",
        "vague_detail",
    ]
    assert report.failure("underspecified") is not None
    assert report.failure("bad_paths") is not None
    assert report.warning("stale_issue_refs") is not None


def test_confirmation_pipeline_can_skip_stale_issue_ref_warnings(monkeypatch) -> None:
    import desloppify.app.commands.plan.triage.validation.enrich_quality as enrich_quality_mod

    monkeypatch.setattr(enrich_quality_mod, "_underspecified_steps", lambda _plan: [])
    monkeypatch.setattr(enrich_quality_mod, "_steps_with_bad_paths", lambda _plan, _root: [])
    monkeypatch.setattr(enrich_quality_mod, "_steps_without_effort", lambda _plan: [])
    monkeypatch.setattr(enrich_quality_mod, "_steps_missing_issue_refs", lambda _plan: [])
    monkeypatch.setattr(enrich_quality_mod, "_steps_with_vague_detail", lambda _plan, _root: [])
    monkeypatch.setattr(
        enrich_quality_mod,
        "_steps_referencing_skipped_issues",
        lambda _plan: [("cluster-a", 1, ["review::a.py::id1"])],
    )
    monkeypatch.setattr("desloppify.base.discovery.paths.get_project_root", lambda: Path("."))

    report = confirmations_enrich_mod._collect_enrich_level_confirmation_checks(
        {"clusters": {}},
        include_stale_issue_ref_warning=False,
    )

    assert report.failures == []
    assert report.warnings == []


def test_confirmation_pipeline_threads_triage_issue_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_evaluate(plan, repo_root, **kwargs):
        del plan, repo_root
        captured.update(kwargs)
        return confirmations_enrich_mod._ConfirmationCheckReport(failures=[], warnings=[])

    monkeypatch.setattr(confirmations_enrich_mod, "evaluate_enrich_quality", _fake_evaluate)
    monkeypatch.setattr("desloppify.base.discovery.paths.get_project_root", lambda: Path("."))

    report = confirmations_enrich_mod._collect_enrich_level_confirmation_checks(
        {"clusters": {}},
        include_stale_issue_ref_warning=True,
        triage_issue_ids={"review::current::issue"},
    )

    assert report.failures == []
    assert captured["triage_issue_ids"] == {"review::current::issue"}


def test_validate_attestation_rules() -> None:
    assert confirmations_basic_mod.validate_attestation("mentions naming", "observe", dimensions=["Naming"]) is None
    err = confirmations_basic_mod.validate_attestation(
        "generic text",
        "reflect",
        dimensions=["Naming"],
        cluster_names=["cluster-a"],
    )
    assert err is not None


def test_display_layout_renderers(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        display_layout_mod,
        "print_stage_progress",
        lambda _stages, _plan: print("stage-progress"),
    )

    si = SimpleNamespace(
        open_issues={
            "review::src/a.py::id1": {
                "summary": "Issue one",
                "detail": {"dimension": "naming", "suggestion": "rename value"},
            }
        },
        existing_clusters=[],
        new_since_last={"review::src/a.py::id1"},
        resolved_since_last=set(),
    )
    stages = {"observe": {"report": "observe report"}, "reflect": {"report": "reflect report"}}
    meta = {"strategy_summary": "Legacy strategy summary"}
    plan = {
        "clusters": {
            "manual": {
                "issue_ids": ["review::src/a.py::id1"],
                "action_steps": [{"title": "Do thing"}],
                "description": "manual cluster",
            }
        },
        "queue_order": ["review::src/a.py::id1"],
    }
    state = {"issues": si.open_issues}
    snapshot = build_triage_snapshot(plan, state)

    display_layout_mod.print_dashboard_header(si, stages, meta, plan, snapshot=snapshot)
    display_layout_mod.print_action_guidance(stages, meta, si, plan, snapshot=snapshot)
    display_layout_mod.print_prior_stage_reports(stages)
    display_layout_mod.print_issues_by_dimension(si.open_issues)
    display_layout_mod.show_plan_summary(plan, state)

    out = capsys.readouterr().out
    assert "Cluster triage" in out
    assert "stage-progress" in out
    assert "Review issues by dimension" in out
    assert "Coverage:" in out
    assert "reusing the current enriched cluster plan" in out


def test_orchestrator_common_helpers(monkeypatch) -> None:
    assert orchestrator_common_mod.parse_only_stages(None) == list(orchestrator_common_mod.STAGES)
    assert orchestrator_common_mod.parse_only_stages("observe,reflect") == ["observe", "reflect"]
    with pytest.raises(ValueError):
        orchestrator_common_mod.parse_only_stages("invalid")

    stamp = orchestrator_common_mod.run_stamp()
    assert len(stamp) == 15


def test_lifecycle_ensure_triage_started_handles_active_blocked_and_started() -> None:
    saved: list[dict] = []
    entries: list[tuple[str, dict]] = []
    printed: list[tuple[str, str]] = []

    services = SimpleNamespace(
        save_plan=lambda plan: saved.append(dict(plan)),
        append_log_entry=lambda _plan, action, **kwargs: entries.append((action, kwargs["detail"])),
    )

    active_plan = {"epic_triage_meta": {"triage_start_blocked": "stale"}}
    outcome = triage_lifecycle_mod.ensure_triage_started(
        active_plan,
        services=services,
        deps=triage_lifecycle_mod.TriageLifecycleDeps(
            has_triage_in_queue=lambda _plan: True,
            colorize=lambda text, style: printed.append((text, style)) or text,
        ),
    )
    assert outcome.status == "already_active"
    assert active_plan["epic_triage_meta"] == {}

    blocked_plan = {"epic_triage_meta": {}}
    blocked = triage_lifecycle_mod.ensure_triage_started(
        blocked_plan,
        services=services,
        state={"issues": {}},
        deps=triage_lifecycle_mod.TriageLifecycleDeps(
            has_triage_in_queue=lambda _plan: False,
            decide_triage_start=lambda *_a, **_k: SimpleNamespace(
                action="defer", reason="objective_backlog"
            ),
            colorize=lambda text, style: printed.append((text, style)) or text,
        ),
    )
    assert blocked.status == "blocked"
    assert blocked_plan["epic_triage_meta"]["triage_start_blocked"] == "objective_backlog"
    assert saved

    started_plan = {"epic_triage_meta": {"triage_start_blocked": "old"}}
    injected: list[str] = []
    started = triage_lifecycle_mod.ensure_triage_started(
        started_plan,
        services=services,
        state={"issues": {}},
        log_action="triage_start",
        log_detail={"source": "test"},
        start_message="started",
        deps=triage_lifecycle_mod.TriageLifecycleDeps(
            has_triage_in_queue=lambda _plan: False,
            inject_triage_stages=lambda plan: injected.extend(
                plan.setdefault("queue_order", ["triage::observe"])
            ),
            decide_triage_start=lambda *_a, **_k: SimpleNamespace(
                action="start", reason="allowed"
            ),
            colorize=lambda text, style: printed.append((text, style)) or text,
        ),
    )
    assert started.status == "started"
    assert started_plan["epic_triage_meta"]["triage_stages"] == {}
    assert "triage_start_blocked" not in started_plan["epic_triage_meta"]
    assert injected == ["triage::observe"]
    assert entries[-1] == (
        "triage_start",
        {
            "source": "test",
            "injected_stage_ids": list(triage_lifecycle_mod.TRIAGE_STAGE_IDS),
        },
    )


def test_lifecycle_ensure_triage_started_uses_plan_aware_backlog_for_workflow_only_queue() -> None:
    saved: list[dict] = []
    services = SimpleNamespace(
        save_plan=lambda plan: saved.append(dict(plan)),
        append_log_entry=lambda *_a, **_k: None,
    )

    plan = {
        "queue_order": ["workflow::create-plan"],
        "plan_start_scores": {"strict": 86.0},
        "epic_triage_meta": {},
    }
    state = {
        "issues": {
            "smells::src/a.py::x": {
                "id": "smells::src/a.py::x",
                "detector": "smells",
                "status": "open",
                "file": "src/a.py",
                "tier": 3,
                "confidence": "high",
                "summary": "objective issue still in state",
                "detail": {},
            }
        },
        "dimension_scores": {},
        "subjective_assessments": {},
    }

    outcome = triage_lifecycle_mod.ensure_triage_started(
        plan,
        services=services,
        state=state,
        deps=triage_lifecycle_mod.TriageLifecycleDeps(
            has_triage_in_queue=lambda _plan: False,
            inject_triage_stages=lambda plan: plan.setdefault("queue_order", []).append("triage::observe"),
            colorize=lambda text, _style: text,
        ),
    )

    assert outcome.status == "started"
    assert "triage::observe" in plan["queue_order"]


def test_pipeline_context_helpers_load_prior_reports_directly() -> None:
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "observe": {"report": "observe report"},
                "reflect": {"report": "reflect report"},
                "organize": {"report": ""},
            }
        }
    }

    prior = orchestrator_pipeline_context_mod.load_prior_reports_from_plan(
        plan,
        ["observe", "reflect", "organize"],
    )

    assert prior == {"observe": "observe report", "reflect": "reflect report"}


def test_pipeline_completion_helpers_cover_success_and_failure_paths(
    monkeypatch,
    capsys,
) -> None:
    assert orchestrator_pipeline_completion_mod.is_full_stage_run(
        list(orchestrator_pipeline_completion_mod.STAGES)
    )
    assert not orchestrator_pipeline_completion_mod.is_full_stage_run(["observe"])
    assert orchestrator_pipeline_completion_mod.all_stage_results_successful(
        stages_to_run=["observe", "reflect"],
        stage_results={"observe": {"status": "confirmed"}, "reflect": {"status": "skipped"}},
    )
    assert not orchestrator_pipeline_completion_mod.all_stage_results_successful(
        stages_to_run=["observe"],
        stage_results={"observe": {"status": "failed"}},
    )

    orchestrator_pipeline_completion_mod.print_not_finalized_message("manual")
    out = capsys.readouterr().out
    assert "triage not finalized (manual)" in out

    plan_store = {"epic_triage_meta": {"triage_stages": {"observe": {"report": "observe"}}}}
    monkeypatch.setattr(
        orchestrator_pipeline_completion_mod,
        "validate_stage",
        lambda *_a, **_k: (True, ""),
    )
    monkeypatch.setattr(
        orchestrator_pipeline_completion_mod,
        "build_auto_attestation",
        lambda *_a, **_k: "attestation text",
    )

    def fake_confirm(_args, *, services):
        plan_store["epic_triage_meta"]["triage_stages"]["observe"]["confirmed_at"] = "now"

    monkeypatch.setattr(
        "desloppify.app.commands.plan.triage.confirmations.router.cmd_confirm_stage",
        fake_confirm,
    )

    ok, result, report = orchestrator_pipeline_completion_mod.validate_and_confirm_stage(
        stage="observe",
        args=argparse.Namespace(state=None),
        services=SimpleNamespace(load_plan=lambda: plan_store),
        triage_input=SimpleNamespace(),
        state={},
        repo_root=Path("."),
        stage_start=time.monotonic(),
        append_run_log=lambda _line: None,
    )
    assert ok is True
    assert result["status"] == "confirmed"
    assert report == "observe"

    monkeypatch.setattr(
        orchestrator_pipeline_completion_mod,
        "validate_stage",
        lambda *_a, **_k: (False, "broken"),
    )
    ok, result, report = orchestrator_pipeline_completion_mod.validate_and_confirm_stage(
        stage="reflect",
        args=argparse.Namespace(state=None),
        services=SimpleNamespace(load_plan=lambda: plan_store),
        triage_input=SimpleNamespace(),
        state={},
        repo_root=Path("."),
        stage_start=time.monotonic(),
        append_run_log=lambda _line: None,
    )
    assert ok is False
    assert result["status"] == "validation_failed"
    assert report == ""

    strategy = orchestrator_pipeline_completion_mod.build_completion_strategy(
        {
            "observe": {"report": "a" * 120},
            "reflect": {"report": "b" * 120},
        }
    )
    assert "[observe]" in strategy
    assert len(strategy) >= 200


def test_complete_pipeline_uses_completion_command(monkeypatch) -> None:
    state = {"completed": False}
    plan_before = {"epic_triage_meta": {}}

    monkeypatch.setattr(
        orchestrator_pipeline_completion_mod,
        "build_auto_attestation",
        lambda *_a, **_k: "attestation text",
    )

    def fake_complete(_args, *, services):
        state["completed"] = True

    monkeypatch.setattr(
        "desloppify.app.commands.plan.triage.stages.completion._cmd_triage_complete",
        fake_complete,
    )

    services = SimpleNamespace(
        load_plan=lambda: {
            "epic_triage_meta": (
                {"last_completed_at": "2026-03-10T18:00:00+00:00"}
                if state["completed"]
                else {}
            )
        }
    )

    completed = orchestrator_pipeline_completion_mod.complete_pipeline(
        args=argparse.Namespace(state=None),
        services=services,
        plan=plan_before,
        strategy="do it",
        triage_input=SimpleNamespace(),
    )
    assert completed is True


def test_orchestrator_claude_prints_instructions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(orchestrator_claude_mod, "ensure_triage_started", lambda *_a, **_k: None)
    services = SimpleNamespace(load_plan=lambda: {}, save_plan=lambda _plan: None)
    orchestrator_claude_mod.run_claude_orchestrator(argparse.Namespace(), services=services)
    out = capsys.readouterr().out
    assert "Claude triage orchestrator mode" in out


def test_orchestrator_observe_helpers_and_dry_run(monkeypatch, tmp_path, capsys) -> None:
    output_file = tmp_path / "observe.txt"
    output_file.write_text("batch output", encoding="utf-8")
    merged = orchestrator_observe_mod._merge_observe_outputs([(["naming"], output_file)])
    assert "Dimensions: naming" in merged

    monkeypatch.setattr(
        orchestrator_observe_mod,
        "group_issues_into_observe_batches",
        lambda _si: [(["naming"], [{"id": "1"}])],
    )
    monkeypatch.setattr(
        orchestrator_observe_mod,
        "build_observe_batch_prompt",
        lambda **_kwargs: "prompt",
    )

    result = orchestrator_observe_mod.run_observe(
        si=SimpleNamespace(),
        repo_root=tmp_path,
        prompts_dir=tmp_path / "prompts",
        output_dir=tmp_path / "out",
        logs_dir=tmp_path / "logs",
        timeout_seconds=60,
        dry_run=True,
    )
    assert result.status == "dry_run"
    assert result.reason == "dry_run"
    assert result.merged_output is None
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_orchestrator_sense_dry_run(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "scoped_manual_clusters_with_issues",
        lambda _plan, _state=None: ["cluster-a"],
    )
    monkeypatch.setattr(orchestrator_sense_mod, "triage_scoped_plan", lambda plan, _state=None: plan)
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_content_prompt",
        lambda **_kwargs: "content prompt",
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_structure_prompt",
        lambda **_kwargs: "structure prompt",
    )

    result = orchestrator_sense_mod.run_sense_check(
        plan={"clusters": {"cluster-a": {"issue_ids": ["id1"]}}},
        repo_root=tmp_path,
        prompts_dir=tmp_path / "prompts",
        output_dir=tmp_path / "out",
        logs_dir=tmp_path / "logs",
        timeout_seconds=60,
        dry_run=True,
    )
    assert result.status == "dry_run"
    assert result.reason == "dry_run"
    assert result.merged_output is None
    out = capsys.readouterr().out
    assert "[dry-run]" in out


def test_orchestrator_sense_non_dry_run_merges_outputs(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "scoped_manual_clusters_with_issues",
        lambda _plan, _state=None: ["cluster-a"],
    )
    monkeypatch.setattr(orchestrator_sense_mod, "triage_scoped_plan", lambda plan, _state=None: plan)
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_content_prompt",
        lambda **_kwargs: "content prompt",
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_structure_prompt",
        lambda **_kwargs: "structure prompt",
    )

    def fake_run_triage_stage(
        *,
        prompt,
        repo_root,
        output_file,
        log_file,
        timeout_seconds,
        validate_output_fn,
    ):
        del repo_root, log_file, timeout_seconds
        if "content" in prompt:
            output_file.write_text("content batch output", encoding="utf-8")
        else:
            output_file.write_text("structure batch output", encoding="utf-8")
        assert validate_output_fn(output_file)
        return codex_runner_mod.TriageStageRunResult(exit_code=0)

    monkeypatch.setattr(
        orchestrator_sense_mod,
        "run_triage_stage",
        fake_run_triage_stage,
    )

    def fake_run_parallel_batches(
        *,
        tasks,
        stage_label,
        batch_label_fn,
        append_run_log,
        heartbeat_seconds,
    ):
        del stage_label, batch_label_fn, append_run_log, heartbeat_seconds
        for task in tasks.values():
            assert task().ok
        return []

    monkeypatch.setattr(orchestrator_sense_mod, "run_parallel_batches", fake_run_parallel_batches)

    prompts_dir = tmp_path / "prompts"
    output_dir = tmp_path / "out"
    logs_dir = tmp_path / "logs"
    prompts_dir.mkdir()
    output_dir.mkdir()
    logs_dir.mkdir()

    result = orchestrator_sense_mod.run_sense_check(
        plan={"clusters": {"cluster-a": {"issue_ids": ["id1"]}}},
        repo_root=tmp_path,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        timeout_seconds=60,
        dry_run=False,
    )

    assert result.ok
    assert result.merged_output is not None
    assert "content:cluster-a" in result.merged_output
    assert "structure" in result.merged_output
    out = capsys.readouterr().out
    assert "merged 3 batch outputs" in out


def test_orchestrator_sense_non_dry_run_reports_parallel_failures(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "scoped_manual_clusters_with_issues",
        lambda _plan, _state=None: ["cluster-a"],
    )
    monkeypatch.setattr(orchestrator_sense_mod, "triage_scoped_plan", lambda plan, _state=None: plan)
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_content_prompt",
        lambda **_kwargs: "content prompt",
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_structure_prompt",
        lambda **_kwargs: "structure prompt",
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "run_parallel_batches",
        lambda **_kwargs: [1],
    )

    prompts_dir = tmp_path / "prompts"
    output_dir = tmp_path / "out"
    logs_dir = tmp_path / "logs"
    prompts_dir.mkdir()
    output_dir.mkdir()
    logs_dir.mkdir()

    result = orchestrator_sense_mod.run_sense_check(
        plan={"clusters": {"cluster-a": {"issue_ids": ["id1"]}}},
        repo_root=tmp_path,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        timeout_seconds=60,
        dry_run=False,
    )

    assert result.status == "failed"
    assert result.reason == "parallel_execution_failed"
    assert result.merged_output is None
    out = capsys.readouterr().out
    assert "batch(es) failed" in out


def test_orchestrator_sense_apply_updates_sequences_and_reloads_plan(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "scoped_manual_clusters_with_issues",
        lambda _plan, _state=None: ["cluster-a"],
    )
    monkeypatch.setattr(orchestrator_sense_mod, "triage_scoped_plan", lambda plan, _state=None: plan)

    content_modes: list[str] = []
    structure_modes: list[str] = []
    structure_versions: list[str] = []
    reload_calls = {"count": 0}
    phase_order: list[str] = []

    def fake_content_prompt(
        *,
        cluster_name,
        plan,
        repo_root,
        policy_block,
        mode,
        cli_command,
    ):
        del cluster_name, plan, repo_root, policy_block, cli_command
        content_modes.append(mode)
        return "content prompt"

    def fake_structure_prompt(*, plan, repo_root, mode, cli_command):
        del repo_root, cli_command
        structure_modes.append(mode)
        structure_versions.append(str(plan.get("version", "missing")))
        return "structure prompt"

    def fake_run_triage_stage(
        *,
        prompt,
        repo_root,
        output_file,
        log_file,
        timeout_seconds,
        validate_output_fn,
    ):
        del repo_root, log_file, timeout_seconds
        if "content" in prompt:
            output_file.write_text("content batch output", encoding="utf-8")
        else:
            output_file.write_text("structure batch output", encoding="utf-8")
        assert validate_output_fn(output_file)
        return codex_runner_mod.TriageStageRunResult(exit_code=0)

    def fake_run_parallel_batches(
        *,
        tasks,
        stage_label,
        batch_label_fn,
        append_run_log,
        heartbeat_seconds,
    ):
        del stage_label, append_run_log, heartbeat_seconds
        labels = [batch_label_fn(i) for i in tasks]
        if any(label.startswith("content:") for label in labels):
            phase_order.append("content")
        if "structure" in labels:
            phase_order.append("structure")
        if "value" in labels:
            phase_order.append("value")
        for task in tasks.values():
            assert task().ok
        return []

    def fake_reload_plan():
        reload_calls["count"] += 1
        return {
            "version": "after-content",
            "clusters": {"cluster-a": {"issue_ids": ["id1"], "action_steps": []}},
        }

    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_content_prompt",
        fake_content_prompt,
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_structure_prompt",
        fake_structure_prompt,
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "build_sense_check_value_prompt",
        lambda **_kwargs: "value prompt",
    )
    monkeypatch.setattr(orchestrator_sense_mod, "run_triage_stage", fake_run_triage_stage)
    monkeypatch.setattr(orchestrator_sense_mod, "run_parallel_batches", fake_run_parallel_batches)

    prompts_dir = tmp_path / "prompts"
    output_dir = tmp_path / "out"
    logs_dir = tmp_path / "logs"
    prompts_dir.mkdir()
    output_dir.mkdir()
    logs_dir.mkdir()

    result = orchestrator_sense_mod.run_sense_check(
        plan={
            "version": "before-content",
            "clusters": {"cluster-a": {"issue_ids": ["id1"], "action_steps": []}},
        },
        repo_root=tmp_path,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        timeout_seconds=60,
        dry_run=False,
        cli_command=_fake_cli_command(),
        apply_updates=True,
        reload_plan=fake_reload_plan,
    )

    assert result.ok
    assert content_modes == ["self_record"]
    assert structure_modes == ["self_record", "self_record"]
    assert structure_versions[-1] == "after-content"
    assert reload_calls["count"] == 2
    assert phase_order == ["content", "structure", "value"]


def test_orchestrator_sense_scopes_content_batches_to_active_triage(monkeypatch, tmp_path) -> None:
    content_clusters: list[str] = []
    structure_versions: list[dict] = []

    monkeypatch.setattr(
        orchestrator_sense_mod,
        "scoped_manual_clusters_with_issues",
        lambda _plan, _state=None: ["current"],
    )
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "triage_scoped_plan",
        lambda plan, _state=None: {
            **plan,
            "clusters": {"current": plan["clusters"]["current"]},
        },
    )

    def fake_content_prompt(*, cluster_name, plan, **_kwargs):
        content_clusters.append(cluster_name)
        assert set(plan.get("clusters", {})) == {"current"}
        return "content prompt"

    def fake_structure_prompt(*, plan, **_kwargs):
        structure_versions.append(plan)
        assert set(plan.get("clusters", {})) == {"current"}
        return "structure prompt"

    monkeypatch.setattr(orchestrator_sense_mod, "build_sense_check_content_prompt", fake_content_prompt)
    monkeypatch.setattr(orchestrator_sense_mod, "build_sense_check_structure_prompt", fake_structure_prompt)
    monkeypatch.setattr(orchestrator_sense_mod, "build_sense_check_value_prompt", lambda **_kwargs: "value prompt")

    def fake_run_triage_stage(
        *,
        prompt,
        repo_root,
        output_file,
        log_file,
        timeout_seconds,
        validate_output_fn,
    ):
        del prompt, repo_root, log_file, timeout_seconds
        output_file.write_text("ok", encoding="utf-8")
        assert validate_output_fn(output_file)
        return codex_runner_mod.TriageStageRunResult(exit_code=0)

    monkeypatch.setattr(orchestrator_sense_mod, "run_triage_stage", fake_run_triage_stage)
    monkeypatch.setattr(
        orchestrator_sense_mod,
        "run_parallel_batches",
        lambda **kwargs: [task() for task in kwargs["tasks"].values()] and [],
    )

    prompts_dir = tmp_path / "prompts"
    output_dir = tmp_path / "out"
    logs_dir = tmp_path / "logs"
    prompts_dir.mkdir()
    output_dir.mkdir()
    logs_dir.mkdir()

    result = orchestrator_sense_mod.run_sense_check(
        plan={
            "clusters": {
                "current": {"issue_ids": ["review::current::issue"], "action_steps": []},
                "legacy": {"issue_ids": ["review::legacy::issue"], "action_steps": []},
            }
        },
        state={
            "issues": {
                "review::current::issue": {"status": "open", "detector": "review"},
                "review::legacy::issue": {"status": "open", "detector": "review"},
            }
        },
        repo_root=tmp_path,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        timeout_seconds=60,
        dry_run=False,
    )

    assert result.ok
    assert content_clusters == ["current"]
    assert len(structure_versions) == 1


def test_default_sense_handler_enables_apply_update_mode(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_sense_check(**kwargs):
        captured.update(kwargs)
        return codex_runner_mod.TriageStageRunResult(exit_code=0)

    monkeypatch.setattr(
        orchestrator_pipeline_execution_mod,
        "run_sense_check",
        fake_run_sense_check,
    )

    context = SimpleNamespace(
        plan={"clusters": {}},
        repo_root=tmp_path,
        prompts_dir=tmp_path / "prompts",
        output_dir=tmp_path / "out",
        logs_dir=tmp_path / "logs",
        timeout_seconds=60,
        dry_run=False,
        cli_command=_fake_cli_command(),
        append_run_log=lambda _line: None,
        services=SimpleNamespace(load_plan=lambda: {"clusters": {}}),
        state=None,
    )
    handler = orchestrator_pipeline_execution_mod.DEFAULT_STAGE_HANDLERS["sense-check"]
    assert handler.run_parallel is not None

    result = handler.run_parallel(context)
    assert result.ok
    assert captured["cli_command"] == _fake_cli_command()
    assert captured["apply_updates"] is True
    assert callable(captured["reload_plan"])


def test_orchestrator_pipeline_summary_writer(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    messages: list[str] = []

    orchestrator_pipeline_mod.write_triage_run_summary(
        run_dir,
        stamp="20260309_120000",
        stages=["observe"],
        stage_results={"observe": {"status": "confirmed"}},
        append_run_log=messages.append,
    )

    summary_path = run_dir / "run_summary.json"
    assert summary_path.exists()
    text = summary_path.read_text(encoding="utf-8")
    assert '"runner": "codex"' in text
    assert messages


def test_orchestrator_pipeline_completion_guards() -> None:
    assert orchestrator_pipeline_mod._is_full_stage_run(
        ["observe", "reflect", "organize", "enrich", "sense-check"]
    ) is True
    assert orchestrator_pipeline_mod._is_full_stage_run(["observe", "reflect"]) is False

    assert orchestrator_pipeline_mod._all_stage_results_successful(
        stages_to_run=["observe", "reflect"],
        stage_results={
            "observe": {"status": "confirmed"},
            "reflect": {"status": "skipped"},
        },
    ) is True
    assert orchestrator_pipeline_mod._all_stage_results_successful(
        stages_to_run=["observe", "reflect"],
        stage_results={
            "observe": {"status": "confirmed"},
            "reflect": {"status": "failed"},
        },
    ) is False


def test_orchestrator_pipeline_summary_writer_includes_finalization_fields(tmp_path) -> None:
    run_dir = tmp_path / "run2"
    run_dir.mkdir(parents=True)
    messages: list[str] = []

    orchestrator_pipeline_mod.write_triage_run_summary(
        run_dir,
        stamp="20260309_120001",
        stages=["observe", "reflect"],
        stage_results={"observe": {"status": "confirmed"}},
        append_run_log=messages.append,
        finalized=False,
        finalization_reason="partial_stage_run",
    )

    summary_path = run_dir / "run_summary.json"
    text = summary_path.read_text(encoding="utf-8")
    assert '"finalized": false' in text
    assert '"finalization_reason": "partial_stage_run"' in text


def test_orchestrator_pipeline_entrypoint_is_exposed() -> None:
    assert callable(orchestrator_pipeline_mod.run_codex_pipeline)


def test_orchestrator_pipeline_writes_exact_cli_helper(tmp_path: Path) -> None:
    helper = orchestrator_pipeline_mod._write_desloppify_cli_helper(tmp_path)
    text = helper.read_text(encoding="utf-8")
    assert helper.exists()
    assert helper.name == _expected_helper_name()
    assert "-m desloppify.cli" in text
    if os.name == "nt":
        assert text.startswith("@echo off")
        assert 'set "PYTHONPATH=' in text
    else:
        assert helper.stat().st_mode & 0o111
        assert "PYTHONPATH=" in text


def test_load_prior_reports_from_plan_uses_existing_stage_reports() -> None:
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "observe": {"report": "observe report"},
                "reflect": {"report": "reflect report"},
                "organize": {"report": ""},
            }
        }
    }

    prior = orchestrator_pipeline_mod._load_prior_reports_from_plan(plan)
    assert prior == {
        "observe": "observe report",
        "reflect": "reflect report",
    }


def test_execute_stage_records_output_only_reflect_report(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    plan_store = {"epic_triage_meta": {"triage_stages": {}}}
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    monkeypatch.setattr(orchestrator_pipeline_mod, "build_stage_prompt", lambda *args, **kwargs: "prompt")

    def fake_run_triage_stage(*, prompt, repo_root, output_file, log_file, timeout_seconds):
        del prompt, repo_root, log_file, timeout_seconds
        output_file.write_text("Reflect analysis report with enough detail.", encoding="utf-8")
        return codex_runner_mod.TriageStageRunResult(exit_code=0)

    monkeypatch.setattr(orchestrator_pipeline_mod, "run_triage_stage", fake_run_triage_stage)
    monkeypatch.setitem(
        orchestrator_pipeline_mod._STAGE_HANDLERS,
        "reflect",
        orchestrator_pipeline_mod.StageHandler(
            record_report=lambda report, _args, _services: (
                captured.setdefault("report", report),
                plan_store["epic_triage_meta"]["triage_stages"].update(
                    {"reflect": {"report": report}}
                ),
            ),
            prompt_mode="output_only",
        ),
    )

    result = orchestrator_pipeline_execution_mod.execute_stage(
        _make_stage_context(
            tmp_path,
            stage="reflect",
            services=SimpleNamespace(load_plan=lambda: plan_store),
        ),
        handlers=orchestrator_pipeline_mod._STAGE_HANDLERS,
        dependencies=orchestrator_pipeline_mod._stage_execution_dependencies(),
    )

    assert result.status == "ready"
    assert result.payload == {}
    assert captured["report"] == "Reflect analysis report with enough detail."


def test_execute_stage_uses_self_record_mode_for_organize(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    def fake_build_stage_prompt(stage, triage_input, prior_reports, *, repo_root, mode, cli_command, stages_data=None):
        del triage_input, prior_reports, repo_root, stages_data
        captured["stage"] = stage
        captured["mode"] = mode
        captured["cli_command"] = cli_command
        return "prompt"

    def fake_run_triage_stage(*, prompt, repo_root, output_file, log_file, timeout_seconds):
        del prompt, repo_root, log_file, timeout_seconds
        output_file.write_text("Organize summary.", encoding="utf-8")
        return codex_runner_mod.TriageStageRunResult(exit_code=0)

    monkeypatch.setattr(orchestrator_pipeline_mod, "build_stage_prompt", fake_build_stage_prompt)
    monkeypatch.setattr(orchestrator_pipeline_mod, "run_triage_stage", fake_run_triage_stage)

    result = orchestrator_pipeline_execution_mod.execute_stage(
        _make_stage_context(
            tmp_path,
            stage="organize",
            services=SimpleNamespace(),
            prior_reports={"reflect": "report"},
        ),
        handlers=orchestrator_pipeline_mod._STAGE_HANDLERS,
        dependencies=orchestrator_pipeline_mod._stage_execution_dependencies(),
    )

    assert result.status == "ready"
    assert result.payload == {}
    assert captured["stage"] == "organize"
    assert captured["mode"] == "self_record"
    assert captured["cli_command"] == _fake_cli_command()


def test_preflight_stage_allows_self_record_organize_before_ledger_materializes() -> None:
    log_lines: list[str] = []
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "reflect": {
                    "report": '## Coverage Ledger\n- deadbeef -> cluster "state-cleanup"\n',
                    "disposition_ledger": [
                        {
                            "issue_id": "review::src/a.py::deadbeef",
                            "decision": "cluster",
                            "target": "state-cleanup",
                        }
                    ],
                }
            }
        },
        "clusters": {},
        "skipped": {},
    }

    ok, reason = orchestrator_pipeline_execution_mod.preflight_stage(
        stage="organize",
        prompt_mode="self_record",
        plan=plan,
        triage_input=SimpleNamespace(open_issues={"review::src/a.py::deadbeef": {}}),
        dry_run=False,
        append_run_log=log_lines.append,
        validate_reflect_issue_accounting=lambda **_kwargs: (True, set(), [], []),
    )

    assert ok is True
    assert reason is None
    assert log_lines == []


def test_preflight_stage_blocks_output_only_organize_when_ledger_unapplied() -> None:
    log_lines: list[str] = []
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "reflect": {
                    "report": '## Coverage Ledger\n- deadbeef -> cluster "state-cleanup"\n',
                    "disposition_ledger": [
                        {
                            "issue_id": "review::src/a.py::deadbeef",
                            "decision": "cluster",
                            "target": "state-cleanup",
                        }
                    ],
                }
            }
        },
        "clusters": {},
        "skipped": {},
    }

    ok, reason = orchestrator_pipeline_execution_mod.preflight_stage(
        stage="organize",
        prompt_mode="output_only",
        plan=plan,
        triage_input=SimpleNamespace(open_issues={"review::src/a.py::deadbeef": {}}),
        dry_run=False,
        append_run_log=log_lines.append,
        validate_reflect_issue_accounting=lambda **_kwargs: (True, set(), [], []),
    )

    assert ok is False
    assert reason == "reflect_ledger_mismatch(count=1 types=cluster)"
    assert log_lines == [
        "stage-preflight-failed stage=organize reason=reflect_ledger_mismatch(count=1 types=cluster)"
    ]


def test_execute_stage_allows_organize_dry_run_without_persisted_reflect(
    tmp_path: Path,
) -> None:
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    dependencies = orchestrator_pipeline_execution_mod.StageExecutionDependencies(
        build_stage_prompt=lambda *_args, **_kwargs: "organize prompt",
        run_triage_stage=orchestrator_pipeline_mod.run_triage_stage,
        read_stage_output=orchestrator_pipeline_execution_mod.read_stage_output,
        analyze_reflect_issue_accounting=orchestrator_pipeline_mod._analyze_reflect_issue_accounting,
        validate_reflect_issue_accounting=lambda **_kwargs: (
            False,
            set(),
            ["review::x::deadbeef"],
            [],
        ),
    )

    result = orchestrator_pipeline_execution_mod.execute_stage(
        _make_stage_context(
            tmp_path,
            stage="organize",
            dry_run=True,
            services=SimpleNamespace(),
            plan={
                "epic_triage_meta": {
                    "triage_stages": {"reflect": {"report": "bad reflect blueprint"}}
                }
            },
            triage_input=SimpleNamespace(
                open_issues={"review::x::deadbeef": {}},
                new_since_last=set(),
            ),
            prior_reports={"reflect": "bad reflect blueprint"},
        ),
        handlers=orchestrator_pipeline_mod._STAGE_HANDLERS,
        dependencies=dependencies,
    )

    assert result.status == "dry_run"
    assert result.payload == {"status": "dry_run"}


def test_execute_stage_blocks_sense_check_when_enrich_is_not_confirmed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    def fail_if_sense_runs(**_kwargs):
        raise AssertionError("sense-check runner should not launch when enrich is unconfirmed")

    monkeypatch.setattr(
        orchestrator_pipeline_execution_mod,
        "run_sense_check",
        fail_if_sense_runs,
    )

    log_lines: list[str] = []
    result = orchestrator_pipeline_execution_mod.execute_stage(
        _make_stage_context(
            tmp_path,
            stage="sense-check",
            services=SimpleNamespace(load_plan=lambda: {"epic_triage_meta": {"triage_stages": {}}}),
            plan={
                "epic_triage_meta": {
                    "triage_stages": {
                        "enrich": {
                            "report": "enrich report exists but has not been confirmed yet",
                        }
                    }
                }
            },
            triage_input=SimpleNamespace(open_issues={}),
            prior_reports={"enrich": "enrich report exists but has not been confirmed yet"},
            append_run_log=log_lines.append,
        ),
        handlers=orchestrator_pipeline_mod._STAGE_HANDLERS,
        dependencies=orchestrator_pipeline_mod._stage_execution_dependencies(),
    )

    assert result.status == "failed"
    assert result.payload["error"] == "enrich_not_confirmed"


def test_execute_stage_blocks_organize_when_reflect_accounting_is_invalid_in_real_run(
    tmp_path: Path,
) -> None:
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    dependencies = orchestrator_pipeline_execution_mod.StageExecutionDependencies(
        build_stage_prompt=orchestrator_pipeline_mod.build_stage_prompt,
        run_triage_stage=orchestrator_pipeline_mod.run_triage_stage,
        read_stage_output=orchestrator_pipeline_execution_mod.read_stage_output,
        analyze_reflect_issue_accounting=orchestrator_pipeline_mod._analyze_reflect_issue_accounting,
        validate_reflect_issue_accounting=lambda **_kwargs: (
            False,
            set(),
            ["review::x::deadbeef"],
            [],
        ),
    )

    result = orchestrator_pipeline_execution_mod.execute_stage(
        _make_stage_context(
            tmp_path,
            stage="organize",
            dry_run=False,
            services=SimpleNamespace(),
            plan={
                "epic_triage_meta": {
                    "triage_stages": {"reflect": {"report": "bad reflect blueprint"}}
                }
            },
            triage_input=SimpleNamespace(
                open_issues={"review::x::deadbeef": {}},
                new_since_last=set(),
            ),
            prior_reports={"reflect": "bad reflect blueprint"},
        ),
        handlers=orchestrator_pipeline_mod._STAGE_HANDLERS,
        dependencies=dependencies,
    )

    assert result.status == "failed"
    assert result.payload["error"].startswith("reflect_accounting_invalid")


def test_repair_reflect_report_if_needed_repairs_missing_hashes(monkeypatch, tmp_path: Path) -> None:
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    repaired_report = """
## Coverage Ledger
- aaaabbbb -> cluster "alpha"
- ccccdddd -> skip "false-positive"

## Cluster Blueprint
Cluster "alpha" owns the actual code changes.

## Execution Order
1. alpha
"""

    dependencies = orchestrator_pipeline_execution_mod.StageExecutionDependencies(
        build_stage_prompt=lambda *_a, **_k: "repair prompt",
        run_triage_stage=lambda **_kwargs: codex_runner_mod.TriageStageRunResult(exit_code=0),
        read_stage_output=lambda _path: repaired_report,
        analyze_reflect_issue_accounting=orchestrator_pipeline_mod._analyze_reflect_issue_accounting,
        validate_reflect_issue_accounting=orchestrator_pipeline_mod._validate_reflect_issue_accounting,
    )

    report, error = orchestrator_pipeline_execution_mod.repair_reflect_report_if_needed(
        report=(
            "## Coverage Ledger\n"
            '- aaaabbbb -> cluster "alpha"\n\n'
            "## Cluster Blueprint\n"
            "Cluster alpha is the main work."
        ),
        triage_input=SimpleNamespace(
            open_issues={
                "review::src/a.ts::alpha::aaaabbbb": {},
                "review::src/b.ts::beta::ccccdddd": {},
            }
        ),
        prior_reports={"observe": "Observed the issues carefully."},
        repo_root=tmp_path,
        prompts_dir=tmp_path / "prompts",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        cli_command=_fake_cli_command(),
        timeout_seconds=30,
        append_run_log=lambda _line: None,
        dependencies=dependencies,
    )

    assert error is None
    assert report == repaired_report


def test_pipeline_execution_helpers_cover_leaf_paths(monkeypatch, tmp_path: Path) -> None:
    missing_output = orchestrator_pipeline_execution_mod.read_stage_output(
        tmp_path / "missing.txt"
    )
    assert missing_output == ""

    report_file = tmp_path / "report.txt"
    report_file.write_text("  report text  ", encoding="utf-8")
    assert orchestrator_pipeline_execution_mod.read_stage_output(report_file) == "report text"

    deps = orchestrator_pipeline_execution_mod.default_stage_execution_dependencies()
    assert callable(deps.build_stage_prompt)
    assert callable(deps.run_triage_stage)

    assert orchestrator_pipeline_execution_mod.stage_report_recorded(
        {"epic_triage_meta": {"triage_stages": {"reflect": {"report": "ok"}}}},
        "reflect",
    )

    log_lines: list[str] = []
    ok, reason = orchestrator_pipeline_execution_mod.preflight_stage(
        stage="sense-check",
        plan={"epic_triage_meta": {"triage_stages": {}}},
        triage_input=SimpleNamespace(open_issues={}),
        dry_run=False,
        append_run_log=log_lines.append,
        validate_reflect_issue_accounting=lambda **_kwargs: (True, set(), [], []),
    )
    assert ok is False
    assert reason == "enrich_not_confirmed"
    assert log_lines == [
        "stage-preflight-failed stage=sense-check reason=enrich_not_confirmed"
    ]

    prompt = orchestrator_pipeline_execution_mod.build_reflect_repair_prompt(
        triage_input=SimpleNamespace(open_issues={}),
        prior_reports={},
        repo_root=Path("."),
        cli_command="desloppify",
        original_report="old report",
        missing_ids=["review::src/a.py::deadbeef"],
        duplicate_ids=["review::src/b.py::facefeed"],
        build_stage_prompt_fn=lambda *_a, **_k: "base prompt",
    )
    assert "Missing hashes: deadbeef" in prompt
    assert "Duplicated hashes: facefeed" in prompt
    assert "Previous Reflect Report" in prompt

    ok, reason = orchestrator_pipeline_execution_mod.preflight_stage(
        stage="organize",
        plan={"epic_triage_meta": {"triage_stages": {}}},
        triage_input=SimpleNamespace(open_issues={"review::x::deadbeef": {}}),
        dry_run=True,
        append_run_log=log_lines.append,
        validate_reflect_issue_accounting=lambda **_kwargs: (
            False,
            set(),
            ["review::x::deadbeef"],
            [],
        ),
    )
    assert ok is True
    assert reason is None

    context = orchestrator_pipeline_context_mod.StageRunContext(
        stage="observe",
        stage_start=time.monotonic(),
        args=argparse.Namespace(state=None),
        services=SimpleNamespace(load_plan=lambda: {}),
        plan={"epic_triage_meta": {"triage_stages": {"observe": {"report": "done"}}}},
        triage_input=SimpleNamespace(),
        prior_reports={},
        repo_root=tmp_path,
        prompts_dir=tmp_path / "prompts",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        cli_command="/tmp/run.sh",
        timeout_seconds=60,
        dry_run=True,
        append_run_log=lambda _line: None,
    )
    context.prompts_dir.mkdir()
    context.output_dir.mkdir()
    context.logs_dir.mkdir()

    parallel_result = orchestrator_pipeline_execution_mod._execute_parallel_stage(
        context=context,
        stage="observe",
        handler=orchestrator_pipeline_execution_mod.StageHandler(
            run_parallel=lambda _context: codex_runner_mod.TriageStageRunResult(
                exit_code=0,
                merged_output="parallel report",
            ),
            record_report=lambda report, _args, _services: report == "parallel report",
        ),
    )
    assert parallel_result.status == "ready"
    assert parallel_result.payload == {}
    assert parallel_result.used_parallel is True

    prompt_text, stages_data = orchestrator_pipeline_execution_mod._build_subprocess_prompt(
        context=context,
        stage="observe",
        prompt_mode="output_only",
        dependencies=orchestrator_pipeline_execution_mod.StageExecutionDependencies(
            build_stage_prompt=lambda *_a, **_k: "prompt body",
            run_triage_stage=lambda **_kwargs: codex_runner_mod.TriageStageRunResult(exit_code=0),
            read_stage_output=lambda _path: "",
            analyze_reflect_issue_accounting=lambda **_kwargs: (set(), [], []),
            validate_reflect_issue_accounting=lambda **_kwargs: (True, set(), [], []),
        ),
    )
    assert prompt_text == "prompt body"
    assert stages_data == {"observe": {"report": "done"}}
    assert (context.prompts_dir / "observe.md").exists()

    subprocess_result = orchestrator_pipeline_execution_mod._run_subprocess_stage(
        context=context,
        stage="observe",
        prompt="prompt body",
        dependencies=orchestrator_pipeline_execution_mod.StageExecutionDependencies(
            build_stage_prompt=lambda *_a, **_k: "prompt body",
            run_triage_stage=lambda **_kwargs: codex_runner_mod.TriageStageRunResult(exit_code=0),
            read_stage_output=lambda _path: "",
            analyze_reflect_issue_accounting=lambda **_kwargs: (set(), [], []),
            validate_reflect_issue_accounting=lambda **_kwargs: (True, set(), [], []),
        ),
    )
    assert subprocess_result.status == "dry_run"
    assert subprocess_result.payload == {"status": "dry_run"}
    assert subprocess_result.output_file is None
    assert subprocess_result.elapsed_seconds is None


def test_execute_stage_fails_when_handler_does_not_persist_stage(monkeypatch, tmp_path: Path) -> None:
    for dirname in ("prompts", "output", "logs"):
        (tmp_path / dirname).mkdir()

    monkeypatch.setattr(orchestrator_pipeline_mod, "build_stage_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        orchestrator_pipeline_mod,
        "run_triage_stage",
        lambda **_kwargs: codex_runner_mod.TriageStageRunResult(exit_code=0),
    )
    monkeypatch.setitem(
        orchestrator_pipeline_mod._STAGE_HANDLERS,
        "reflect",
        orchestrator_pipeline_mod.StageHandler(record_report=lambda *_a, **_k: None),
    )

    services = SimpleNamespace(load_plan=lambda: {"epic_triage_meta": {"triage_stages": {}}})

    result = orchestrator_pipeline_execution_mod.execute_stage(
        _make_stage_context(
            tmp_path,
            stage="reflect",
            services=services,
            plan={"epic_triage_meta": {"triage_stages": {"observe": {"report": "ok"}}}},
            triage_input=SimpleNamespace(open_issues={}),
            prior_reports={"observe": "ok"},
        ),
        handlers=orchestrator_pipeline_mod._STAGE_HANDLERS,
        dependencies=orchestrator_pipeline_execution_mod.StageExecutionDependencies(
            build_stage_prompt=lambda *_a, **_k: "prompt",
            run_triage_stage=lambda **_kwargs: codex_runner_mod.TriageStageRunResult(exit_code=0),
            read_stage_output=lambda _path: "x" * 120,
            analyze_reflect_issue_accounting=orchestrator_pipeline_mod._analyze_reflect_issue_accounting,
            validate_reflect_issue_accounting=orchestrator_pipeline_mod._validate_reflect_issue_accounting,
        ),
    )

    assert result.status == "failed"
    assert result.payload["error"] == "stage_not_recorded"


def test_run_codex_pipeline_raises_on_stage_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(orchestrator_pipeline_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(orchestrator_pipeline_mod, "run_stamp", lambda: "20260309_151500")
    monkeypatch.setattr(
        orchestrator_pipeline_mod,
        "_write_desloppify_cli_helper",
        lambda run_dir: run_dir / _expected_helper_name(),
    )
    monkeypatch.setattr(
        orchestrator_pipeline_mod,
        "execute_stage_impl",
        lambda *_args, **_kwargs: StageExecutionResult(status="failed", payload={"status": "failed", "error": "boom"}),
    )

    services = SimpleNamespace(
        load_plan=lambda: {"epic_triage_meta": {"triage_stages": {}}},
        command_runtime=lambda _args: SimpleNamespace(state={}),
        collect_triage_input=lambda _plan, _state: SimpleNamespace(open_issues={}, resolved_issues={}),
    )
    monkeypatch.setattr(
        orchestrator_pipeline_mod,
        "default_triage_services",
        lambda: services,
    )
    monkeypatch.setattr(orchestrator_pipeline_mod, "ensure_triage_started", lambda *_a, **_k: None)

    with pytest.raises(CommandError) as excinfo:
        orchestrator_pipeline_mod.run_codex_pipeline(
            argparse.Namespace(stage_timeout_seconds=30, dry_run=False, state=None),
            stages_to_run=["organize"],
            services=services,
        )

    assert excinfo.value.exit_code == 1
    assert "triage stage failed: organize" in excinfo.value.message
