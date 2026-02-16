"""Tests for desloppify.config — project-wide configuration management."""

import json
import pytest

from desloppify.config import (
    CONFIG_SCHEMA,
    default_config,
    load_config,
    save_config,
    add_ignore_pattern,
    set_config_value,
    unset_config_value,
    config_for_query,
    _migrate_from_state_files,
)


# ===========================================================================
# default_config
# ===========================================================================

class TestDefaultConfig:
    def test_returns_all_keys(self):
        cfg = default_config()
        for key in CONFIG_SCHEMA:
            assert key in cfg

    def test_default_values(self):
        cfg = default_config()
        assert cfg["review_max_age_days"] == 30
        assert cfg["holistic_max_age_days"] == 30
        assert cfg["generate_scorecard"] is True
        assert cfg["badge_path"] == "scorecard.png"
        assert cfg["finding_noise_budget"] == 10
        assert cfg["finding_noise_global_budget"] == 0
        assert cfg["languages"] == {}
        assert cfg["exclude"] == []
        assert cfg["ignore"] == []
        assert cfg["zone_overrides"] == {}


# ===========================================================================
# load_config / save_config round-trip
# ===========================================================================

class TestLoadSaveConfig:
    def test_no_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "config.json")
        assert cfg == default_config()

    def test_round_trip(self, tmp_path):
        p = tmp_path / "config.json"
        cfg = default_config()
        cfg["review_max_age_days"] = 7
        cfg["ignore"] = ["smells::*::debug"]
        save_config(cfg, p)
        loaded = load_config(p)
        assert loaded["review_max_age_days"] == 7
        assert loaded["ignore"] == ["smells::*::debug"]

    def test_fills_missing_keys(self, tmp_path):
        p = tmp_path / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"review_max_age_days": 14}))
        cfg = load_config(p)
        assert cfg["review_max_age_days"] == 14
        # Missing keys get defaults
        assert cfg["holistic_max_age_days"] == 30
        assert cfg["generate_scorecard"] is True

    def test_corrupted_file_returns_defaults(self, tmp_path):
        p = tmp_path / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not valid json{{{")
        cfg = load_config(p)
        assert cfg == default_config()

    def test_legacy_csharp_keys_migrate_to_languages_namespace(self, tmp_path):
        p = tmp_path / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "csharp_corroboration_min_signals": 3,
                    "csharp_high_fanout_threshold": 8,
                }
            )
        )
        cfg = load_config(p)
        assert "csharp_corroboration_min_signals" not in cfg
        assert "csharp_high_fanout_threshold" not in cfg
        csharp_cfg = cfg["languages"].get("csharp", {})
        assert csharp_cfg.get("corroboration_min_signals") == 3
        assert csharp_cfg.get("high_fanout_threshold") == 8


# ===========================================================================
# set_config_value
# ===========================================================================

class TestSetConfigValue:
    def test_set_int(self):
        cfg = default_config()
        set_config_value(cfg, "review_max_age_days", "14")
        assert cfg["review_max_age_days"] == 14

    def test_set_noise_budget_int(self):
        cfg = default_config()
        set_config_value(cfg, "finding_noise_budget", "25")
        assert cfg["finding_noise_budget"] == 25

    def test_set_noise_global_budget_int(self):
        cfg = default_config()
        set_config_value(cfg, "finding_noise_global_budget", "50")
        assert cfg["finding_noise_global_budget"] == 50

    def test_set_never(self):
        cfg = default_config()
        set_config_value(cfg, "review_max_age_days", "never")
        assert cfg["review_max_age_days"] == 0

    def test_set_bool_true(self):
        cfg = default_config()
        set_config_value(cfg, "generate_scorecard", "false")
        assert cfg["generate_scorecard"] is False

    def test_set_bool_yes(self):
        cfg = default_config()
        cfg["generate_scorecard"] = False
        set_config_value(cfg, "generate_scorecard", "yes")
        assert cfg["generate_scorecard"] is True

    def test_set_string(self):
        cfg = default_config()
        set_config_value(cfg, "badge_path", "badges/health.png")
        assert cfg["badge_path"] == "badges/health.png"

    def test_set_list_appends(self):
        cfg = default_config()
        set_config_value(cfg, "exclude", "node_modules")
        assert "node_modules" in cfg["exclude"]

    def test_set_list_deduplicates(self):
        cfg = default_config()
        cfg["exclude"] = ["node_modules"]
        set_config_value(cfg, "exclude", "node_modules")
        assert cfg["exclude"].count("node_modules") == 1

    def test_unknown_key_raises(self):
        cfg = default_config()
        with pytest.raises(KeyError, match="Unknown config key"):
            set_config_value(cfg, "nonexistent", "value")

    def test_invalid_bool_raises(self):
        cfg = default_config()
        with pytest.raises(ValueError, match="Expected true/false"):
            set_config_value(cfg, "generate_scorecard", "maybe")

    def test_dict_key_raises(self):
        cfg = default_config()
        with pytest.raises(ValueError, match="Cannot set dict"):
            set_config_value(cfg, "zone_overrides", "value")


# ===========================================================================
# unset_config_value
# ===========================================================================

class TestUnsetConfigValue:
    def test_resets_to_default(self):
        cfg = default_config()
        cfg["review_max_age_days"] = 0
        unset_config_value(cfg, "review_max_age_days")
        assert cfg["review_max_age_days"] == 30

    def test_unknown_key_raises(self):
        cfg = default_config()
        with pytest.raises(KeyError, match="Unknown config key"):
            unset_config_value(cfg, "nonexistent")


# ===========================================================================
# add_ignore_pattern
# ===========================================================================

class TestAddIgnorePattern:
    def test_adds_pattern(self):
        cfg = default_config()
        add_ignore_pattern(cfg, "smells::*::debug")
        assert "smells::*::debug" in cfg["ignore"]

    def test_deduplicates(self):
        cfg = default_config()
        add_ignore_pattern(cfg, "smells::*::debug")
        add_ignore_pattern(cfg, "smells::*::debug")
        assert cfg["ignore"].count("smells::*::debug") == 1


# ===========================================================================
# config_for_query
# ===========================================================================

class TestConfigForQuery:
    def test_returns_all_keys(self):
        cfg = default_config()
        q = config_for_query(cfg)
        for key in CONFIG_SCHEMA:
            assert key in q

    def test_reflects_values(self):
        cfg = default_config()
        cfg["review_max_age_days"] = 0
        q = config_for_query(cfg)
        assert q["review_max_age_days"] == 0


# ===========================================================================
# _migrate_from_state_files
# ===========================================================================

class TestMigrateFromStateFiles:
    def test_migrates_ignore(self, tmp_path):
        state_dir = tmp_path
        state_dir.mkdir(exist_ok=True)
        state_data = {
            "version": 1,
            "config": {"ignore": ["smells::*::debug"], "exclude": ["dist"]},
            "findings": {},
        }
        state_file = state_dir / "state-python.json"
        state_file.write_text(json.dumps(state_data))
        config_path = state_dir / "config.json"

        result = _migrate_from_state_files(config_path)
        assert "smells::*::debug" in result.get("ignore", [])
        assert "dist" in result.get("exclude", [])

        # State file should have config key removed
        updated_state = json.loads(state_file.read_text())
        assert "config" not in updated_state

        # Config file should be written
        assert config_path.exists()

    def test_merges_multiple_state_files(self, tmp_path):
        state_dir = tmp_path
        state_dir.mkdir(exist_ok=True)

        s1 = {"version": 1, "config": {"ignore": ["pat1"], "exclude": ["ex1"]}, "findings": {}}
        s2 = {"version": 1, "config": {"ignore": ["pat2"], "exclude": ["ex1", "ex2"]}, "findings": {}}
        (state_dir / "state-python.json").write_text(json.dumps(s1))
        (state_dir / "state-typescript.json").write_text(json.dumps(s2))
        config_path = state_dir / "config.json"

        result = _migrate_from_state_files(config_path)
        assert "pat1" in result.get("ignore", [])
        assert "pat2" in result.get("ignore", [])
        assert "ex1" in result.get("exclude", [])
        assert "ex2" in result.get("exclude", [])

    def test_no_state_files_returns_empty(self, tmp_path):
        config_path = tmp_path / "config.json"
        result = _migrate_from_state_files(config_path)
        assert result == {}

    def test_state_without_config_key(self, tmp_path):
        state_dir = tmp_path
        state_dir.mkdir(exist_ok=True)
        state_data = {"version": 1, "findings": {}}
        (state_dir / "state-python.json").write_text(json.dumps(state_data))
        config_path = state_dir / "config.json"

        result = _migrate_from_state_files(config_path)
        assert result == {}

    def test_zone_overrides_merged(self, tmp_path):
        state_dir = tmp_path
        state_dir.mkdir(exist_ok=True)
        s1 = {"version": 1, "config": {"zone_overrides": {"a.py": "test"}}, "findings": {}}
        s2 = {"version": 1, "config": {"zone_overrides": {"b.ts": "vendor"}}, "findings": {}}
        (state_dir / "state-python.json").write_text(json.dumps(s1))
        (state_dir / "state-typescript.json").write_text(json.dumps(s2))
        config_path = state_dir / "config.json"

        result = _migrate_from_state_files(config_path)
        overrides = result.get("zone_overrides", {})
        assert overrides.get("a.py") == "test"
        assert overrides.get("b.ts") == "vendor"

    def test_legacy_language_keys_migrated_from_state(self, tmp_path):
        state_dir = tmp_path
        state_dir.mkdir(exist_ok=True)
        s1 = {
            "version": 1,
            "config": {"csharp_corroboration_min_signals": 4},
            "findings": {},
        }
        s2 = {
            "version": 1,
            "config": {"csharp_high_fanout_threshold": 9},
            "findings": {},
        }
        (state_dir / "state-csharp.json").write_text(json.dumps(s1))
        (state_dir / "state-csharp-alt.json").write_text(json.dumps(s2))
        config_path = state_dir / "config.json"

        result = _migrate_from_state_files(config_path)
        csharp_cfg = result.get("languages", {}).get("csharp", {})
        assert csharp_cfg.get("corroboration_min_signals") == 4
        assert csharp_cfg.get("high_fanout_threshold") == 9
