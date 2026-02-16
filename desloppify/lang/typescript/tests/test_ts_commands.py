"""Tests for desloppify.lang.typescript.commands — command registry."""

from desloppify.lang.typescript.commands import get_detect_commands


# ── get_detect_commands() ─────────────────────────────────────


def test_returns_dict():
    """get_detect_commands() returns a dict."""
    cmds = get_detect_commands()
    assert isinstance(cmds, dict)


def test_keys_are_strings():
    """All keys in the command registry are strings."""
    cmds = get_detect_commands()
    for key in cmds:
        assert isinstance(key, str)


def test_values_are_callable():
    """All values in the command registry are callable."""
    cmds = get_detect_commands()
    for key, val in cmds.items():
        assert callable(val), f"Command '{key}' is not callable"


def test_expected_commands_present():
    """Core detect commands are present in the registry."""
    cmds = get_detect_commands()
    expected = [
        "logs", "unused", "exports", "deprecated", "large",
        "complexity", "gods", "single-use", "props", "passthrough",
        "concerns", "dupes", "smells", "coupling", "patterns",
        "naming", "cycles", "orphaned", "react", "facade",
    ]
    for name in expected:
        assert name in cmds, f"Expected command '{name}' not found"


def test_non_empty():
    """Command registry has at least 10 entries."""
    cmds = get_detect_commands()
    assert len(cmds) >= 10
