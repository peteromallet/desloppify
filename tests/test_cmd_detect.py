"""Tests for desloppify.commands.detect — single detector runner."""

import inspect
import sys

import pytest

from desloppify.commands.detect import cmd_detect


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------

class TestDetectModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_detect_callable(self):
        assert callable(cmd_detect)

    def test_cmd_detect_signature(self):
        sig = inspect.signature(cmd_detect)
        params = list(sig.parameters.keys())
        assert params == ["args"]


# ---------------------------------------------------------------------------
# cmd_detect behaviour
# ---------------------------------------------------------------------------

class TestCmdDetect:
    """Test cmd_detect dispatch and validation."""

    def test_no_lang_exits(self, monkeypatch):
        """When no language is specified, cmd_detect should exit."""
        import desloppify.commands._helpers as cli_mod
        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: None)

        class FakeArgs:
            detector = "unused"
            lang = None
            path = "."
            threshold = None

        with pytest.raises(SystemExit) as exc_info:
            cmd_detect(FakeArgs())
        assert exc_info.value.code == 1

    def test_unknown_detector_exits(self, monkeypatch):
        """When detector name is invalid for the language, should exit."""
        import desloppify.commands._helpers as cli_mod

        class FakeLang:
            name = "typescript"
            detect_commands = {"unused": lambda a: None, "smells": lambda a: None}
            large_threshold = 300

        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "nonexistent_detector"
            lang = "typescript"
            path = "."
            threshold = None

        with pytest.raises(SystemExit) as exc_info:
            cmd_detect(FakeArgs())
        assert exc_info.value.code == 1

    def test_valid_detector_dispatches(self, monkeypatch):
        """When detector is valid, it should be called."""
        import desloppify.commands._helpers as cli_mod

        calls = []

        class FakeLang:
            name = "typescript"
            detect_commands = {"unused": lambda a: calls.append("unused")}
            large_threshold = 300

        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "unused"
            lang = "typescript"
            path = "."
            threshold = None

        cmd_detect(FakeArgs())
        assert calls == ["unused"]

    def test_large_threshold_default(self, monkeypatch):
        """When detector is 'large' and threshold is None, use lang.large_threshold."""
        import desloppify.commands._helpers as cli_mod

        captured_args = []

        class FakeLang:
            name = "typescript"
            detect_commands = {"large": lambda a: captured_args.append(a)}
            large_threshold = 500

        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "large"
            lang = "typescript"
            path = "."
            threshold = None

        cmd_detect(FakeArgs())
        assert len(captured_args) == 1
        assert captured_args[0].threshold == 500

    def test_dupes_threshold_default(self, monkeypatch):
        """When detector is 'dupes' and threshold is None, default to 0.8."""
        import desloppify.commands._helpers as cli_mod

        captured_args = []

        class FakeLang:
            name = "typescript"
            detect_commands = {"dupes": lambda a: captured_args.append(a)}
            large_threshold = 300

        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "dupes"
            lang = "typescript"
            path = "."
            threshold = None

        cmd_detect(FakeArgs())
        assert len(captured_args) == 1
        assert captured_args[0].threshold == 0.8

    def test_explicit_threshold_not_overridden(self, monkeypatch):
        """When user provides --threshold, it should not be overridden."""
        import desloppify.commands._helpers as cli_mod

        captured_args = []

        class FakeLang:
            name = "typescript"
            detect_commands = {"large": lambda a: captured_args.append(a)}
            large_threshold = 500

        monkeypatch.setattr(cli_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "large"
            lang = "typescript"
            path = "."
            threshold = 200  # user-provided

        cmd_detect(FakeArgs())
        assert captured_args[0].threshold == 200
