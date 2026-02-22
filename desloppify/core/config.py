"""Project-wide + language-specific config (.desloppify/config.json)."""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.utils import safe_write_text

CONFIG_FILE = PROJECT_ROOT / ".desloppify" / "config.json"
logger = logging.getLogger(__name__)
MIN_TARGET_STRICT_SCORE = 0
MAX_TARGET_STRICT_SCORE = 100


@dataclass(frozen=True)
class ConfigKey:
    type: type
    default: object
    description: str


CONFIG_SCHEMA: dict[str, ConfigKey] = {
    "target_strict_score": ConfigKey(
        int, 95, "North-star strict score target used to prioritize guidance"
    ),
    "review_max_age_days": ConfigKey(
        int, 30, "Days before a file review is considered stale (0 = never)"
    ),
    "holistic_max_age_days": ConfigKey(
        int, 30, "Days before a holistic review is considered stale (0 = never)"
    ),
    "generate_scorecard": ConfigKey(
        bool, True, "Generate scorecard image after each scan"
    ),
    "badge_path": ConfigKey(
        str, "scorecard.png", "Output path for scorecard image"
    ),
    "exclude": ConfigKey(list, [], "Path patterns to exclude from scanning"),
    "ignore": ConfigKey(list, [], "Finding patterns to suppress"),
    "ignore_metadata": ConfigKey(dict, {}, "Ignore metadata {pattern: {note, added_at}}"),
    "zone_overrides": ConfigKey(
        dict, {}, "Manual zone overrides {rel_path: zone_name}"
    ),
    "review_dimensions": ConfigKey(
        list,
        [],
        "Override default per-file review dimensions (empty = built-in defaults)",
    ),
    "large_files_threshold": ConfigKey(
        int,
        0,
        "Override LOC threshold for large file detection (0 = use language default)",
    ),
    "props_threshold": ConfigKey(
        int,
        0,
        "Override prop count threshold for bloated interface detection (0 = default 14)",
    ),
    "finding_noise_budget": ConfigKey(
        int,
        10,
        "Max findings surfaced per detector in show/scan summaries (0 = unlimited)",
    ),
    "finding_noise_global_budget": ConfigKey(
        int,
        0,
        "Global cap for surfaced findings after per-detector budget (0 = unlimited)",
    ),
    "languages": ConfigKey(
        dict, {}, "Language-specific settings {lang_name: {key: value}}"
    ),
}


def default_config() -> dict[str, Any]:
    """Return a config dict with all keys set to their defaults."""
    return {k: copy.deepcopy(v.default) for k, v in CONFIG_SCHEMA.items()}


def _coerce_target_strict_score(value: object) -> tuple[int, bool]:
    """Coerce target strict score and report whether it is in range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return MIN_TARGET_STRICT_SCORE, False
    valid = MIN_TARGET_STRICT_SCORE <= parsed <= MAX_TARGET_STRICT_SCORE
    return parsed, valid


def load_config(path: Path | None = None) -> dict[str, Any]:
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

    changed = False

    # Fill missing keys with defaults
    for key, schema in CONFIG_SCHEMA.items():
        if key not in config:
            config[key] = copy.deepcopy(schema.default)
            changed = True
        elif key == "badge_path":
            try:
                normalized = _validate_badge_path(str(config[key]))
                if normalized != config[key]:
                    config[key] = normalized
                    changed = True
            except ValueError:
                config[key] = copy.deepcopy(schema.default)
                changed = True

    if changed and p.exists():
        try:
            save_config(config, p)
        except OSError as exc:
            log_best_effort_failure(logger, f"persist migrated config to {p}", exc)

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


def set_ignore_metadata(config: dict, pattern: str, *, note: str, added_at: str) -> None:
    """Record note + timestamp for an ignore pattern."""
    meta = config.setdefault("ignore_metadata", {})
    if not isinstance(meta, dict):
        meta = {}
        config["ignore_metadata"] = meta
    meta[pattern] = {"note": note, "added_at": added_at}


def _validate_badge_path(raw: str) -> str:
    """Require badge_path to point to a filename (root or nested path)."""
    value = raw.strip()
    path = Path(value)
    if (
        not value
        or value.endswith(("/", "\\"))
        or path.name in {"", ".", ".."}
    ):
        raise ValueError(
            "Expected file path for badge_path "
            f"(example: scorecard.png or assets/scorecard.png), got: {raw}"
        )
    return value


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
        if key == "target_strict_score":
            target_strict_score, target_valid = _coerce_target_strict_score(config[key])
            if not target_valid:
                raise ValueError(
                    f"Expected integer {MIN_TARGET_STRICT_SCORE}-{MAX_TARGET_STRICT_SCORE} "
                    f"for {key}, got: {raw}"
                )
            config[key] = target_strict_score
    elif schema.type is bool:
        if raw.lower() in ("true", "1", "yes"):
            config[key] = True
        elif raw.lower() in ("false", "0", "no"):
            config[key] = False
        else:
            raise ValueError(f"Expected true/false for {key}, got: {raw}")
    elif schema.type is str:
        if key == "badge_path":
            config[key] = _validate_badge_path(raw)
        else:
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
    config[key] = copy.deepcopy(CONFIG_SCHEMA[key].default)


def config_for_query(config: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized config dict suitable for query.json."""
    return {k: config.get(k, schema.default) for k, schema in CONFIG_SCHEMA.items()}


def _merge_config_value(config: dict, key: str, value: object) -> None:
    """Merge a config value into the target dict."""
    if key not in config:
        config[key] = copy.deepcopy(value)
        return
    if isinstance(value, list) and isinstance(config[key], list):
        for item in value:
            if item not in config[key]:
                config[key].append(item)
        return
    if isinstance(value, dict) and isinstance(config[key], dict):
        for dk, dv in value.items():
            if dk not in config[key]:
                config[key][dk] = copy.deepcopy(dv)
        return

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

    state_files = list(state_dir.glob("state-*.json")) + list(
        state_dir.glob("state.json")
    )
    migrated_any = False
    for sf in state_files:
        try:
            state_data = json.loads(sf.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            logger.debug("Skipping unreadable state file %s: %s", sf, exc)
            continue

        old_config = state_data.get("config")
        if not old_config or not isinstance(old_config, dict):
            continue

        # Merge: union for lists, merge for dicts, first-wins for scalars
        for k, v in old_config.items():
            if k not in CONFIG_SCHEMA:
                continue
            _merge_config_value(config, k, v)

        # Strip "config" from state file
        if "config" in state_data:
            del state_data["config"]
            try:
                safe_write_text(sf, json.dumps(state_data, indent=2) + "\n")
            except OSError as exc:
                log_best_effort_failure(
                    logger,
                    f"rewrite state file {sf} after config migration",
                    exc,
                )

        migrated_any = True

    if migrated_any and config:
        try:
            save_config(config, config_path)
        except OSError as exc:
            log_best_effort_failure(
                logger, f"save migrated config to {config_path}", exc
            )

    return config
