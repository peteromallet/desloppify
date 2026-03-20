"""Tests for triage dependency chain validation in cmd_plan_resolve."""

from __future__ import annotations

import argparse

import desloppify.app.commands.plan.override.resolve_cmd as override_mod
import desloppify.app.commands.plan.override.resolve_workflow as override_workflow_mod
from desloppify.app.commands.plan.override.resolve_helpers import blocked_triage_stages as _blocked_triage_stages
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS


def _plan_with_triage_stages(*confirmed_stages: str) -> dict:
    """Build a plan with all triage stages in queue, some confirmed."""
    plan = empty_plan()
    plan["queue_order"] = list(TRIAGE_STAGE_IDS)
    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    for name in confirmed_stages:
        stages[name] = {
            "stage": name,
            "report": f"Report for {name}",
            "timestamp": "2025-06-01T00:00:00Z",
            "confirmed_at": "2025-06-01T00:01:00Z",
        }
    return plan


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "patterns": [],
        "attest": None,
        "note": None,
        "confirm": False,
        "force_resolve": False,
        "state": None,
        "lang": None,
        "path": None,
        "exclude": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ── Unit tests for _blocked_triage_stages ───────────────


class TestBlockedTriageStages:
    def test_nothing_confirmed_blocks_all_except_strategize(self):
        plan = _plan_with_triage_stages()
        blocked = _blocked_triage_stages(plan)
        assert "triage::strategize" not in blocked
        assert blocked["triage::observe"] == ["triage::strategize"]
        assert blocked["triage::reflect"] == ["triage::observe"]
        assert blocked["triage::organize"] == ["triage::reflect"]
        assert blocked["triage::enrich"] == ["triage::organize"]
        assert blocked["triage::sense-check"] == ["triage::enrich"]
        assert blocked["triage::commit"] == ["triage::sense-check"]

    def test_observe_confirmed_unblocks_reflect(self):
        plan = _plan_with_triage_stages("observe")
        blocked = _blocked_triage_stages(plan)
        assert "triage::observe" not in blocked
        assert "triage::reflect" not in blocked
        assert blocked["triage::organize"] == ["triage::reflect"]

    def test_all_confirmed_returns_empty(self):
        plan = _plan_with_triage_stages(
            "observe",
            "reflect",
            "organize",
            "enrich",
            "sense-check",
            "commit",
        )
        assert _blocked_triage_stages(plan) == {}

    def test_no_triage_in_queue_returns_empty(self):
        plan = empty_plan()
        plan["queue_order"] = ["some::issue"]
        assert _blocked_triage_stages(plan) == {}

    def test_missing_queue_id_for_unconfirmed_stage_still_blocks_later_stage(self):
        plan = empty_plan()
        plan["queue_order"] = ["triage::enrich", "triage::sense-check", "triage::commit"]
        plan["epic_triage_meta"] = {
            "triage_stages": {"organize": {"report": "cluster plan"}},
        }
        blocked = _blocked_triage_stages(plan)
        assert blocked["triage::enrich"] == ["triage::organize"]


# ── Integration tests through cmd_plan_resolve ────────────────


def test_plan_resolve_rejects_blocked_triage_stage(monkeypatch, capsys):
    """cmd_plan_resolve refuses to resolve triage::reflect when observe is incomplete."""
    plan = _plan_with_triage_stages()  # nothing confirmed

    monkeypatch.setattr(override_workflow_mod, "load_plan", lambda *a, **kw: plan)

    saved_plans = []
    monkeypatch.setattr(override_workflow_mod, "save_plan", lambda p, *a, **kw: saved_plans.append(p))

    args = _args(patterns=["triage::reflect"])
    override_mod.cmd_plan_resolve(args)

    out = capsys.readouterr().out
    assert "Cannot resolve" in out
    assert "observe" in out
    # Plan should NOT have been saved (stage was blocked)
    assert len(saved_plans) == 0


def test_plan_resolve_allows_unblocked_triage_stage(monkeypatch, capsys):
    """cmd_plan_resolve resolves triage::reflect when observe is already confirmed."""
    plan = _plan_with_triage_stages("observe")  # observe confirmed

    monkeypatch.setattr(override_workflow_mod, "load_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(override_workflow_mod, "live_planned_queue_empty", lambda _plan: False)

    saved_plans = []
    monkeypatch.setattr(override_workflow_mod, "save_plan", lambda p, *a, **kw: saved_plans.append(p))

    args = _args(patterns=["triage::reflect"])
    override_mod.cmd_plan_resolve(args)

    out = capsys.readouterr().out
    assert "Resolved" in out
    assert len(saved_plans) == 1


def test_plan_resolve_force_resolve_overrides_block(monkeypatch, capsys):
    """--force-resolve allows resolving a blocked triage stage."""
    plan = _plan_with_triage_stages()  # nothing confirmed

    monkeypatch.setattr(override_workflow_mod, "load_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(override_workflow_mod, "live_planned_queue_empty", lambda _plan: False)

    saved_plans = []
    monkeypatch.setattr(override_workflow_mod, "save_plan", lambda p, *a, **kw: saved_plans.append(p))

    args = _args(patterns=["triage::reflect"], force_resolve=True)
    override_mod.cmd_plan_resolve(args)

    out = capsys.readouterr().out
    # Warning is still shown but it proceeds
    assert "Resolved" in out
    assert len(saved_plans) == 1


def test_plan_resolve_observe_requires_strategize(monkeypatch, capsys):
    """triage::observe is blocked until strategize is complete."""
    plan = _plan_with_triage_stages()  # nothing confirmed

    monkeypatch.setattr(override_workflow_mod, "load_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(override_workflow_mod, "live_planned_queue_empty", lambda _plan: False)

    saved_plans = []
    monkeypatch.setattr(override_workflow_mod, "save_plan", lambda p, *a, **kw: saved_plans.append(p))

    args = _args(patterns=["triage::observe"])
    override_mod.cmd_plan_resolve(args)

    out = capsys.readouterr().out
    assert "Cannot resolve" in out
    assert "strategize" in out
    assert len(saved_plans) == 0
