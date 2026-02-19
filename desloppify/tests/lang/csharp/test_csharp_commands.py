"""Tests for C# detect command registry."""

from desloppify.languages.csharp.commands import get_detect_commands


def test_csharp_detect_commands_registry_contains_mvp_commands():
    commands = get_detect_commands()
    for name in ("deps", "cycles", "orphaned", "dupes", "large", "complexity"):
        assert name in commands
        assert callable(commands[name])
