"""Tests for triage-completion and scan-completion gates on workflow items.

workflow::score-checkpoint and workflow::create-plan require:
  1. All 4 triage stages confirmed (observe, reflect, organize, commit)
  2. A scan has run since the plan cycle started (scan_count > scan_count_at_plan_start)

Both gates can be bypassed:
  - Triage gate: --force-resolve with 50+ char note
  - Scan gate: --force-resolve, or `plan scan-gate --skip --note "..."`
"""

from __future__ import annotations

import argparse

import desloppify.app.commands.plan.override_handlers as override_mod
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.stale_dimensions import (
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_with_workflow_item(
    wid: str = WORKFLOW_SCORE_CHECKPOINT_ID,
    *,
    triage_complete: bool = False,
    scan_count_at_start: int | None = None,
    scan_gate_skipped: bool = False,
) -> dict:
    """Build a plan with a gated workflow item in the queue."""
    plan = empty_plan()
    plan["queue_order"] = [wid]
    if triage_complete:
        # Mimic real --complete behavior: stages archived to last_triage,
        # triage_stages cleared, last_completed_at set
        plan["epic_triage_meta"] = {
            "triage_stages": {},
            "last_completed_at": "2025-01-01T00:00:00Z",
            "last_triage": {
                "stages": {
                    stage: {"report": f"test {stage}", "timestamp": "2025-01-01T00:00:00Z"}
                    for stage in ("observe", "reflect", "organize")
                },
                "strategy": "test strategy",
            },
        }
    if scan_count_at_start is not None:
        plan["scan_count_at_plan_start"] = scan_count_at_start
    if scan_gate_skipped:
        plan["scan_gate_skipped"] = True
    return plan


def _state_with_scan_count(count: int = 5) -> dict:
    return {
        "issues": {},
        "scan_count": count,
        "last_scan": "2025-01-01T00:00:00Z",
    }


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "patterns": [WORKFLOW_SCORE_CHECKPOINT_ID],
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


def _scan_gate_args(**overrides) -> argparse.Namespace:
    defaults = {
        "skip": False,
        "note": None,
        "state": None,
        "lang": None,
        "path": None,
        "exclude": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _mock_plan_io(monkeypatch, plan):
    """Patch load_plan/save_plan, return list of saved plans."""
    monkeypatch.setattr(override_mod, "load_plan", lambda *a, **kw: plan)
    saved = []
    monkeypatch.setattr(override_mod, "save_plan", lambda p, *a, **kw: saved.append(p))
    return saved


def _mock_state(monkeypatch, state):
    """Patch state_path and load_state to return our spoofed state."""
    import desloppify.state as state_mod_real
    monkeypatch.setattr(override_mod, "state_path", lambda args: None)
    monkeypatch.setattr(state_mod_real, "load_state", lambda path=None: state)
    # Also patch the module-level import used in override_handlers
    monkeypatch.setattr(override_mod.state_mod, "load_state", lambda path=None: state)


# ===========================================================================
# Triage gate tests
# ===========================================================================


class TestTriageGateBlocksWorkflow:
    """workflow::score-checkpoint is blocked when triage is incomplete."""

    def test_blocked_when_triage_incomplete(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(triage_complete=False)
        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "triage not complete" in out
        assert "observe" in out  # next stage hint

    def test_shows_next_stage_reflect(self, monkeypatch, capsys):
        """When observe is done, should hint at reflect."""
        plan = _plan_with_workflow_item()
        plan["epic_triage_meta"] = {
            "triage_stages": {
                "observe": {"report": "done", "timestamp": "2025-01-01T00:00:00Z"},
            }
        }
        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "triage not complete" in out
        assert "Observe is done" in out or "reflect" in out

    def test_shows_next_stage_organize(self, monkeypatch, capsys):
        """When observe+reflect done, should hint at organize."""
        plan = _plan_with_workflow_item()
        plan["epic_triage_meta"] = {
            "triage_stages": {
                "observe": {"report": "done", "timestamp": "2025-01-01T00:00:00Z"},
                "reflect": {"report": "done", "timestamp": "2025-01-01T00:00:00Z"},
            }
        }
        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "triage not complete" in out
        assert "organize" in out.lower()

    def test_shows_next_stage_commit(self, monkeypatch, capsys):
        """When observe+reflect+organize done, should hint at commit."""
        plan = _plan_with_workflow_item()
        plan["epic_triage_meta"] = {
            "triage_stages": {
                "observe": {"report": "done", "timestamp": "2025-01-01T00:00:00Z"},
                "reflect": {"report": "done", "timestamp": "2025-01-01T00:00:00Z"},
                "organize": {"report": "done", "timestamp": "2025-01-01T00:00:00Z"},
            }
        }
        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "triage not complete" in out
        assert "commit" in out.lower()

    def test_force_resolve_requires_long_note(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(triage_complete=False)
        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args(
            force_resolve=True,
            note="too short",
            confirm=True,
        ))

        out = capsys.readouterr().out
        assert "min 50 chars" in out

    def test_force_resolve_with_long_note_passes_triage(self, monkeypatch, capsys):
        """Force-resolve with 50+ char note bypasses triage gate."""
        plan = _plan_with_workflow_item(
            triage_complete=False,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(6)  # scan ran
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        long_note = "Skipping triage because I manually reviewed all findings in the previous session"
        override_mod.cmd_plan_resolve(_args(
            force_resolve=True,
            note=long_note,
            confirm=True,
        ))

        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "Resolved" in out
        assert len(saved) >= 1

    def test_passes_when_triage_complete(self, monkeypatch, capsys):
        """Triage complete + scan ran → resolves normally."""
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(6)  # scan ran
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "Resolved" in out
        assert len(saved) >= 1


# ===========================================================================
# Scan gate tests
# ===========================================================================


class TestScanGateBlocksWorkflow:
    """workflow items blocked when no scan has run since plan cycle start."""

    def test_blocked_when_no_scan_this_cycle(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)  # same count = no new scan
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "no scan has run this cycle" in out
        assert "desloppify scan" in out

    def test_passes_when_scan_ran(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(6)  # scan ran
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "Resolved" in out
        assert len(saved) >= 1

    def test_passes_when_scan_gate_skipped(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
            scan_gate_skipped=True,
        )
        state = _state_with_scan_count(5)  # no new scan, but gate skipped
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "Resolved" in out
        assert len(saved) >= 1

    def test_force_resolve_bypasses_scan_gate(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)  # no new scan
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        long_note = "Forcing resolution because scan results were already reviewed manually in detail"
        override_mod.cmd_plan_resolve(_args(
            force_resolve=True,
            note=long_note,
            confirm=True,
        ))

        out = capsys.readouterr().out
        # force-resolve bypasses both triage (already complete) and scan gate
        assert "Resolved" in out
        assert len(saved) >= 1

    def test_no_scan_count_at_start_skips_gate(self, monkeypatch, capsys):
        """When scan_count_at_plan_start is not set, scan gate doesn't apply."""
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=None,  # not set
        )
        saved = _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "Resolved" in out
        assert len(saved) >= 1

    def test_create_plan_also_gated(self, monkeypatch, capsys):
        """workflow::create-plan is also behind the scan gate."""
        plan = _plan_with_workflow_item(
            wid=WORKFLOW_CREATE_PLAN_ID,
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)  # no new scan
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args(patterns=[WORKFLOW_CREATE_PLAN_ID]))

        out = capsys.readouterr().out
        assert "no scan has run this cycle" in out


# ===========================================================================
# scan-gate subcommand tests
# ===========================================================================


class TestScanGateCommand:
    """Tests for `desloppify plan scan-gate` subcommand."""

    def test_status_blocked(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_scan_gate(_scan_gate_args())

        out = capsys.readouterr().out
        assert "BLOCKED" in out

    def test_status_passed(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(6)
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_scan_gate(_scan_gate_args())

        out = capsys.readouterr().out
        assert "PASSED" in out

    def test_status_skipped(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
            scan_gate_skipped=True,
        )
        state = _state_with_scan_count(5)
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_scan_gate(_scan_gate_args())

        out = capsys.readouterr().out
        assert "SKIPPED" in out

    def test_skip_requires_long_note(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_scan_gate(_scan_gate_args(skip=True, note="too short"))

        out = capsys.readouterr().out
        assert "50 chars" in out

    def test_skip_with_long_note_succeeds(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        long_note = "Skipping scan because I already validated all findings manually in the previous session"
        override_mod.cmd_plan_scan_gate(_scan_gate_args(skip=True, note=long_note))

        out = capsys.readouterr().out
        assert "satisfied" in out
        assert len(saved) >= 1
        assert saved[-1].get("scan_gate_skipped") is True

    def test_skip_when_already_scanned(self, monkeypatch, capsys):
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(6)  # scan already ran
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_scan_gate(_scan_gate_args(skip=True, note="x" * 50))

        out = capsys.readouterr().out
        assert "already ran" in out

    def test_no_plan_cycle(self, monkeypatch, capsys):
        plan = empty_plan()  # no scan_count_at_plan_start
        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_scan_gate(_scan_gate_args())

        out = capsys.readouterr().out
        assert "not applicable" in out


# ===========================================================================
# Both gates together
# ===========================================================================


class TestBothGatesInteraction:
    """Tests for triage + scan gates operating in sequence."""

    def test_triage_blocks_before_scan_gate_checked(self, monkeypatch, capsys):
        """Triage gate fires first — scan gate never checked."""
        plan = _plan_with_workflow_item(
            triage_complete=False,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(5)  # no scan either
        _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "triage not complete" in out
        assert "no scan has run" not in out  # scan gate not reached

    def test_both_complete_resolves(self, monkeypatch, capsys):
        """Both triage and scan satisfied → clean resolve."""
        plan = _plan_with_workflow_item(
            triage_complete=True,
            scan_count_at_start=5,
        )
        state = _state_with_scan_count(6)
        saved = _mock_plan_io(monkeypatch, plan)
        _mock_state(monkeypatch, state)

        override_mod.cmd_plan_resolve(_args())

        out = capsys.readouterr().out
        assert "Resolved" in out
        assert len(saved) >= 1

    def test_non_gated_workflow_id_bypasses_both(self, monkeypatch, capsys):
        """A non-gated synthetic ID (e.g. triage::observe) isn't affected."""
        plan = empty_plan()
        plan["queue_order"] = ["triage::observe"]

        _mock_plan_io(monkeypatch, plan)

        override_mod.cmd_plan_resolve(_args(patterns=["triage::observe"]))

        out = capsys.readouterr().out
        assert "Resolved" in out
