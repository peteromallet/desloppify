"""Tests for desloppify.commands.zone_cmd — zone command helpers."""



from desloppify.commands.zone_cmd import cmd_zone, _zone_set, _zone_clear, _zone_show


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
            "desloppify.commands.zone_cmd._zone_show",
            lambda args: calls.append("show"),
        )

        class FakeArgs:
            zone_action = None

        cmd_zone(FakeArgs())
        assert calls == ["show"]

    def test_show_action_dispatches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.commands.zone_cmd._zone_show",
            lambda args: calls.append("show"),
        )

        class FakeArgs:
            zone_action = "show"

        cmd_zone(FakeArgs())
        assert calls == ["show"]

    def test_set_action_dispatches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.commands.zone_cmd._zone_set",
            lambda args: calls.append("set"),
        )

        class FakeArgs:
            zone_action = "set"

        cmd_zone(FakeArgs())
        assert calls == ["set"]

    def test_clear_action_dispatches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "desloppify.commands.zone_cmd._zone_clear",
            lambda args: calls.append("clear"),
        )

        class FakeArgs:
            zone_action = "clear"

        cmd_zone(FakeArgs())
        assert calls == ["clear"]

    def test_unknown_action_prints_usage(self, capsys):
        class FakeArgs:
            zone_action = "bogus"

        cmd_zone(FakeArgs())
        out = capsys.readouterr().out
        assert "Usage:" in out


# ---------------------------------------------------------------------------
# _zone_set
# ---------------------------------------------------------------------------

class TestZoneSet:
    """_zone_set validates zone values and persists overrides."""

    def test_invalid_zone_value(self, monkeypatch, capsys):
        """Setting an invalid zone value should print an error."""
        fake_config = {"zone_overrides": {}}

        class FakeArgs:
            _config = fake_config
            zone_path = "src/foo.ts"
            zone_value = "invalid_zone"
            lang = None
            path = "."

        _zone_set(FakeArgs())
        out = capsys.readouterr().out
        assert "Invalid zone" in out

    def test_valid_zone_value_saves(self, monkeypatch, capsys):
        """Setting a valid zone value should save config."""
        import desloppify.config as config_mod

        saved = []
        fake_config = {"zone_overrides": {}}
        monkeypatch.setattr(config_mod, "save_config", lambda cfg, path=None: saved.append(dict(cfg)))

        class FakeArgs:
            _config = fake_config
            zone_path = "src/foo.ts"
            zone_value = "test"
            lang = None
            path = "."

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
        import desloppify.config as config_mod

        saved = []
        fake_config = {"zone_overrides": {"src/foo.ts": "test"}}
        monkeypatch.setattr(config_mod, "save_config", lambda cfg, path=None: saved.append(dict(cfg)))

        class FakeArgs:
            _config = fake_config
            zone_path = "src/foo.ts"
            lang = None
            path = "."

        _zone_clear(FakeArgs())
        out = capsys.readouterr().out
        assert "Cleared" in out
        assert len(saved) == 1
        assert "src/foo.ts" not in fake_config["zone_overrides"]

    def test_clear_nonexistent_override(self, monkeypatch, capsys):
        fake_config = {"zone_overrides": {}}

        class FakeArgs:
            _config = fake_config
            zone_path = "src/bar.ts"
            lang = None
            path = "."

        _zone_clear(FakeArgs())
        out = capsys.readouterr().out
        assert "No override found" in out
