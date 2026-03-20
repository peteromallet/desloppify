"""Tests for jump-back: re-running earlier triage stages."""

from __future__ import annotations

import argparse

import desloppify.app.commands.plan.triage.command as triage_mod
from desloppify.app.commands.plan.triage.services import TriageServices
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import TRIAGE_STAGE_IDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_with_issues(*ids: str, dimension: str = "naming") -> dict:
    issues = {}
    for fid in ids:
        issues[fid] = {
            "status": "open",
            "detector": "review",
            "file": "test.py",
            "summary": f"Review issue {fid}",
            "confidence": "medium",
            "tier": 2,
            "detail": {"dimension": dimension},
        }
    return {"issues": issues, "scan_count": 5, "dimension_scores": {}}


def _plan_with_stages(*stage_names: str, confirmed: bool = False) -> dict:
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
            "report": (
                "A sufficiently long report for the stage that meets minimum "
                "length requirements and more text to ensure validation passes"
                " — covers r1 r2 r3 r4 r5"
            ),
            "cited_ids": ["r1", "r2", "r3"],
            "timestamp": "2025-06-01T00:00:00Z",
            "issue_count": 5,
        }
        if name == "strategize":
            stages[name]["confirmed_text"] = "auto-confirmed"
        if confirmed:
            stages[name]["confirmed_at"] = "2025-06-01T00:01:00Z"
            stages[name]["confirmed_text"] = (
                "I have thoroughly reviewed all the issues in naming dimension "
                "and this stage analysis is complete"
            )
    return plan


def _plan_with_enriched_clusters(stage_names, confirmed=False):
    """Plan with stages + enriched manual clusters."""
    plan = _plan_with_stages(*stage_names, confirmed=confirmed)
    plan["clusters"]["fix-naming"] = {
        "name": "fix-naming",
        "issue_ids": ["r1", "r2", "r3", "r4", "r5"],
        "description": "Fix naming issues",
        "action_steps": ["step 1", "step 2", "step 3", "step 4", "step 5"],
        "auto": False,
        "user_modified": True,
        "created_at": "2025-06-01T00:00:00Z",
        "updated_at": "2025-06-01T00:00:00Z",
        "cluster_key": "",
        "action": None,
    }
    return plan


def _fake_runtime(state: dict):
    return type("Ctx", (), {"state": state, "config": {}})()


def _fake_args(**overrides) -> argparse.Namespace:
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


def _patch_triage(monkeypatch, plan, state, save_plan_fn=None):
    """Apply standard triage monkeypatches."""
    monkeypatch.setattr(
        triage_mod, "default_triage_services",
        lambda: _fake_services(plan, state, save_plan_fn),
    )
    monkeypatch.setattr(triage_mod, "require_issue_inventory", lambda s: True)


# ---------------------------------------------------------------------------
# Tests: jump-back reflect with new report
# ---------------------------------------------------------------------------

class TestJumpBackReflect:
    def test_rerun_reflect_with_new_report_clears_organize_confirmation(self, monkeypatch, capsys):
        """Re-running reflect with --report clears organize's confirmed_at."""
        plan = _plan_with_enriched_clusters(
            ["observe", "reflect", "organize"], confirmed=True,
        )
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        new_report = (
            "Revised strategy for r1 r2 r3 r4 r5: after further analysis, the naming issues "
            "have a deeper root cause than initially thought. Need to "
            "restructure approach to address the root cause first."
        )
        args = _fake_args(stage="reflect", report=new_report)
        triage_mod.cmd_plan_triage(args)

        stages = plan["epic_triage_meta"]["triage_stages"]
        # Reflect should have new report
        assert stages["reflect"]["report"] == new_report
        # Reflect's own confirmation should be cleared (new data)
        assert stages["reflect"].get("confirmed_at") is None
        # Organize's confirmation should be cleared (cascade)
        assert stages["organize"].get("confirmed_at") is None

    def test_rerun_reflect_without_report_reuses_data(self, monkeypatch, capsys):
        """Re-running reflect without --report reuses existing report."""
        plan = _plan_with_stages("observe", "reflect", confirmed=True)
        original_report = plan["epic_triage_meta"]["triage_stages"]["reflect"]["report"]
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(stage="reflect")  # No --report
        triage_mod.cmd_plan_triage(args)

        stages = plan["epic_triage_meta"]["triage_stages"]
        # Report should be preserved
        assert stages["reflect"]["report"] == original_report
        out = capsys.readouterr().out
        assert "preserved" in out.lower()

    def test_rerun_reflect_without_report_preserves_own_confirmation(self, monkeypatch, capsys):
        """Reuse mode preserves reflect's own confirmed_at (data unchanged)."""
        plan = _plan_with_stages("observe", "reflect", confirmed=True)
        original_confirmed = plan["epic_triage_meta"]["triage_stages"]["reflect"]["confirmed_at"]
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(stage="reflect")  # No --report (reuse)
        triage_mod.cmd_plan_triage(args)

        stages = plan["epic_triage_meta"]["triage_stages"]
        assert stages["reflect"].get("confirmed_at") == original_confirmed


# ---------------------------------------------------------------------------
# Tests: jump-back observe cascades to reflect and organize
# ---------------------------------------------------------------------------

class TestJumpBackObserve:
    def test_rerun_observe_cascades_to_reflect_and_organize(self, monkeypatch, capsys):
        """Jumping back to observe with new report clears reflect + organize confirmations."""
        plan = _plan_with_enriched_clusters(
            ["observe", "reflect", "organize"], confirmed=True,
        )
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        new_report = (
            "Completely revised observation after discovering additional naming "
            "patterns in the codebase that change the analysis significantly."
        )
        args = _fake_args(stage="observe", report=new_report)
        triage_mod.cmd_plan_triage(args)

        stages = plan["epic_triage_meta"]["triage_stages"]
        # Observe should have new data, confirmation cleared
        assert stages["observe"]["report"] == new_report
        assert stages["observe"].get("confirmed_at") is None
        # Reflect and organize confirmations should be cleared
        assert stages["reflect"].get("confirmed_at") is None
        assert stages["organize"].get("confirmed_at") is None


# ---------------------------------------------------------------------------
# Tests: jump-back then fold-confirm forward
# ---------------------------------------------------------------------------

class TestJumpBackThenFoldConfirm:
    def test_jump_back_then_fold_confirm_forward(self, monkeypatch, capsys):
        """Jump back to reflect (reuse), then --stage organize with --attestation fold-confirms."""
        plan = _plan_with_enriched_clusters(
            ["observe", "reflect", "organize"], confirmed=True,
        )
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        # Step 1: Jump back to reflect (reuse) — this clears organize's confirmation
        args = _fake_args(stage="reflect")
        triage_mod.cmd_plan_triage(args)

        stages = plan["epic_triage_meta"]["triage_stages"]
        # Reflect confirmation preserved (reuse), organize confirmation cleared
        assert stages["reflect"].get("confirmed_at") is not None
        assert stages["organize"].get("confirmed_at") is None

        # Step 2: Re-run organize with attestation to fold-confirm reflect
        # Since reflect is still confirmed from reuse, this should work directly
        organize_report = (
            "Re-organized after reviewing. The fix-naming cluster structure "
            "is still valid. Priority ordering unchanged. This cluster "
            "addresses the root cause of naming inconsistencies."
        )
        attestation = (
            "I have reviewed the fix-naming cluster and the reflect strategy "
            "remains valid — the naming dimension analysis is correct"
        )
        args2 = _fake_args(
            stage="organize",
            report=organize_report,
            attestation=attestation,
        )
        triage_mod.cmd_plan_triage(args2)

        stages = plan["epic_triage_meta"]["triage_stages"]
        assert "organize" in stages
        assert stages["organize"]["report"] == organize_report


# ---------------------------------------------------------------------------
# Tests: complete shows jump-back guidance
# ---------------------------------------------------------------------------

class TestCompleteJumpBackGuidance:
    def test_complete_shows_jump_back_guidance(self, monkeypatch, capsys):
        """The --complete summary includes guidance on revising earlier stages."""
        plan = _plan_with_enriched_clusters(
            ["observe", "reflect", "organize", "enrich", "sense-check"], confirmed=True,
        )
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        strategy = (
            "Execute fix-naming cluster first to resolve all naming convention "
            "issues across the codebase. Start with the most impactful files "
            "and work outward. Verify each fix with a scan afterwards. "
            "The approach addresses root causes rather than symptoms. "
            "After naming is clean, reassess remaining issues."
        )
        args = _fake_args(complete=True, strategy=strategy)
        triage_mod.cmd_plan_triage(args)

        out = capsys.readouterr().out
        assert "revise" in out.lower()
        assert "--stage" in out


# ---------------------------------------------------------------------------
# Tests: rerun stage without prior data still requires report
# ---------------------------------------------------------------------------

class TestRerunWithoutPriorData:
    def test_rerun_stage_without_prior_data_still_requires_report(self, monkeypatch, capsys):
        """When stage has no existing data and no --report, error as before."""
        plan = _plan_with_stages("observe", confirmed=True)
        # No reflect stage data exists
        state = _state_with_issues("r1", "r2", "r3")

        _patch_triage(monkeypatch, plan, state)

        args = _fake_args(stage="reflect")  # No --report, no prior data
        triage_mod.cmd_plan_triage(args)

        out = capsys.readouterr().out
        assert "--report is required" in out
        # Reflect should NOT be in stages
        stages = plan["epic_triage_meta"]["triage_stages"]
        assert "reflect" not in stages


# ---------------------------------------------------------------------------
# Tests: stage progress shows needs confirm after cascade-clear
# ---------------------------------------------------------------------------

class TestStageProgressShowsNeedsConfirm:
    def test_stage_progress_shows_needs_confirm(self, monkeypatch, capsys):
        """After cascade-clear, stage progress shows 'needs confirm' for unconfirmed stages."""
        plan = _plan_with_enriched_clusters(
            ["observe", "reflect", "organize"], confirmed=True,
        )
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")

        _patch_triage(monkeypatch, plan, state)

        # Jump back to reflect with new report — clears organize confirmation
        new_report = (
            "Revised strategy for r1 r2 r3 r4 r5: after further analysis, the naming issues "
            "have a deeper root cause than initially thought. Need to "
            "restructure approach to address the root cause first."
        )
        args = _fake_args(stage="reflect", report=new_report)
        triage_mod.cmd_plan_triage(args)
        capsys.readouterr()  # discard first output

        # Now run triage with no args to see the dashboard
        args2 = _fake_args()
        triage_mod.cmd_plan_triage(args2)
        out = capsys.readouterr().out

        assert "needs confirm" in out
