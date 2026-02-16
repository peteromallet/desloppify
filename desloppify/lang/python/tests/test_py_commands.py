"""Tests for desloppify.lang.python.commands — command registry."""

import pytest

from desloppify.lang.python.commands import get_detect_commands


class TestGetDetectCommands:
    def test_returns_dict(self):
        commands = get_detect_commands()
        assert isinstance(commands, dict)

    def test_keys_are_strings(self):
        commands = get_detect_commands()
        for key in commands:
            assert isinstance(key, str)

    def test_values_are_callable(self):
        commands = get_detect_commands()
        for value in commands.values():
            assert callable(value)

    def test_expected_commands_present(self):
        commands = get_detect_commands()
        expected = {
            "unused", "large", "complexity", "gods",
            "props", "smells", "dupes", "deps",
            "cycles", "orphaned", "single_use", "naming",
            "facade",
        }
        assert expected <= set(commands.keys())

    def test_no_empty_keys(self):
        commands = get_detect_commands()
        for key in commands:
            assert key.strip() != ""

    def test_stable_across_calls(self):
        """Calling get_detect_commands twice returns the same set of keys."""
        c1 = get_detect_commands()
        c2 = get_detect_commands()
        assert set(c1.keys()) == set(c2.keys())
