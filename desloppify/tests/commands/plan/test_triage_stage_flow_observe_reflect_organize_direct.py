"""Direct tests for observe/reflect/organize stage flow module."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import desloppify.app.commands.plan.triage.stages.observe as observe_mod
import desloppify.app.commands.plan.triage.stages.organize as organize_mod
import desloppify.app.commands.plan.triage.stages.reflect as reflect_mod


def _args(**overrides) -> argparse.Namespace:
    base = {"report": None, "attestation": None}
    base.update(overrides)
    return argparse.Namespace(**base)


def _services(
    plan: dict,
    *,
    state: dict | None = None,
    open_issues: dict | None = None,
    resolved_issues: dict | None = None,
):
    saved: list[dict] = []
    logs: list[tuple[str, dict]] = []
    state_obj = state or {}
    return SimpleNamespace(
        command_runtime=lambda _args: SimpleNamespace(state=state_obj),
        load_plan=lambda: plan,
        save_plan=lambda current: saved.append(current.copy()),
        collect_triage_input=lambda _plan, _state: SimpleNamespace(
            open_issues=open_issues or {},
            resolved_issues=resolved_issues or {},
        ),
        extract_issue_citations=lambda _report, _valid_ids: set(),
        append_log_entry=lambda _plan, action, **kwargs: logs.append((action, kwargs)),
        detect_recurring_patterns=lambda _open, _resolved: {},
    ), saved, logs


def test_observe_autostarts_planning_and_requires_report(monkeypatch) -> None:
    plan = {"epic_triage_meta": {}}
    services, saved, _logs = _services(plan)
    called: list[str] = []
    monkeypatch.setattr(observe_mod, "_print_observe_report_requirement", lambda: called.append("required"))

    def _inject_started_plan(current_plan: dict) -> None:
        current_plan.setdefault("queue_order", []).append("workflow::observe")
        current_plan.setdefault("epic_triage_meta", {}).setdefault("triage_stages", {})["strategize"] = {
            "stage": "strategize",
            "report": "{}",
            "confirmed_at": "t",
            "confirmed_text": "auto-confirmed",
        }

    observe_mod._cmd_stage_observe(
        _args(report=None),
        services=services,
        has_triage_in_queue_fn=lambda _plan: False,
        inject_triage_stages_fn=_inject_started_plan,
    )

    assert called == ["required"]
    assert saved  # planning mode auto-start save happened
    assert "workflow::observe" in plan.get("queue_order", [])


def test_observe_zero_issue_path_records_stage_and_saves(monkeypatch) -> None:
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "strategize": {
                    "stage": "strategize",
                    "report": "{}",
                    "confirmed_at": "t",
                    "confirmed_text": "auto-confirmed",
                }
            }
        }
    }
    services, saved, _logs = _services(plan)
    monkeypatch.setattr(observe_mod, "record_observe_stage", lambda stages, **_k: stages.setdefault("observe", {}) or [])

    observe_mod._cmd_stage_observe(
        _args(report="short but valid"),
        services=services,
        has_triage_in_queue_fn=lambda _plan: True,
        inject_triage_stages_fn=lambda _plan: None,
    )

    assert saved
    assert "observe" in plan["epic_triage_meta"]["triage_stages"]


def test_reflect_exits_when_triage_not_in_queue(monkeypatch, capsys) -> None:
    plan = {"epic_triage_meta": {"triage_stages": {}}}
    services, _saved, _logs = _services(plan)
    monkeypatch.setattr(reflect_mod, "has_triage_in_queue", lambda _plan: False)

    reflect_mod._cmd_stage_reflect(_args(report="r" * 120), services=services)
    out = capsys.readouterr().out
    assert "No planning stages in the queue" in out


def test_organize_exits_when_reflect_requirement_not_met(monkeypatch) -> None:
    plan = {"epic_triage_meta": {"triage_stages": {}}, "clusters": {}}
    services, _saved, _logs = _services(plan, state={"issues": {}})
    monkeypatch.setattr(organize_mod, "has_triage_in_queue", lambda _plan: True)
    monkeypatch.setattr(organize_mod, "_require_reflect_stage_for_organize", lambda _stages: False)

    organize_mod._cmd_stage_organize(_args(report="organized"), services=services)


def test_organize_records_zero_issue_noop_batch(monkeypatch) -> None:
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "reflect": {
                    "report": "x" * 150,
                    "confirmed_at": "2026-03-10T00:00:00Z",
                    "timestamp": "2026-03-10T00:00:00Z",
                }
            }
        },
        "clusters": {},
    }
    services, saved, logs = _services(plan, state={"issues": {}})
    monkeypatch.setattr(organize_mod, "has_triage_in_queue", lambda _plan: True)
    monkeypatch.setattr(organize_mod, "_require_reflect_stage_for_organize", lambda _stages: True)
    monkeypatch.setattr(organize_mod, "auto_confirm_reflect_for_organize", lambda **_kwargs: True)

    organize_mod._cmd_stage_organize(
        _args(
            report=(
                "Organize remained intentionally empty for this batch because the current triage "
                "state has zero open review issues, zero skip candidates, and no review work to cluster."
            )
        ),
        services=services,
    )

    assert saved
    assert "organize" in plan["epic_triage_meta"]["triage_stages"]
    assert any(action == "triage_organize" for action, _kwargs in logs)


def test_public_stage_entrypoints_remain_callable(monkeypatch) -> None:
    called: list[str] = []
    services, _saved, _logs = _services({"epic_triage_meta": {"triage_stages": {}}})
    monkeypatch.setattr(reflect_mod, "_cmd_stage_reflect", lambda *args, **kwargs: called.append("reflect"))
    monkeypatch.setattr(organize_mod, "_cmd_stage_organize", lambda *args, **kwargs: called.append("organize"))
    monkeypatch.setattr(observe_mod, "ensure_triage_started", lambda *args, **kwargs: SimpleNamespace(status="blocked"))

    args = _args()
    observe_mod.cmd_stage_observe(args, services=services)
    reflect_mod.cmd_stage_reflect(args)
    organize_mod.cmd_stage_organize(args)

    assert callable(observe_mod._cmd_stage_observe)
    assert called == ["reflect", "organize"]


def test_reflect_rejects_incomplete_issue_accounting(monkeypatch, capsys) -> None:
    plan = {
        "epic_triage_meta": {
            "triage_stages": {
                "observe": {
                    "report": "x" * 120,
                    "confirmed_at": "2026-03-09T00:00:00Z",
                }
            }
        }
    }
    open_issues = {
        "review::design::aaaabbbb": {"status": "open"},
        "review::design::ccccdddd": {"status": "open"},
    }
    services, _saved, _logs = _services(plan, open_issues=open_issues)
    monkeypatch.setattr(reflect_mod, "has_triage_in_queue", lambda _plan: True)

    reflect_mod._cmd_stage_reflect(
        _args(
            report=(
                "Cluster alpha will handle aaaabbbb in src/a.ts after reviewing the current "
                "resolved history and recurring dimensions. " * 2
            )
        ),
        services=services,
    )

    out = capsys.readouterr().out
    assert "account for every open review issue exactly once" in out
    assert "reflect" not in plan["epic_triage_meta"]["triage_stages"]
