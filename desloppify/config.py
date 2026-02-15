"""Project-wide configuration management (.desloppify/config.json).

Config is project-wide (not per-language). Keys cover exclusions, zone overrides,
review staleness thresholds, and scorecard generation settings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .utils import PROJECT_ROOT, safe_write_text

CONFIG_FILE = PROJECT_ROOT / ".desloppify" / "config.json"


@dataclass(frozen=True)
class ConfigKey:
    type: type
    default: object
    description: str


CONFIG_SCHEMA: dict[str, ConfigKey] = {
    "review_max_age_days": ConfigKey(int, 30,
        "Days before a file review is considered stale (0 = never)"),
    "holistic_max_age_days": ConfigKey(int, 30,
        "Days before a holistic review is considered stale (0 = never)"),
    "generate_scorecard": ConfigKey(bool, True,
        "Generate scorecard.png after each scan"),
    "badge_path": ConfigKey(str, "scorecard.png",
        "Output path for scorecard image"),
    "exclude": ConfigKey(list, [],
        "Path patterns to exclude from scanning"),
    "ignore": ConfigKey(list, [],
        "Finding patterns to suppress"),
    "zone_overrides": ConfigKey(dict, {},
        "Manual zone overrides {rel_path: zone_name}"),
    "review_dimensions": ConfigKey(list, [],
        "Override default per-file review dimensions (empty = built-in defaults)"),
    "large_files_threshold": ConfigKey(int, 0,
        "Override LOC threshold for large file detection (0 = use language default)"),
    "props_threshold": ConfigKey(int, 0,
        "Override prop count threshold for bloated interface detection (0 = default 14)"),
}


def default_config() -> dict:
    """Return a config dict with all keys set to their defaults."""
    return {k: v.default for k, v in CONFIG_SCHEMA.items()}


def load_config(path: Path | None = None) -> dict:
    """Load config from disk, auto-migrating from state files if needed.

    Fills missing keys with defaults. If no config.json exists, attempts
    migration from state-*.json files.
    """
    p = path or CONFIG_FILE
    if p.exists():
        try:
            config = json.loads(p.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            config = {}
    else:
        # First run — try migrating from state files
        config = _migrate_from_state_files(p)

    # Fill missing keys with defaults
    for key, schema in CONFIG_SCHEMA.items():
        if key not in config:
            config[key] = schema.default

    return config


def save_config(config: dict, path: Path | None = None) -> None:
    """Save config to disk atomically."""
    p = path or CONFIG_FILE
    safe_write_text(p, json.dumps(config, indent=2) + "\n")


def add_ignore_pattern(config: dict, pattern: str) -> None:
    """Append a pattern to the ignore list (deduplicates)."""
    ignores = config.setdefault("ignore", [])
    if pattern not in ignores:
        ignores.append(pattern)


def set_config_value(config: dict, key: str, raw: str) -> None:
    """Parse and set a config value from a raw string.

    Handles special cases:
    - "never" → 0 for age keys
    - "true"/"false" for bools
    """
    if key not in CONFIG_SCHEMA:
        raise KeyError(f"Unknown config key: {key}")

    schema = CONFIG_SCHEMA[key]

    if schema.type is int:
        if raw.lower() == "never":
            config[key] = 0
        else:
            config[key] = int(raw)
    elif schema.type is bool:
        if raw.lower() in ("true", "1", "yes"):
            config[key] = True
        elif raw.lower() in ("false", "0", "no"):
            config[key] = False
        else:
            raise ValueError(f"Expected true/false for {key}, got: {raw}")
    elif schema.type is str:
        config[key] = raw
    elif schema.type is list:
        # For list keys, append the value
        config.setdefault(key, [])
        if raw not in config[key]:
            config[key].append(raw)
    elif schema.type is dict:
        raise ValueError(f"Cannot set dict key '{key}' via CLI — use subcommands")
    else:
        config[key] = raw


def unset_config_value(config: dict, key: str) -> None:
    """Reset a config key to its default value."""
    if key not in CONFIG_SCHEMA:
        raise KeyError(f"Unknown config key: {key}")
    config[key] = CONFIG_SCHEMA[key].default


def config_for_query(config: dict) -> dict:
    """Return a sanitized config dict suitable for query.json."""
    return {k: config.get(k, schema.default)
            for k, schema in CONFIG_SCHEMA.items()}


def _migrate_from_state_files(config_path: Path) -> dict:
    """Migrate config keys from state-*.json files into config.json.

    Reads state["config"] from all state files, merges them (union for
    lists, merge for dicts), writes config.json, and strips "config" from
    the state files.
    """
    config: dict = {}
    state_dir = config_path.parent
    if not state_dir.exists():
        return config

    state_files = list(state_dir.glob("state-*.json")) + list(state_dir.glob("state.json"))
    migrated_any = False

    for sf in state_files:
        try:
            state_data = json.loads(sf.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue

        old_config = state_data.get("config")
        if not old_config or not isinstance(old_config, dict):
            continue

        # Merge: union for lists, merge for dicts, first-wins for scalars
        for k, v in old_config.items():
            if k not in CONFIG_SCHEMA:
                continue
            if k not in config:
                config[k] = v
            elif isinstance(v, list) and isinstance(config[k], list):
                for item in v:
                    if item not in config[k]:
                        config[k].append(item)
            elif isinstance(v, dict) and isinstance(config[k], dict):
                for dk, dv in v.items():
                    if dk not in config[k]:
                        config[k][dk] = dv

        # Strip "config" from state file
        if "config" in state_data:
            del state_data["config"]
            try:
                safe_write_text(sf, json.dumps(state_data, indent=2) + "\n")
            except OSError:
                pass

        migrated_any = True

    if migrated_any and config:
        try:
            save_config(config, config_path)
        except OSError:
            pass

    return config
