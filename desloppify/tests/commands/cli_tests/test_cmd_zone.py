"""Tests for desloppify.app.commands.zone_cmd — zone command helpers."""

import desloppify.core.config as config_mod
from desloppify.app.commands.helpers.runtime import CommandRuntime
from desloppify.app.commands.zone_cmd import (
    _zone_clear,
    _zone_set,
    _zone_show,
    cmd_zone,
)

# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


class TestZoneModuleSanity:
    """Verify the module imports and has expected exports."""

    def test_cmd_zone_callable(self):
        assert callable(cmd_zone)

    def test_zone_show_callable(self):
        assert callable(_zone_show)

    def test_zone_set_callable(self):
        assert callable(_zone_set)

    def test_zone_clear_callable(self):
        assert callable(_zone_clear)


# ---------------------------------------------------------------------------
# cmd_zone dispatch
# ---------------------------------------------------------------------------


class TestCmdZoneDispatch:
    """cmd_zone dispatches to sub-actions based on zone_action attr."""

    def test_missing_action_defaults_to_show(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd._zone_show",
            lambda args: calls.append("show"),
        )

        class FakeArgs:
            zone_action = None

        cmd_zone(FakeArgs())
        assert calls == ["show"]

    def test_show_action_dispatches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd._zone_show",
            lambda args: calls.append("show"),
        )

        class FakeArgs:
            zone_action = "show"

        cmd_zone(FakeArgs())
        assert calls == ["show"]

    def test_set_action_dispatches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd._zone_set",
            lambda args: calls.append("set"),
        )

        class FakeArgs:
            zone_action = "set"

        cmd_zone(FakeArgs())
        assert calls == ["set"]

    def test_clear_action_dispatches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd._zone_clear",
            lambda args: calls.append("clear"),
        )

        class FakeArgs:
            zone_action = "clear"

        cmd_zone(FakeArgs())
        assert calls == ["clear"]

    def test_unknown_action_prints_usage(self, capsys):
        import pytest

        class FakeArgs:
            zone_action = "bogus"

        with pytest.raises(SystemExit, match="1"):
            cmd_zone(FakeArgs())
        err = capsys.readouterr().err
        assert "Usage:" in err


# ---------------------------------------------------------------------------
# _zone_set
# ---------------------------------------------------------------------------


class TestZoneSet:
    """_zone_set validates zone values and persists overrides."""

    def test_invalid_zone_value(self, monkeypatch, capsys):
        """Setting an invalid zone value should exit with error."""
        import pytest

        fake_config = {"zone_overrides": {}}

        class FakeArgs:
            zone_path = "src/foo.ts"
            zone_value = "invalid_zone"
            lang = None
            path = "."
            runtime = CommandRuntime(
                config=fake_config,
                state={},
                state_path=None,
            )

        with pytest.raises(SystemExit, match="1"):
            _zone_set(FakeArgs())
        err = capsys.readouterr().err
        assert "Invalid zone" in err

    def test_valid_zone_value_saves(self, monkeypatch, capsys):
        """Setting a valid zone value should save config."""

        saved = []
        fake_config = {"zone_overrides": {}}
        monkeypatch.setattr(
            config_mod, "save_config", lambda cfg, path=None: saved.append(dict(cfg))
        )
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd.rel", lambda p: p,
        )

        class FakeArgs:
            zone_path = "src/foo.ts"
            zone_value = "test"
            lang = None
            path = "."
            runtime = CommandRuntime(
                config=fake_config,
                state={},
                state_path=None,
            )

        _zone_set(FakeArgs())
        out = capsys.readouterr().out
        assert "src/foo.ts" in out
        assert "test" in out
        assert len(saved) == 1
        assert saved[0]["zone_overrides"]["src/foo.ts"] == "test"


# ---------------------------------------------------------------------------
# _zone_clear
# ---------------------------------------------------------------------------


class TestZoneClear:
    """_zone_clear removes zone overrides."""

    def test_clear_existing_override(self, monkeypatch, capsys):
        saved = []
        fake_config = {"zone_overrides": {"src/foo.ts": "test"}}
        monkeypatch.setattr(
            config_mod, "save_config", lambda cfg, path=None: saved.append(dict(cfg))
        )
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd.rel", lambda p: p,
        )

        class FakeArgs:
            zone_path = "src/foo.ts"
            lang = None
            path = "."
            runtime = CommandRuntime(
                config=fake_config,
                state={},
                state_path=None,
            )

        _zone_clear(FakeArgs())
        out = capsys.readouterr().out
        assert "Cleared" in out
        assert len(saved) == 1
        assert "src/foo.ts" not in fake_config["zone_overrides"]

    def test_clear_nonexistent_override(self, monkeypatch, capsys):
        fake_config = {"zone_overrides": {}}
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd.rel", lambda p: p,
        )

        class FakeArgs:
            zone_path = "src/bar.ts"
            lang = None
            path = "."
            runtime = CommandRuntime(
                config=fake_config,
                state={},
                state_path=None,
            )

        _zone_clear(FakeArgs())
        out = capsys.readouterr().out
        assert "No override found" in out


# ---------------------------------------------------------------------------
# Zone path normalization (#159)
# ---------------------------------------------------------------------------


class TestZonePathNormalization:
    """_zone_set and _zone_clear normalize paths with rel() before storing."""

    def test_zone_set_stores_normalized_key(self, monkeypatch, capsys):
        """_zone_set uses rel() to normalize the path before storing."""
        saved = []
        fake_config = {"zone_overrides": {}}
        monkeypatch.setattr(
            config_mod, "save_config", lambda cfg, path=None: saved.append(dict(cfg))
        )
        # rel() normalizes the absolute path to relative form
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd.rel",
            lambda p: "src/file.py",
        )

        class FakeArgs:
            zone_path = "/absolute/project/src/file.py"
            zone_value = "production"
            lang = None
            path = "."
            runtime = CommandRuntime(
                config=fake_config,
                state={},
                state_path=None,
            )

        _zone_set(FakeArgs())
        assert len(saved) == 1
        # Key should be the normalized form, not the raw input
        assert "src/file.py" in saved[0]["zone_overrides"]
        assert "/absolute/project/src/file.py" not in saved[0]["zone_overrides"]

    def test_zone_clear_uses_normalized_key(self, monkeypatch, capsys):
        """_zone_clear uses rel() to normalize path for lookup."""
        saved = []
        fake_config = {"zone_overrides": {"src/file.py": "test"}}
        monkeypatch.setattr(
            config_mod, "save_config", lambda cfg, path=None: saved.append(dict(cfg))
        )
        monkeypatch.setattr(
            "desloppify.app.commands.zone_cmd.rel",
            lambda p: "src/file.py",
        )

        class FakeArgs:
            zone_path = "/absolute/project/src/file.py"
            lang = None
            path = "."
            runtime = CommandRuntime(
                config=fake_config,
                state={},
                state_path=None,
            )

        _zone_clear(FakeArgs())
        out = capsys.readouterr().out
        assert "Cleared" in out
        assert "src/file.py" not in fake_config["zone_overrides"]
