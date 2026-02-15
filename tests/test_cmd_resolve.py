"""Tests for desloppify.commands.resolve — resolve/ignore command logic."""

import inspect

import pytest

from desloppify.commands.resolve import cmd_resolve, cmd_ignore_pattern


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
        from desloppify.commands import resolve as resolve_mod

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

    def test_resolve_no_matches(self, monkeypatch, capsys):
        """When no findings match, should print a warning."""
        from desloppify.commands import resolve as resolve_mod
        import desloppify.state as state_mod

        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")

        fake_state = {
            "findings": {}, "score": 50, "strict_score": 40,
            "stats": {}, "scan_count": 1, "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_mod, "resolve_findings",
                            lambda state, pattern, status, note: [])

        class FakeArgs:
            status = "fixed"
            note = "done"
            patterns = ["nonexistent"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "No open findings" in out

    def test_resolve_successful(self, monkeypatch, capsys):
        """Resolving findings should print a success message."""
        from desloppify.commands import resolve as resolve_mod
        import desloppify.state as state_mod
        import desloppify.narrative as narrative_mod
        import desloppify.cli as cli_mod

        monkeypatch.setattr(resolve_mod, "state_path", lambda a: "/tmp/fake.json")
        monkeypatch.setattr(resolve_mod, "_write_query", lambda payload: None)

        fake_state = {
            "findings": {"f1": {"status": "fixed"}},
            "score": 60, "strict_score": 50,
            "stats": {}, "scan_count": 1, "last_scan": "2025-01-01",
        }
        monkeypatch.setattr(state_mod, "load_state", lambda sp: fake_state)
        monkeypatch.setattr(state_mod, "save_state", lambda state, sp: None)
        monkeypatch.setattr(state_mod, "resolve_findings",
                            lambda state, pattern, status, note: ["f1"])
        monkeypatch.setattr(narrative_mod, "compute_narrative",
                            lambda state, **kw: {"headline": "test", "milestone": None})

        # Mock _resolve_lang
        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            status = "fixed"
            note = "done"
            patterns = ["f1"]
            lang = None
            path = "."

        cmd_resolve(FakeArgs())
        out = capsys.readouterr().out
        assert "Resolved 1" in out
        assert "Score:" in out
