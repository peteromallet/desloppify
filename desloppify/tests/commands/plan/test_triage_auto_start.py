"""Tests for auto-start triage on --stage observe."""

from __future__ import annotations

import argparse
from pathlib import Path

import desloppify.app.commands.plan.triage.command as triage_mod
from desloppify.app.commands.plan.triage import helpers as triage_helpers
import desloppify.app.commands.plan.triage.workflow as triage_workflow_mod
from desloppify.app.commands.plan.triage.services import TriageServices
from desloppify.engine._plan.schema import empty_plan
from desloppify.engine._plan.constants import TRIAGE_IDS, TRIAGE_STAGE_IDS

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
        "run_stages": False,
        "runner": "codex",
        "report_file": None,
        "only_stages": None,
        "stage_prompt": None,
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
# Tests
# ---------------------------------------------------------------------------

class TestAutoStartTriage:
    def test_observe_auto_starts_triage(self, monkeypatch, capsys):
        """When no triage stages in queue, --stage observe auto-starts then blocks on strategize."""
        plan = empty_plan()
        # No triage stage IDs in queue_order
        assert not any(sid in plan.get("queue_order", []) for sid in TRIAGE_IDS)

        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")
        _patch_triage(monkeypatch, plan, state)

        long_report = (
            "This is a thorough analysis of the naming and architecture issues. "
            "The main themes are inconsistent naming conventions across modules, "
            "and some architectural coupling between components."
        )
        args = _fake_args(stage="observe", report=long_report)
        triage_mod.cmd_plan_triage(args)

        # All triage stage IDs should now be in queue
        assert all(sid in plan.get("queue_order", []) for sid in TRIAGE_STAGE_IDS)
        # Observe remains blocked until strategize runs
        stages = plan.get("epic_triage_meta", {}).get("triage_stages", {})
        assert "observe" not in stages
        out = capsys.readouterr().out
        assert "cannot observe" in out.lower()
        assert "strategize" in out

    def test_observe_auto_start_prints_note(self, monkeypatch, capsys):
        """Auto-start prints a note about injecting triage::pending."""
        plan = empty_plan()
        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")
        _patch_triage(monkeypatch, plan, state)

        long_report = (
            "This is a thorough analysis of the naming and architecture issues. "
            "The main themes are inconsistent naming conventions across modules, "
            "and some architectural coupling between components."
        )
        args = _fake_args(stage="observe", report=long_report)
        triage_mod.cmd_plan_triage(args)

        out = capsys.readouterr().out
        assert "auto-started" in out.lower()

    def test_observe_works_normally_when_already_started(self, monkeypatch, capsys):
        """When strategize is already recorded, observe proceeds without double-injection."""
        plan = empty_plan()
        plan["queue_order"] = list(TRIAGE_STAGE_IDS)
        plan["epic_triage_meta"] = {
            "triage_stages": {
                "strategize": {
                    "stage": "strategize",
                    "report": "{}",
                    "timestamp": "2025-06-01T00:00:00Z",
                    "confirmed_at": "2025-06-01T00:00:00Z",
                    "confirmed_text": "auto-confirmed",
                }
            }
        }

        state = _state_with_issues("r1", "r2", "r3", "r4", "r5")
        _patch_triage(monkeypatch, plan, state)

        long_report = (
            "This is a thorough analysis of the naming and architecture issues. "
            "The main themes are inconsistent naming conventions across modules, "
            "and some architectural coupling between components."
        )
        args = _fake_args(stage="observe", report=long_report)
        triage_mod.cmd_plan_triage(args)

        out = capsys.readouterr().out
        assert "auto-started" not in out.lower()
        # No duplicate stage IDs
        for sid in TRIAGE_STAGE_IDS:
            assert plan["queue_order"].count(sid) == 1
        # Stage should be recorded
        stages = plan.get("epic_triage_meta", {}).get("triage_stages", {})
        assert "observe" in stages

    def test_inject_triage_stages_prepends_and_deduplicates(self):
        """Inject helper keeps one copy of each stage ID at queue front."""
        plan = {
            "queue_order": [
                "review::a.py::x1",
                TRIAGE_STAGE_IDS[2],
                "review::b.py::x2",
                TRIAGE_STAGE_IDS[0],
                TRIAGE_STAGE_IDS[4],
            ]
        }

        triage_helpers.inject_triage_stages(plan)

        assert plan["queue_order"][: len(TRIAGE_STAGE_IDS)] == list(TRIAGE_STAGE_IDS)
        for sid in TRIAGE_STAGE_IDS:
            assert plan["queue_order"].count(sid) == 1
        assert plan["queue_order"][len(TRIAGE_STAGE_IDS) :] == [
            "review::a.py::x1",
            "review::b.py::x2",
        ]

    def test_inject_triage_stages_clears_skipped_entries(self):
        """Inject helper removes triage stage IDs from skipped."""
        plan = {
            "queue_order": ["review::a.py::x1"],
            "skipped": {
                "triage::enrich": {"kind": "temporary"},
                "triage::sense-check": {"kind": "temporary"},
                "review::z.py::x9": {"kind": "temporary"},
            },
        }

        triage_helpers.inject_triage_stages(plan)

        assert "triage::enrich" not in plan["skipped"]
        assert "triage::sense-check" not in plan["skipped"]
        assert "review::z.py::x9" in plan["skipped"]

    def test_cmd_plan_triage_run_stages_reads_report_file_before_runner_dispatch(
        self,
        monkeypatch,
        tmp_path: Path,
        capsys,
    ) -> None:
        plan = empty_plan()
        state = _state_with_issues("r1", "r2", "r3")
        _patch_triage(monkeypatch, plan, state)
        monkeypatch.setattr(triage_mod, "require_issue_inventory", lambda _state: True)

        report_file = tmp_path / "sense-check.txt"
        report_file.write_text(
            "This report came from a file and should be loaded before staged runner dispatch.",
            encoding="utf-8",
        )

        seen: dict[str, object] = {}

        def fake_run_codex_pipeline(args, *, stages_to_run, services):
            seen["report"] = args.report
            seen["report_file"] = args.report_file
            seen["stages_to_run"] = stages_to_run
            seen["services"] = services
            run_dir = tmp_path / ".desloppify" / "triage_runs" / "fake-run"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "run_summary.json").write_text("{}", encoding="utf-8")
            print(f"runner wrote: {run_dir}")

        monkeypatch.setattr(triage_workflow_mod, "run_codex_pipeline", fake_run_codex_pipeline)

        args = _fake_args(
            run_stages=True,
            runner="codex",
            report=None,
            report_file=str(report_file),
            only_stages="observe",
        )
        triage_mod.cmd_plan_triage(args)

        out = capsys.readouterr().out
        assert seen["report"] == report_file.read_text(encoding="utf-8")
        assert seen["report_file"] == str(report_file)
        assert seen["stages_to_run"] == ["observe"]
        assert seen["services"] is not None
        assert "runner wrote:" in out
