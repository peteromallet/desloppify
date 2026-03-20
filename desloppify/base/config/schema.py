"""Config schema/defaults and target-score normalization helpers."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from desloppify.base.text_utils import is_numeric

MIN_TARGET_STRICT_SCORE = 0
MAX_TARGET_STRICT_SCORE = 100
DEFAULT_TARGET_STRICT_SCORE: float = 85.0


@dataclass(frozen=True)
class ConfigKey:
    type: type
    default: object
    description: str


CONFIG_SCHEMA: dict[str, ConfigKey] = {
    "target_strict_score": ConfigKey(
        int, 85, "North-star strict score target used to prioritize guidance"
    ),
    "review_max_age_days": ConfigKey(
        int, 30, "Days before a file review is considered stale (0 = never)"
    ),
    "review_batch_max_files": ConfigKey(
        int,
        80,
        "Max files assigned to each holistic review batch (0 = unlimited)",
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
    "ignore": ConfigKey(list, [], "Issue patterns to suppress"),
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
    "issue_noise_budget": ConfigKey(
        int,
        10,
        "Max issues surfaced per detector in show/scan summaries (0 = unlimited)",
    ),
    "issue_noise_global_budget": ConfigKey(
        int,
        0,
        "Global cap for surfaced issues after per-detector budget (0 = unlimited)",
    ),
    "execution_log_max_entries": ConfigKey(
        int, 10000, "Max execution log entries in plan.json (0 = unlimited)"
    ),
    "needs_rescan": ConfigKey(
        bool, False, "Set when config changes may have invalidated cached scores"
    ),
    "languages": ConfigKey(
        dict, {}, "Language-specific settings {lang_name: {key: value}}"
    ),
    "commit_tracking_enabled": ConfigKey(
        bool, True, "Show commit guidance after resolve and enable PR updates"
    ),
    "commit_pr": ConfigKey(
        int, 0, "Target PR number for commit tracking (0 = not set)"
    ),
    "commit_default_branch": ConfigKey(
        str, "", "Default branch for commit tracking (empty = auto-detect)"
    ),
    "commit_message_template": ConfigKey(
        str,
        "desloppify: {status} {count} issue(s) — {summary}",
        "Template for suggested commit messages",
    ),
    "trust_plugins": ConfigKey(
        bool,
        False,
        "Allow loading user plugins from .desloppify/plugins/ (security opt-in)",
    ),
    "transition_messages": ConfigKey(
        dict,
        {},
        "Messages shown to agents at lifecycle phase transitions {phase: message}",
    ),
    "hermes_enabled": ConfigKey(
        bool,
        False,
        "Enable Hermes agent integration (model switching, autoreply, task handoff)",
    ),
    "hermes_models": ConfigKey(
        dict,
        {
            "execute": "openrouter:x-ai/grok-4.20-beta",
            "review": "openrouter:google/gemini-3.1-pro-preview",
        },
        "Phase → provider:model mapping for Hermes model switching",
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


def coerce_target_score(
    value: object, *, fallback: float = DEFAULT_TARGET_STRICT_SCORE
) -> float:
    """Normalize target score-like values to a safe [0, 100] float."""
    if is_numeric(fallback):
        fallback_value = float(fallback)
    else:
        fallback_value = DEFAULT_TARGET_STRICT_SCORE

    if is_numeric(value):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            parsed = fallback_value
        else:
            try:
                parsed = float(text)
            except ValueError:
                parsed = fallback_value
    else:
        parsed = fallback_value
    return max(0.0, min(100.0, parsed))


def target_strict_score_from_config(
    config: dict | None, *, fallback: float = DEFAULT_TARGET_STRICT_SCORE
) -> float:
    """Read and normalize target strict score from config."""
    if isinstance(config, dict):
        raw = config.get("target_strict_score", fallback)
    else:
        raw = fallback
    return coerce_target_score(raw, fallback=fallback)


__all__ = [
    "CONFIG_SCHEMA",
    "DEFAULT_TARGET_STRICT_SCORE",
    "MAX_TARGET_STRICT_SCORE",
    "MIN_TARGET_STRICT_SCORE",
    "ConfigKey",
    "_coerce_target_strict_score",
    "coerce_target_score",
    "default_config",
    "target_strict_score_from_config",
]
