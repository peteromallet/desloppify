"""Tests for desloppify.app.commands.resolve — resolve/ignore command logic."""

import inspect

import pytest

import desloppify.app.commands.resolve.apply as resolve_apply_mod
import desloppify.app.commands.resolve.cmd as resolve_mod
import desloppify.app.commands.resolve.selection as resolve_selection_mod
import desloppify.cli as cli_mod
import desloppify.intelligence.narrative as narrative_mod
import desloppify.state as state_mod
from desloppify.app.commands.resolve.cmd import cmd_ignore_pattern, cmd_resolve
from desloppify.engine.work_queue import ATTEST_EXAMPLE

# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


class TestResolveModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_resolve_callable(self):
        assert callable(cmd_resolve)

    def test_cmd_ignore_pattern_callable(self):
        assert callable(cmd_ignore_pattern)

    def test_cmd_resolve_signature(self):
        sig = inspect.signature(cmd_resolve)
        params = list(sig.parameters.keys())
        assert params == ["args"]

    def test_cmd_ignore_pattern_signature(self):
        sig = inspect.signature(cmd_ignore_pattern)
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

        with pytest.raises(SystemExit) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.code == 1

    def test_fixed_without_attestation_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "fixed"
            note = "done"
            attest = None
            patterns = ["test::a.ts::foo"]
            lang = None
            path = "."

        with pytest.raises(SystemExit) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Manual resolve requires --attest" in out
        assert "Required keywords: 'I have actually' and 'not gaming'." in out
        assert f'--attest "{ATTEST_EXAMPLE}"' in out

    def test_fixed_with_incomplete_attestation_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            status = "fixed"
            note = "done"
            attest = "I fixed this for real."
            patterns = ["test::a.ts::foo"]
            lang = None
            path = "."

        with pytest.raises(SystemExit) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "missing required keyword(s)" in out
        assert "'i have actually'" in out
        assert "'not gaming'" in out

    def test_resolve_no_matches(self, monkeypatch, capsys):
        """When no findings match, should print a warning."""
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        fake_state = {
            "findings": {},
            "overall_score": 50,
            "objective_score": 48,
            "strict_score": 40,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(
            state_mod,
            "resolve_findings",
            lambda state, pattern, status, note, **kwargs: [],
        )

        class FakeArgs:
            status = "fixed"
            note = "done"
            attest = "I have actually fixed this and I am not gaming the score."
            patterns = ["nonexistent"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "No open findings" in out

    def test_resolve_successful(self, monkeypatch, capsys):
        """Resolving findings should print a success message."""
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_apply_mod, "write_query", lambda payload: None)

        fake_state = {
            "findings": {"f1": {"status": "fixed"}},
            "overall_score": 60,
            "objective_score": 58,
            "strict_score": 50,
            "verified_strict_score": 49,
            "stats": {},
            "scan_count": 1,
            "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_mod, "save_state", lambda state, sp: None)
        monkeypatch.setattr(
            state_mod,
            "resolve_findings",
            lambda state, pattern, status, note, **kwargs: ["f1"],
        )
        monkeypatch.setattr(
            narrative_mod,
            "compute_narrative",
            lambda state, **kw: {"headline": "test", "milestone": None},
        )

        # Mock _resolve_lang
        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            status = "fixed"
            note = "done"
            attest = "I have actually fixed this and I am not gaming the score."
            patterns = ["f1"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "Resolved 1" in out
        assert "Scores:" in out

    def test_large_wontfix_batch_requires_confirmation(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        fake_state = {
            "findings": {},
            "overall_score": 90,
            "objective_score": 88,
            "strict_score": 84,
            "stats": {},
            "scan_count": 12,
            "last_scan": "2026-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
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

        with pytest.raises(SystemExit) as exc_info:
            cmd_resolve(FakeArgs())
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Large wontfix batch detected" in out
        assert "Estimated strict-score debt added now: 2.4 points." in out
        assert "--confirm-batch-wontfix" in out


class TestCmdIgnore:
    def test_ignore_without_attestation_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        class FakeArgs:
            pattern = "unused::*"
            attest = None
            _config = {}
            lang = None
            path = "."

        with pytest.raises(SystemExit) as exc_info:
            cmd_ignore_pattern(FakeArgs())
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Ignore requires --attest" in out
        assert "Required keywords: 'I have actually' and 'not gaming'." in out
        assert f'--attest "{ATTEST_EXAMPLE}"' in out
