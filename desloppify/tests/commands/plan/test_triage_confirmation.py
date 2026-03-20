"""Tests for triage stage confirmation workflow."""

from __future__ import annotations

import argparse

import desloppify.app.commands.plan.triage.command as triage_mod
from desloppify.app.commands.plan.triage.services import TriageServices
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_with_review_issues(*ids: str) -> dict:
    """Build minimal state with open review issues."""
    issues = {}
    for fid in ids:
        issues[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review issue {fid}",
            "confidence": "medium",
            "tier": 2,
            "detail": {"dimension": "abstraction_fitness"},
        }
    return {"issues": issues, "scan_count": 5, "dimension_scores": {}}


def _plan_with_stages(*stage_names: str, confirmed: bool = False) -> dict:
    """Build a plan with triage stages pre-recorded."""
    plan = empty_plan()
    plan["queue_order"] = list(TRIAGE_STAGE_IDS)
    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    normalized_stage_names = list(stage_names)
    if normalized_stage_names and "strategize" not in normalized_stage_names:
        normalized_stage_names.insert(0, "strategize")
    for name in normalized_stage_names:
        stages[name] = {
            "stage": name,
            "report": f"A sufficiently long report for {name} stage that meets minimum length requirements and more text — covers r1 r2 r3",
            "cited_ids": ["r1", "r2", "r3"],
            "timestamp": "2025-06-01T00:00:00Z",
            "issue_count": 5,
        }
        if name == "strategize":
            stages[name]["confirmed_text"] = "auto-confirmed"
        if confirmed:
            stages[name]["confirmed_at"] = "2025-06-01T00:01:00Z"
            stages[name]["confirmed_text"] = "I have thoroughly reviewed all the issues in this stage"
    return plan


def _fake_runtime(state: dict):
    """Build a minimal command_runtime return."""
    return type("Ctx", (), {"state": state, "config": {}})()


def _fake_services(plan, state, save_plan_fn=None):
    """Build a fake TriageServices with test stubs."""
    return TriageServices(
        command_runtime=lambda args: _fake_runtime(state),
        load_plan=lambda *a, **kw: plan,
        save_plan=save_plan_fn or (lambda p, *a, **kw: None),
        collect_triage_input=lambda p, s: type("TI", (), {
            "open_issues": s.get("issues", {}),
            "resolved_issues": {},
            "new_since_last": [],
            "resolved_since_last": [],
            "existing_clusters": {},
        })(),
        detect_recurring_patterns=lambda _a, _b: {},
        append_log_entry=lambda *a, **kw: None,
        extract_issue_citations=lambda text, ids: set(),
        build_triage_prompt=lambda si: "prompt",
    )


def _fake_args(**overrides) -> argparse.Namespace:
    """Build an argparse.Namespace with default triage args."""
    defaults = {
        "lang": None,
        "path": ".",
        "confirm": None,
        "attestation": None,
        "confirmed": None,
        "stage": None,
        "report": None,
        "complete": False,
        "confirm_existing": False,
        "strategy": None,
        "note": None,
        "start": False,
        "dry_run": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _patch_triage(monkeypatch, plan, state, save_plan_fn=None):
    """Apply standard triage monkeypatches."""
    monkeypatch.setattr(
        triage_mod, "default_triage_services",
        lambda: _fake_services(plan, state, save_plan_fn),
    )
    monkeypatch.setattr(triage_mod, "require_issue_inventory", lambda s: True)


# ---------------------------------------------------------------------------
# Confirm observe
# ---------------------------------------------------------------------------

class TestConfirmObserve:
    def test_confirm_observe_shows_summary_without_attestation(self, monkeypatch, capsys):
        """Without --attestation, confirm observe shows summary and guidance."""
        plan = _plan_with_stages("observe")
        state = _state_with_review_issues("r1", "r2", "r3")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(confirm="observe")
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "OBSERVE" in out
        assert "attestation" in out.lower() or "confirm" in out.lower()
        # Should NOT have confirmed
        assert "confirmed_at" not in plan["epic_triage_meta"]["triage_stages"]["observe"]

    def test_confirm_observe_attestation_too_short(self, monkeypatch, capsys):
        """Attestation shorter than 30 chars is rejected."""
        plan = _plan_with_stages("observe")
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(confirm="observe", attestation="too short")
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "too short" in out.lower()
        assert "confirmed_at" not in plan["epic_triage_meta"]["triage_stages"]["observe"]

    def test_confirm_observe_records_confirmation(self, monkeypatch, capsys):
        """Valid attestation records confirmed_at and confirmed_text."""
        plan = _plan_with_stages("observe")
        state = _state_with_review_issues("r1", "r2")
        saved_plans = []

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: saved_plans.append(True))

        attestation = "I have thoroughly reviewed all 2 issues across abstraction_fitness dimension and identified root causes in modules"
        args = _fake_args(confirm="observe", attestation=attestation)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "confirmed" in out.lower()
        obs = plan["epic_triage_meta"]["triage_stages"]["observe"]
        assert obs.get("confirmed_at")
        assert obs.get("confirmed_text") == attestation
        assert len(saved_plans) == 1

    def test_confirm_observe_requires_stage_recorded(self, monkeypatch, capsys):
        """Cannot confirm observe if stage not yet recorded."""
        plan = _plan_with_stages()  # no stages
        state = _state_with_review_issues("r1")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(confirm="observe", attestation="I have reviewed everything thoroughly and completely")
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "not recorded" in out.lower()


# ---------------------------------------------------------------------------
# Reflect blocked without confirmed observe
# ---------------------------------------------------------------------------

class TestReflectGate:
    def test_reflect_blocked_without_confirmed_observe(self, monkeypatch, capsys):
        """Reflect stage is blocked if observe exists but is not confirmed."""
        plan = _plan_with_stages("observe")  # observe recorded but NOT confirmed
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state)

        report = "A sufficiently long report about strategy and comparing issues r1 r2 against completed work and more text"
        args = _fake_args(stage="reflect", report=report)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "not confirmed" in out.lower()

    def test_reflect_proceeds_with_confirmed_observe(self, monkeypatch, capsys):
        """Reflect stage proceeds when observe is confirmed."""
        plan = _plan_with_stages("observe", confirmed=True)
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: None)

        report = "A sufficiently long report about strategy and comparing issues r1 r2 against completed work and more text"
        args = _fake_args(stage="reflect", report=report)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "reflect stage recorded" in out.lower()


# ---------------------------------------------------------------------------
# Confirm reflect
# ---------------------------------------------------------------------------

class TestConfirmReflect:
    def test_confirm_reflect_shows_strategy(self, monkeypatch, capsys):
        """Confirm reflect shows strategy briefing excerpt."""
        plan = _plan_with_stages("observe", "reflect", confirmed=True)
        # Un-confirm reflect so we can test the summary
        plan["epic_triage_meta"]["triage_stages"]["reflect"].pop("confirmed_at", None)
        plan["epic_triage_meta"]["triage_stages"]["reflect"].pop("confirmed_text", None)
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(confirm="reflect")
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "REFLECT" in out
        assert "strategy" in out.lower()

    def test_confirm_reflect_records_single_save(self, monkeypatch, capsys):
        """Reflect confirmation persists once after purge+log updates."""
        plan = _plan_with_stages("observe", "reflect", confirmed=True)
        plan["epic_triage_meta"]["triage_stages"]["reflect"].pop("confirmed_at", None)
        plan["epic_triage_meta"]["triage_stages"]["reflect"].pop("confirmed_text", None)
        state = _state_with_review_issues("r1", "r2")
        saved_plans = []

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: saved_plans.append(True))

        attestation = (
            "I have thoroughly reviewed the abstraction fitness dimension strategy "
            "in this plan and validated sequencing before organizing."
        )
        args = _fake_args(confirm="reflect", attestation=attestation)
        triage_mod.cmd_plan_triage(args)

        assert len(saved_plans) == 1


# ---------------------------------------------------------------------------
# Organize gate
# ---------------------------------------------------------------------------

class TestOrganizeGate:
    def test_organize_blocked_without_confirmed_reflect(self, monkeypatch, capsys):
        """Organize is blocked if reflect exists but is not confirmed."""
        plan = _plan_with_stages("observe", "reflect")
        # Confirm observe but not reflect
        plan["epic_triage_meta"]["triage_stages"]["observe"]["confirmed_at"] = "2025-06-01T00:01:00Z"
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state)

        report = "A sufficiently long organize report about my clusters r1 r2 and their priorities and ordering details for this plan"
        args = _fake_args(stage="organize", report=report)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "not confirmed" in out.lower()


# ---------------------------------------------------------------------------
# Confirm organize shows plan
# ---------------------------------------------------------------------------

class TestConfirmOrganize:
    def test_confirm_organize_shows_plan(self, monkeypatch, capsys):
        """Confirm organize shows the full plan summary."""
        plan = _plan_with_stages("observe", "reflect", "organize", confirmed=True)
        plan["epic_triage_meta"]["triage_stages"]["organize"].pop("confirmed_at", None)
        plan["epic_triage_meta"]["triage_stages"]["organize"].pop("confirmed_text", None)
        plan["clusters"]["fix-naming"] = {
            "name": "fix-naming",
            "description": "Fix naming conventions",
            "issue_ids": ["r1", "r2"],
            "action_steps": ["step 1", "step 2"],
        }
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(confirm="organize")
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "ORGANIZE" in out
        assert "Coverage" in out


# ---------------------------------------------------------------------------
# Complete blocked without confirmed organize
# ---------------------------------------------------------------------------

class TestCompleteGate:
    def test_complete_blocked_without_confirmed_organize(self, monkeypatch, capsys):
        """Complete is blocked if organize exists but is not confirmed."""
        plan = _plan_with_stages("observe", "reflect", "organize", confirmed=True)
        plan["epic_triage_meta"]["triage_stages"]["organize"].pop("confirmed_at", None)
        plan["epic_triage_meta"]["triage_stages"]["organize"].pop("confirmed_text", None)
        plan["clusters"]["fix-names"] = {
            "name": "fix-names",
            "description": "Fix naming",
            "issue_ids": ["r1"],
            "action_steps": ["step 1"],
        }
        state = _state_with_review_issues("r1")

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: None)

        strategy = "A" * 200
        args = _fake_args(complete=True, strategy=strategy)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "not confirmed" in out.lower()


# ---------------------------------------------------------------------------
# Confirm-existing requires --confirmed
# ---------------------------------------------------------------------------

class TestConfirmExistingRequiresConfirmed:
    def test_confirm_existing_requires_confirmed(self, monkeypatch, capsys):
        """--confirm-existing without --confirmed shows plan and blocks."""
        plan = _plan_with_stages("observe", "reflect", confirmed=True)
        plan["epic_triage_meta"]["strategy_summary"] = "A" * 200
        plan["clusters"]["fix-names"] = {
            "name": "fix-names",
            "description": "Fix naming",
            "issue_ids": ["r1"],
            "action_steps": ["step 1"],
        }
        state = _state_with_review_issues("r1")

        _patch_triage(monkeypatch, plan, state)

        note = "A" * 100 + " r1"
        args = _fake_args(confirm_existing=True, note=note, strategy="same")
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "--confirmed" in out
        assert "Coverage" in out


# ---------------------------------------------------------------------------
# --start manual trigger
# ---------------------------------------------------------------------------

class TestTriageStart:
    def test_start_injects_triage_stages(self, monkeypatch, capsys):
        """--start injects all triage stage IDs into the queue."""
        plan = empty_plan()
        state = _state_with_review_issues("r1", "r2")

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: None)

        args = _fake_args(start=True)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "started" in out.lower()
        assert all(sid in plan["queue_order"] for sid in TRIAGE_STAGE_IDS)

    def test_start_clears_existing_stages(self, monkeypatch, capsys):
        """--start when triage already in progress clears prior stages."""
        plan = _plan_with_stages("observe", "reflect")
        state = _state_with_review_issues("r1")

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: None)

        args = _fake_args(start=True)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "clearing" in out.lower()
        stages = plan["epic_triage_meta"]["triage_stages"]
        assert stages == {}

    def test_start_repairs_partial_triage_queue_and_skipped_overlap(self, monkeypatch, capsys):
        """--start restores missing triage stages and clears triage skips."""
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS[:3])
        plan["skipped"] = {
            "triage::enrich": {"kind": "temporary"},
            "triage::sense-check": {"kind": "temporary"},
            "triage::commit": {"kind": "temporary"},
            "review::x.py::id1": {"kind": "temporary"},
        }
        state = _state_with_review_issues("r1")

        _patch_triage(monkeypatch, plan, state, save_plan_fn=lambda p, *a, **kw: None)

        args = _fake_args(start=True)
        triage_mod.cmd_plan_triage(args)
        out = capsys.readouterr().out
        assert "already in the queue" in out.lower()
        assert plan["queue_order"][: len(TRIAGE_STAGE_IDS)] == list(TRIAGE_STAGE_IDS)
        assert "triage::enrich" not in plan["skipped"]
        assert "triage::sense-check" not in plan["skipped"]
        assert "triage::commit" not in plan["skipped"]
        assert "review::x.py::id1" in plan["skipped"]
