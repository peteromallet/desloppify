"""Behavioral tests for plan-pattern resolution and synthesis guardrails."""

from __future__ import annotations

import argparse

import desloppify.app.commands.helpers.guardrails as guardrails_mod
import desloppify.app.commands.helpers.runtime as runtime_mod
import desloppify.app.commands.plan.override_handlers as override_handlers_mod
import desloppify.app.commands.plan._resolve as resolve_mod
import desloppify.state as state_mod


def _state_with_findings() -> dict:
    state = state_mod.empty_state()
    state["findings"] = {
        "f-open": {
            "id": "f-open",
            "detector": "smells",
            "file": "desloppify/app/commands/next.py",
            "status": "open",
            "summary": "open finding",
        },
        "f-fixed": {
            "id": "f-fixed",
            "detector": "smells",
            "file": "desloppify/app/commands/plan/_resolve.py",
            "status": "fixed",
            "summary": "fixed finding",
        },
    }
    return state


def test_resolve_ids_from_patterns_expands_cluster_name() -> None:
    state = _state_with_findings()
    plan = {
        "queue_order": [],
        "skipped": {},
        "clusters": {
            "auto/refactor-batch": {"finding_ids": ["f-fixed", "f-open"]},
        },
    }
    ids = resolve_mod.resolve_ids_from_patterns(
        state,
        ["auto/refactor-batch"],
        plan=plan,
    )
    assert ids == ["f-fixed", "f-open"]


def test_resolve_ids_from_patterns_normalizes_legacy_status_alias() -> None:
    state = _state_with_findings()
    ids = resolve_mod.resolve_ids_from_patterns(
        state,
        ["f-fixed"],
        status_filter="resolved",
    )
    assert ids == ["f-fixed"]


def test_print_no_match_hint_includes_cluster_pattern_help(capsys) -> None:
    resolve_mod.print_no_match_hint(["missing::id"])
    out = capsys.readouterr().out
    assert "Plan cluster name" in out


def test_guardrail_banner_renders_when_synthesis_pending(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        guardrails_mod,
        "load_plan",
        lambda: {"queue_order": ["synthesis::pending"]},
    )
    monkeypatch.setattr(
        guardrails_mod,
        "synthesis_phase_banner",
        lambda _plan: "synthesis phase in progress",
    )

    guardrails_mod.print_synthesis_guardrail_banner()
    out = capsys.readouterr().out
    assert "synthesis phase in progress" in out


def test_guardrail_banner_warns_when_plan_load_fails(monkeypatch, capsys) -> None:
    def _raise_os_error() -> dict:
        raise OSError("read failure")

    monkeypatch.setattr(guardrails_mod, "load_plan", _raise_os_error)

    guardrails_mod.print_synthesis_guardrail_banner()
    err = capsys.readouterr().err
    assert "Warning: synthesis guardrail unavailable" in err


def test_cmd_plan_done_expands_cluster_pattern_before_resolve(monkeypatch) -> None:
    state = _state_with_findings()
    state["last_scan"] = {"at": "now"}
    runtime = runtime_mod.CommandRuntime(config={}, state=state, state_path=None)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        override_handlers_mod,
        "load_plan",
        lambda: {
            "queue_order": [],
            "skipped": {},
            "clusters": {"auto/refactor-batch": {"finding_ids": ["f-open"]}},
        },
    )
    monkeypatch.setattr(
        override_handlers_mod,
        "cmd_resolve",
        lambda ns: captured.setdefault("patterns", list(ns.patterns)),
    )

    args = argparse.Namespace(
        patterns=["auto/refactor-batch"],
        attest="I have actually fixed it and I am not gaming the score.",
        note=None,
        state=None,
        lang=None,
        path=None,
        exclude=None,
        runtime=runtime,
    )
    override_handlers_mod.cmd_plan_done(args)
    assert captured["patterns"] == ["f-open"]


def test_cmd_plan_done_prints_no_match_hint_for_unknown_selector(
    monkeypatch,
    capsys,
) -> None:
    state = _state_with_findings()
    state["last_scan"] = {"at": "now"}
    runtime = runtime_mod.CommandRuntime(config={}, state=state, state_path=None)

    monkeypatch.setattr(
        override_handlers_mod,
        "load_plan",
        lambda: {"queue_order": [], "skipped": {}, "clusters": {}},
    )
    called = {"resolve": False}

    def _mark_called(_ns) -> None:
        called["resolve"] = True

    monkeypatch.setattr(override_handlers_mod, "cmd_resolve", _mark_called)

    args = argparse.Namespace(
        patterns=["auto/missing-cluster"],
        attest="I have actually fixed it and I am not gaming the score.",
        note=None,
        state=None,
        lang=None,
        path=None,
        exclude=None,
        runtime=runtime,
    )
    override_handlers_mod.cmd_plan_done(args)

    out = capsys.readouterr().out
    assert "No matching findings found." in out
    assert called["resolve"] is False
