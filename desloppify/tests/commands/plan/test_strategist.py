"""Tests for strategize stage lifecycle and compatibility wiring."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import desloppify.app.commands.plan.triage.stages.strategize as strategize_mod
from desloppify.app.cli_support.parser_groups_plan_impl_sections_triage_commit_scan import (
    _add_triage_subparser,
)
from desloppify.app.commands.plan.triage.stages.observe import cmd_stage_observe
from desloppify.app.commands.plan.triage.workflow import run_triage_workflow
from desloppify.engine._plan.constants import (
    TRIAGE_STAGE_IDS,
    confirmed_triage_stage_names,
    recorded_unconfirmed_triage_stage_names,
)
from desloppify.engine._plan.schema import empty_plan, validate_plan
from desloppify.engine._plan.sync.triage import _inject_pending_triage_stages
from desloppify.engine.plan_triage import compute_triage_progress


def _services(plan: dict, state: dict):
    return SimpleNamespace(
        command_runtime=lambda _args: SimpleNamespace(state=state),
        load_plan=lambda: plan,
        save_plan=lambda _plan: None,
        append_log_entry=lambda *_args, **_kwargs: None,
    )


def test_cmd_stage_strategize_persists_briefing_and_auto_confirms(monkeypatch, capsys) -> None:
    plan = {"queue_order": list(TRIAGE_STAGE_IDS), "epic_triage_meta": {"triage_stages": {}}, "execution_log": [], "commit_log": []}
    state = {"scan_count": 1, "scan_history": [], "dimension_scores": {}, "work_items": {}}
    events: list[dict] = []

    monkeypatch.setattr(strategize_mod, "load_progression", lambda: [])
    monkeypatch.setattr(strategize_mod, "append_progression_event", lambda event: events.append(event))
    monkeypatch.setattr(
        strategize_mod,
        "collect_strategist_input",
        lambda *_args, **_kwargs: SimpleNamespace(
            rework_loops=[],
            score_trajectory=SimpleNamespace(trend="stable"),
            debt_trajectory=SimpleNamespace(trend="stable"),
        ),
    )

    strategize_mod.cmd_stage_strategize(
        argparse.Namespace(
            report=(
                '{"score_trend":"stable","debt_trend":"stable",'
                '"executive_summary":"'
                + ("x" * 120)
                + '","observe_guidance":"'
                + ("y" * 60)
                + '","reflect_guidance":"'
                + ("z" * 60)
                + '","organize_guidance":"'
                + ("o" * 60)
                + '","sense_check_guidance":"'
                + ("s" * 60)
                + '","focus_dimensions":[{"name":"naming","reason":"high headroom","trend":"stagnant","headroom":20}],'
                '"anti_patterns":[{"type":"rework","description":"loop","evidence":["same files"]}]}'
            )
        ),
        services=_services(plan, state),
    )

    briefing = plan["epic_triage_meta"]["strategist_briefing"]
    record = plan["epic_triage_meta"]["triage_stages"]["strategize"]
    assert briefing["score_trend"] == "stable"
    assert record["confirmed_at"]
    assert record["confirmed_text"] == "auto-confirmed"
    assert events and events[0]["event_type"] == "strategist_complete"
    assert "auto-confirmed" in capsys.readouterr().out


def test_create_strategic_work_items_preserves_matching_skipped_strategy_id() -> None:
    """Generated reports must not silently revive an explicitly skipped ID."""
    plan = empty_plan()
    plan["skipped"] = {
        "strategy::repeat": {
            "issue_id": "strategy::repeat",
            "kind": "false_positive",
        }
    }
    state = {"work_items": {}}
    strategic_issues = [
        {
            "identifier": "repeat",
            "summary": "Fresh strategic concern",
            "priority": "high",
            "recommendation": "Work the newly observed concern as a bounded packet.",
            "dimensions_affected": ["naming"],
        }
    ]

    strategize_mod._create_strategic_work_items(
        state,
        plan,
        strategic_issues,
    )

    validate_plan(plan)
    assert "strategy::repeat" not in plan["queue_order"]
    assert "strategy::repeat" in plan["skipped"]
    assert "strategy::repeat" not in state["work_items"]


def test_create_strategic_work_items_queues_new_strategy_id() -> None:
    plan = empty_plan()
    state = {"work_items": {}}
    strategic_issues = [
        {
            "identifier": "fresh",
            "summary": "Fresh strategic concern",
            "priority": "high",
            "recommendation": "Work the newly observed concern as a bounded packet.",
            "dimensions_affected": ["naming"],
        }
    ]

    strategize_mod._create_strategic_work_items(
        state,
        plan,
        strategic_issues,
    )

    validate_plan(plan)
    assert plan["queue_order"] == ["strategy::fresh"]
    assert state["work_items"]["strategy::fresh"]["status"] == "open"


def test_observe_is_blocked_until_strategize_is_recorded(capsys) -> None:
    plan = {"queue_order": list(TRIAGE_STAGE_IDS), "epic_triage_meta": {"triage_stages": {}}, "execution_log": [], "commit_log": []}
    state = {"work_items": {}}

    progress = compute_triage_progress(plan["epic_triage_meta"]["triage_stages"])
    assert progress.current_stage == "strategize"

    cmd_stage_observe(
        argparse.Namespace(report="x" * 120, attestation=None),
        services=_services(plan, state),
        has_triage_in_queue_fn=lambda _plan: True,
        inject_triage_stages_fn=lambda _plan: None,
    )
    out = capsys.readouterr().out
    assert "Cannot observe: strategize stage not complete." in out


def test_legacy_tolerance_backfills_strategize_for_progress_and_sync() -> None:
    legacy_meta = {
        "triage_stages": {
            "observe": {"stage": "observe", "report": "ok", "confirmed_at": "2026-03-01T00:00:00+00:00"},
            "reflect": {"stage": "reflect", "report": "ok"},
        }
    }
    confirmed = confirmed_triage_stage_names(legacy_meta)
    recorded_unconfirmed = recorded_unconfirmed_triage_stage_names(legacy_meta)
    progress = compute_triage_progress(legacy_meta["triage_stages"])

    assert "strategize" in confirmed
    assert "strategize" not in recorded_unconfirmed
    assert progress.current_stage == "organize"

    order: list[str] = []
    injected = _inject_pending_triage_stages(order, confirmed)
    assert "triage::strategize" not in injected


def test_cli_accepts_stage_and_stage_prompt_and_confirm() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    _add_triage_subparser(sub)

    parsed = parser.parse_args(["triage", "--stage", "strategize", "--report", "{}"])
    assert parsed.stage == "strategize"

    parsed_prompt = parser.parse_args(["triage", "--stage-prompt", "strategize"])
    assert parsed_prompt.stage_prompt == "strategize"

    parsed_reqs = parser.parse_args(["triage", "--stage", "reflect", "--show-requirements"])
    assert parsed_reqs.stage == "reflect"
    assert parsed_reqs.show_requirements is True

    parsed_confirm = parser.parse_args(["triage", "--confirm", "strategize"])
    assert parsed_confirm.confirm == "strategize"


def test_show_requirements_prints_stage_without_loading_state(capsys) -> None:
    calls = {"runtime": 0}

    services = SimpleNamespace(
        command_runtime=lambda _args: calls.__setitem__("runtime", calls["runtime"] + 1),
    )

    run_triage_workflow(
        argparse.Namespace(stage="reflect", show_requirements=True),
        services=services,
        require_issue_inventory_fn=lambda _state: True,
    )

    out = capsys.readouterr().out
    assert "# reflect" in out
    assert "Coverage Ledger" in out
    assert calls["runtime"] == 0
