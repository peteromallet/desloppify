"""Tests for strategize stage lifecycle and compatibility wiring."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

import desloppify.app.commands.plan.triage.stages.strategize as strategize_mod
from desloppify.app.cli_support.parser_groups_plan_impl_sections_triage_commit_scan import (
    _add_triage_subparser,
)
from desloppify.engine._plan.constants import (
    TRIAGE_STAGE_IDS,
    confirmed_triage_stage_names,
    recorded_unconfirmed_triage_stage_names,
)
from desloppify.engine._plan.sync.triage import _inject_pending_triage_stages
from desloppify.engine.plan_triage import compute_triage_progress
from desloppify.app.commands.plan.triage.stages.observe import cmd_stage_observe


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

    parsed_confirm = parser.parse_args(["triage", "--confirm", "strategize"])
    assert parsed_confirm.confirm == "strategize"
