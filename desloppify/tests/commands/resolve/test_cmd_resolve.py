"""Tests for desloppify.app.commands.resolve — resolve/ignore command logic."""

import argparse
import inspect
from pathlib import Path

import pytest

import desloppify.app.commands.helpers.command_runtime as command_runtime_mod
import desloppify.app.commands.resolve.cmd as resolve_mod
import desloppify.app.commands.resolve.selection as resolve_selection_mod
import desloppify.app.commands.suppress as suppress_mod
import desloppify.app.commands.helpers.state_persistence as state_persistence_mod
import desloppify.engine.plan_state as plan_mod
import desloppify.intelligence.narrative.core as narrative_mod
import desloppify.state as state_mod
from desloppify.app.commands.resolve.cmd import cmd_resolve
from desloppify.app.commands.suppress import cmd_suppress
from desloppify.base.exception_sets import CommandError
from desloppify.engine._work_queue.core import ATTEST_EXAMPLE


@pytest.fixture(autouse=True)
def _isolate_plan(monkeypatch):
    """Prevent resolve tests from touching the real .desloppify/plan.json."""
    monkeypatch.setattr(plan_mod, "has_living_plan", lambda: False)

# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


class TestResolveModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_resolve_callable(self):
        assert callable(cmd_resolve)

    def test_cmd_suppress_callable(self):
        assert callable(cmd_suppress)

    def test_cmd_resolve_signature(self):
        sig = inspect.signature(cmd_resolve)
        params = list(sig.parameters.keys())
        assert params == ["args"]

    def test_cmd_suppress_signature(self):
        sig = inspect.signature(cmd_suppress)
        params = list(sig.parameters.keys())
        assert params == ["args"]


# ---------------------------------------------------------------------------
# cmd_resolve with mocked state
# ---------------------------------------------------------------------------


class TestCmdResolve:
    """Test resolve command with mocked state layer."""

    def test_wontfix_without_note_exits(self, monkeypatch):
        """Wontfix without --note should exit with error."""
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "wontfix"
            note = None
            patterns = ["test::a.ts::foo"]
            lang = None
            path = "."

        with pytest.raises(CommandError) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.exit_code == 1

    def test_fixed_without_attestation_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "fixed"
            note = "Refactored the module to use proper dependency injection patterns"
            attest = None
            patterns = ["test::a.ts::foo"]
            lang = None
            path = "."

        with pytest.raises(CommandError) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Manual resolve requires --attest" in err
        assert "Required keywords: 'I have actually' and 'not gaming'." in err
        assert f'--attest "{ATTEST_EXAMPLE}"' in err

    def test_fixed_with_incomplete_attestation_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "fixed"
            note = "Refactored the module to use proper dependency injection patterns"
            attest = "I fixed this for real."
            patterns = ["test::a.ts::foo"]
            lang = None
            path = "."

        with pytest.raises(CommandError) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "missing required keyword(s)" in err
        assert "'i have actually'" in err
        assert "'not gaming'" in err

    def test_resolve_no_matches(self, monkeypatch, capsys):
        """When no issues match, should print a warning."""
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "require_triage_current_or_exit", lambda **kwargs: None)

        fake_state = {
            "issues": {},
            "overall_score": 50,
            "objective_score": 48,
            "strict_score": 40,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(resolve_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(
            state_mod,
            "resolve_issues",
            lambda state, pattern, status, note, **kwargs: [],
        )

        class FakeArgs:
            status = "fixed"
            note = "Refactored the module to use proper dependency injection patterns"
            attest = "I have actually fixed this and I am not gaming the score."
            patterns = ["nonexistent"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "No open issues" in out

    def test_resolve_successful(self, monkeypatch, capsys):
        """Resolving issues should print a success message."""
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "require_triage_current_or_exit", lambda **kwargs: None)
        monkeypatch.setattr(resolve_mod, "_write_resolve_query_entry", lambda _ctx: None)

        fake_state = {
            "issues": {"f1": {"status": "fixed"}},
            "overall_score": 60,
            "objective_score": 58,
            "strict_score": 50,
            "verified_strict_score": 49,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(resolve_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_persistence_mod, "save_state", lambda state, sp: None)
        monkeypatch.setattr(
            state_mod,
            "resolve_issues",
            lambda state, pattern, status, note, **kwargs: ["f1"],
        )
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": "test", "milestone": None},
        )

        monkeypatch.setattr(resolve_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            status = "fixed"
            note = "Refactored the module to use proper dependency injection patterns"
            attest = "I have actually fixed this and I am not gaming the score."
            patterns = ["f1"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "Resolved 1" in out
        assert "Scores:" in out or "Score" in out

    def test_attested_resolve_reattributes_auto_resolved_and_keeps_open_behavior(
        self, monkeypatch, capsys
    ):
        from types import SimpleNamespace

        from desloppify.app.commands.resolve.plan_load import (
            DegradedPlanWarningState,
            ResolvePlanAccess,
        )
        from desloppify.engine._state.filtering import make_issue
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        open_issue = make_issue(
            "unused",
            "src/open.py",
            "open",
            tier=2,
            confidence="high",
            summary="open issue",
        )
        auto_issue = make_issue(
            "unused",
            "src/auto.py",
            "auto",
            tier=2,
            confidence="high",
            summary="auto-resolved issue",
        )
        auto_issue["status"] = "auto_resolved"
        auto_issue["note"] = "no longer detected by scan"
        wontfix_issue = make_issue(
            "unused",
            "src/wontfix.py",
            "wontfix",
            tier=2,
            confidence="high",
            summary="accepted debt",
        )
        wontfix_issue["status"] = "wontfix"
        false_positive_issue = make_issue(
            "unused",
            "src/false_positive.py",
            "false-positive",
            tier=2,
            confidence="high",
            summary="false positive",
        )
        false_positive_issue["status"] = "false_positive"
        state["work_items"] = {
            open_issue["id"]: open_issue,
            auto_issue["id"]: auto_issue,
            wontfix_issue["id"]: wontfix_issue,
            false_positive_issue["id"]: false_positive_issue,
        }

        monkeypatch.setattr(resolve_mod, "state_path", lambda _args: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "load_state", lambda _path: state)
        monkeypatch.setattr(resolve_mod, "save_state_or_exit", lambda *_args: None)
        monkeypatch.setattr(
            resolve_mod, "require_triage_current_or_exit", lambda **_kwargs: None
        )
        monkeypatch.setattr(resolve_mod, "_check_queue_order_guard", lambda *_a, **_kw: False)
        monkeypatch.setattr(
            resolve_mod,
            "load_resolve_plan_access",
            lambda: ResolvePlanAccess(
                plan=None,
                degraded=False,
                error_kind=None,
                warning_state=DegradedPlanWarningState(),
            ),
        )
        monkeypatch.setattr(
            resolve_mod,
            "update_living_plan_after_resolve",
            lambda **_kwargs: (
                None,
                SimpleNamespace(cluster_name=None, cluster_completed=False),
            ),
        )
        monkeypatch.setattr(resolve_mod, "show_score_with_plan_context", lambda *_a: None)
        monkeypatch.setattr(resolve_mod, "render_commit_guidance", lambda *_a: None)
        monkeypatch.setattr(resolve_mod, "_print_subjective_reset_hint", lambda **_kw: None)
        monkeypatch.setattr(resolve_mod, "_print_next_command", lambda _state: "")
        monkeypatch.setattr(resolve_mod, "_write_resolve_query_entry", lambda _ctx: None)
        monkeypatch.setattr(resolve_mod, "print_fixed_next_user_message", lambda **_kw: None)
        monkeypatch.setattr(resolve_mod, "resolve_lang", lambda _args: None)
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda *_a, **_kw: {"milestone": None},
        )

        note = "Removed both unused names and verified the affected modules still run."
        cmd_resolve(
            argparse.Namespace(
                status="fixed",
                note=note,
                attest=f"I have actually {note} I am not gaming the score.",
                patterns=["unused"],
                force_resolve=False,
                lang=None,
                path=".",
            )
        )

        assert state["work_items"][open_issue["id"]]["status"] == "fixed"
        reattributed = state["work_items"][auto_issue["id"]]
        assert reattributed["status"] == "fixed"
        assert (
            reattributed["resolution_attestation"]["previous_status"]
            == "auto_resolved"
        )
        assert wontfix_issue["status"] == "wontfix"
        assert false_positive_issue["status"] == "false_positive"
        assert "Re-attributed 1 auto-resolved issue(s) as fixed" in capsys.readouterr().out

    def test_auto_resolved_is_not_reattributed_without_attestation(self):
        from desloppify.engine._state.filtering import make_issue
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        issue = make_issue(
            "unused",
            "src/a.py",
            "name",
            tier=2,
            confidence="high",
            summary="unused",
        )
        issue["status"] = "auto_resolved"
        state["work_items"] = {issue["id"]: issue}

        assert state_mod.resolve_issues(
            state,
            issue["id"],
            "fixed",
            note="This note is deliberately long enough to satisfy command requirements.",
            attestation=None,
            reattribute_auto_resolved=True,
        ) == []
        assert issue["status"] == "auto_resolved"

    def test_wontfix_shows_strict_cost_warning(self, monkeypatch, capsys):
        """Wontfix resolution should warn about strict score impact."""
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "_write_resolve_query_entry", lambda _ctx: None)

        fake_state = {
            "issues": {"f1": {"status": "wontfix", "detector": "smells"}},
            "overall_score": 90,
            "objective_score": 88,
            "strict_score": 80,
            "verified_strict_score": 79,
            "stats": {},
            "scan_count": 2,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(resolve_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_persistence_mod, "save_state", lambda state, sp: None)
        monkeypatch.setattr(
            state_mod,
            "resolve_issues",
            lambda state, pattern, status, note, **kwargs: ["f1"],
        )
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": "test", "milestone": None},
        )
        monkeypatch.setattr(resolve_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            status = "wontfix"
            note = "intentional pattern"
            attest = "I have actually reviewed this and I am not gaming the score."
            patterns = ["f1"]
            lang = None
            path = "."
            confirm_batch_wontfix = False

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        # Scores are shown via print_score_update or frozen score display
        assert "Scores" in out or "Plan-start score" in out or "Score" in out

    def test_reopen_without_attestation_allowed(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "_write_resolve_query_entry", lambda _ctx: None)

        fake_state = {
            "issues": {"f1": {"status": "open"}},
            "overall_score": 60,
            "objective_score": 58,
            "strict_score": 50,
            "verified_strict_score": 49,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(resolve_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_persistence_mod, "save_state", lambda state, sp: None)
        monkeypatch.setattr(
            state_mod,
            "resolve_issues",
            lambda state, pattern, status, note, **kwargs: ["f1"],
        )
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": "test", "milestone": None},
        )
        monkeypatch.setattr(resolve_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            status = "open"
            note = "reopened for follow-up"
            attest = None
            patterns = ["f1"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "Reopened 1" in out

    def test_resolve_save_state_error_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "require_triage_current_or_exit", lambda **kwargs: None)

        fake_state = {
            "issues": {"f1": {"status": "fixed"}},
            "overall_score": 60,
            "objective_score": 58,
            "strict_score": 50,
            "verified_strict_score": 49,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(resolve_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(
            state_mod,
            "resolve_issues",
            lambda state, pattern, status, note, **kwargs: ["f1"],
        )
        monkeypatch.setattr(
            state_persistence_mod,
            "save_state",
            lambda state, sp: (_ for _ in ()).throw(OSError("disk full")),
        )

        class FakeArgs:
            status = "fixed"
            note = "Refactored the module to use proper dependency injection patterns"
            attest = "I have actually fixed this and I am not gaming the score."
            patterns = ["f1"]
            lang = None
            path = "."

        with pytest.raises(CommandError) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.exit_code == 1
        assert "could not save state" in exc_info.value.message

    def test_large_wontfix_batch_requires_confirmation(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: Path("/tmp/fake.json"))

        fake_state = {
            "issues": {},
            "overall_score": 90,
            "objective_score": 88,
            "strict_score": 84,
            "stats": {},
            "scan_count": 12,
            "last_scan": "2026-01-01",
        }
        monkeypatch.setattr(resolve_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(
            resolve_selection_mod, "_preview_resolve_count", lambda state, patterns: 12
        )
        monkeypatch.setattr(
            resolve_selection_mod,
            "_estimate_wontfix_strict_delta",
            lambda state, args, **kwargs: 2.4,
        )

        class FakeArgs:
            status = "wontfix"
            note = "intentional debt"
            attest = "I have actually reviewed this and I am not gaming the score."
            patterns = ["smells::*"]
            lang = None
            path = "."
            confirm_batch_wontfix = False

        with pytest.raises(CommandError) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Large wontfix batch detected" in err
        assert "Estimated strict-score debt added now: 2.4 points." in err
        assert "--confirm-batch-wontfix" in exc_info.value.message


class TestCmdSuppress:
    def test_suppress_without_attestation_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            pattern = "unused::*"
            attest = None
            _config = {}
            lang = None
            path = "."

        with pytest.raises(CommandError) as exc_info:
            cmd_suppress(FakeArgs())
        assert exc_info.value.exit_code == 1
        err = capsys.readouterr().err
        assert "Suppress requires --attest" in err
        assert "Required keywords: 'not gaming' and 'i have actually' or 'reviewed'." in err
        assert f'--attest "{ATTEST_EXAMPLE}"' in err

    def test_suppress_save_state_error_exits(self, monkeypatch, capsys):
        from desloppify.app.commands.helpers.command_runtime import CommandRuntime

        fake_state = {"issues": {}}
        fake_runtime = CommandRuntime(
            config={},
            state=fake_state,
            state_path=Path("/tmp/fake.json"),
        )
        monkeypatch.setattr(
            state_persistence_mod,
            "save_state",
            lambda state, sp: (_ for _ in ()).throw(OSError("readonly")),
        )
        monkeypatch.setattr(state_mod, "remove_ignored_issues", lambda state, pattern: 0)
        monkeypatch.setattr(
            suppress_mod, "save_config_or_exit", lambda _config: None
        )
        monkeypatch.setattr(suppress_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            pattern = "unused::*"
            attest = "I have actually reviewed this and I am not gaming the score."
            _config = {}
            lang = None
            path = "."
            runtime = fake_runtime

        with pytest.raises(CommandError) as exc_info:
            cmd_suppress(FakeArgs())
        assert exc_info.value.exit_code == 1
        assert "could not save state" in exc_info.value.message

    def test_suppress_accepts_reviewed_style_attestation(self, monkeypatch):
        from desloppify.app.commands.helpers.command_runtime import CommandRuntime

        fake_runtime = CommandRuntime(
            config={},
            state={"issues": {}, "last_scan": "2026-05-13T00:00:00+00:00"},
            state_path=Path("/tmp/fake.json"),
        )
        monkeypatch.setattr(state_mod, "remove_ignored_issues", lambda state, pattern: 0)
        monkeypatch.setattr(suppress_mod, "save_config_or_exit", lambda _config: None)
        monkeypatch.setattr(suppress_mod, "save_state_or_exit", lambda _state, _state_file: None)
        monkeypatch.setattr(suppress_mod, "show_score_with_plan_context", lambda *_a, **_k: None)
        monkeypatch.setattr(suppress_mod, "check_config_staleness", lambda _config: None)
        monkeypatch.setattr(suppress_mod, "resolve_lang", lambda args: None)
        monkeypatch.setattr(suppress_mod.narrative_mod, "compute_narrative", lambda *_a, **_k: {})
        monkeypatch.setattr(suppress_mod, "write_query", lambda _payload: None)

        class FakeArgs:
            pattern = "unused::*"
            attest = "I reviewed this suppress decision and I am not gaming the score."
            _config = {}
            lang = None
            path = "."
            runtime = fake_runtime

        cmd_suppress(FakeArgs())


class TestResolveHelperModules:
    def test_command_runtime_prefers_explicit_runtime(self) -> None:
        runtime = command_runtime_mod.CommandRuntime(
            config={"strict_target": 95},
            state={"issues": {}},
            state_path=Path("/tmp/desloppify-state.json"),
        )

        loaded = command_runtime_mod.command_runtime(argparse.Namespace(runtime=runtime))

        assert loaded is runtime
        assert loaded.config["strict_target"] == 95
        assert loaded.state == {"issues": {}}
        assert loaded.state_path == Path("/tmp/desloppify-state.json")

    def test_command_runtime_builds_runtime_from_config_and_state(self, monkeypatch) -> None:
        fake_state = {"issues": {"one": {"status": "open"}}}
        captured: dict[str, object] = {}

        def _fake_load_state(path: Path) -> dict[str, object]:
            captured["state_path"] = path
            return fake_state

        monkeypatch.setattr(command_runtime_mod, "load_config", lambda: {"badge": True})
        monkeypatch.setattr(command_runtime_mod, "state_path", lambda _args: "var/desloppify.json")
        monkeypatch.setattr(command_runtime_mod, "load_state", _fake_load_state)

        runtime = command_runtime_mod.command_runtime(argparse.Namespace())

        assert runtime.config == {"badge": True}
        assert runtime.state == fake_state
        assert runtime.state_path == Path("var/desloppify.json")
        assert captured["state_path"] == Path("var/desloppify.json")

    def test_state_persistence_helpers_delegate_and_wrap_os_errors(self, monkeypatch) -> None:
        saved: dict[str, object] = {}

        monkeypatch.setattr(
            state_persistence_mod,
            "save_state",
            lambda state, state_file: saved.update(state=state, state_file=state_file),
        )
        monkeypatch.setattr(
            state_persistence_mod.config_mod,
            "save_config",
            lambda config: saved.update(config=config),
        )

        state = {"issues": {}}
        state_file = Path("/tmp/desloppify-state.json")
        config = {"strict_target": 95}

        state_persistence_mod.save_state_or_exit(state, state_file)
        state_persistence_mod.save_config_or_exit(config)

        assert saved["state"] is state
        assert saved["state_file"] == state_file
        assert saved["config"] is config

        monkeypatch.setattr(
            state_persistence_mod,
            "save_state",
            lambda *_args: (_ for _ in ()).throw(OSError("readonly")),
        )
        monkeypatch.setattr(
            state_persistence_mod.config_mod,
            "save_config",
            lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(CommandError, match="could not save state: readonly"):
            state_persistence_mod.save_state_or_exit(state, state_file)
        with pytest.raises(CommandError, match="could not save config: disk full"):
            state_persistence_mod.save_config_or_exit(config)
