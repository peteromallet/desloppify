"""Tests for desloppify.app.commands.detect — single detector runner."""

import inspect

import pytest

import desloppify.app.commands.detect as detect_mod
from desloppify.app.commands.detect import cmd_detect


class _FakeLangBase:
    runtime_option_specs: dict[str, object] = {}
    runtime_option_aliases: dict[str, str] = {}
    setting_specs: dict[str, object] = {}

    def normalize_settings(self, values):
        return values if isinstance(values, dict) else {}

    def normalize_runtime_options(self, values, *, strict=False):
        values = values if isinstance(values, dict) else {}
        if strict and values:
            raise KeyError("Unknown runtime option(s)")
        return values


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
        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: None)

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

        class FakeLang(_FakeLangBase):
            name = "typescript"
            detect_commands = {"unused": lambda a: None, "smells": lambda a: None}
            large_threshold = 300

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

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
        calls = []

        class FakeLang(_FakeLangBase):
            name = "typescript"
            detect_commands = {"unused": lambda a: calls.append("unused")}
            large_threshold = 300

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "unused"
            lang = "typescript"
            path = "."
            threshold = None

        cmd_detect(FakeArgs())
        assert calls == ["unused"]

    def test_large_threshold_default(self, monkeypatch):
        """When detector is 'large' and threshold is None, use lang.large_threshold."""
        captured_args = []

        class FakeLang(_FakeLangBase):
            name = "typescript"
            detect_commands = {"large": lambda a: captured_args.append(a)}
            large_threshold = 500

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

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
        captured_args = []

        class FakeLang(_FakeLangBase):
            name = "typescript"
            detect_commands = {"dupes": lambda a: captured_args.append(a)}
            large_threshold = 300

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

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
        captured_args = []

        class FakeLang(_FakeLangBase):
            name = "typescript"
            detect_commands = {"large": lambda a: captured_args.append(a)}
            large_threshold = 500

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "large"
            lang = "typescript"
            path = "."
            threshold = 200  # user-provided

        cmd_detect(FakeArgs())
        assert captured_args[0].threshold == 200

    def test_hyphen_alias_resolves_to_underscore_key(self, monkeypatch):
        """Hyphenated detector input resolves to underscore command key."""
        calls = []

        class FakeLang(_FakeLangBase):
            name = "python"
            detect_commands = {"single_use": lambda a: calls.append("single_use")}
            large_threshold = 300

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "single-use"
            lang = "python"
            path = "."
            threshold = None

        cmd_detect(FakeArgs())
        assert calls == ["single_use"]

    def test_passthrough_alias_maps_to_props_when_passthrough_missing(
        self, monkeypatch
    ):
        """Legacy passthrough alias is no longer accepted."""

        class FakeLang(_FakeLangBase):
            name = "python"
            detect_commands = {"props": lambda a: None}
            large_threshold = 300

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "passthrough"
            lang = "python"
            path = "."
            threshold = None

        with pytest.raises(SystemExit) as exc_info:
            cmd_detect(FakeArgs())
        assert exc_info.value.code == 1

    def test_runtime_options_are_passed_without_lang_run_shim(self, monkeypatch):
        """Detector commands receive normalized runtime options via args payload."""
        captured = {}

        class FakeLang(_FakeLangBase):
            name = "csharp"
            detect_commands = {
                "deps": lambda a: captured.setdefault(
                    "runtime_options", getattr(a, "lang_runtime_options", None)
                )
            }
            large_threshold = 300
            runtime_option_specs = {"roslyn_cmd": object()}
            runtime_option_aliases = {"roslyn_cmd": "roslyn_cmd"}

            def normalize_runtime_options(self, values, *, strict=False):
                return dict(values or {})

        monkeypatch.setattr(detect_mod, "resolve_lang", lambda args: FakeLang())

        class FakeArgs:
            detector = "deps"
            lang = "csharp"
            path = "."
            threshold = None
            lang_opt = ["roslyn_cmd=custom-roslyn --json"]

        args = FakeArgs()
        cmd_detect(args)
        assert captured["runtime_options"] == {"roslyn_cmd": "custom-roslyn --json"}
        assert args.lang_runtime_options is None
