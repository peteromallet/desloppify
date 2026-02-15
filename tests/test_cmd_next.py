"""Tests for desloppify.commands.next — import verification and structure."""

import inspect

import pytest

from desloppify.commands.next import cmd_next


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestNextModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_next_callable(self):
        assert callable(cmd_next)

    def test_cmd_next_signature(self):
        sig = inspect.signature(cmd_next)
        params = list(sig.parameters.keys())
        assert params == ["args"]

    def test_module_docstring(self):
        import desloppify.commands.next as mod
        assert mod.__doc__ is not None
        assert "next" in mod.__doc__.lower()


# ---------------------------------------------------------------------------
# cmd_next output formatting (via monkeypatch)
# ---------------------------------------------------------------------------

class TestCmdNextOutput:
    """Test cmd_next output for empty state."""

    def test_no_items_prints_nothing_to_do(self, monkeypatch, capsys):
        """When there are no open findings, cmd_next should say 'Nothing to do'."""
        from desloppify.commands import next as next_mod
        from desloppify import cli as cli_mod

        # Mock load_state to return empty state
        def mock_load_state(sp):
            return {"findings": {}, "score": 100, "stats": {}}

        # Mock get_next_items to return empty list
        def mock_get_next_items(state, tier, count, scan_path=None):
            return []

        # Mock state_path
        def mock_state_path(args):
            return "/tmp/fake-state.json"

        # Mock check_tool_staleness
        def mock_check_staleness(state):
            return None

        # Mock _write_query (still private)
        written = []
        def mock_write_query(payload):
            written.append(payload)

        monkeypatch.setattr(next_mod, "state_path", mock_state_path)
        monkeypatch.setattr(next_mod, "_write_query", mock_write_query)

        # We need to patch the lazy imports inside cmd_next
        import desloppify.state as state_mod
        import desloppify.plan as plan_mod
        import desloppify.utils as utils_mod
        monkeypatch.setattr(state_mod, "load_state", mock_load_state)
        monkeypatch.setattr(plan_mod, "get_next_items", mock_get_next_items)
        monkeypatch.setattr(utils_mod, "check_tool_staleness", mock_check_staleness)

        class FakeArgs:
            tier = None
            count = 1
            output = None
            lang = None
            path = "."

        cmd_next(FakeArgs())
        out = capsys.readouterr().out
        assert "Nothing to do" in out
        assert len(written) == 1
        assert written[0]["command"] == "next"
        assert written[0]["items"] == []
