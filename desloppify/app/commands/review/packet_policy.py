"""Shared review packet policy helpers.

Both ``prepare.py`` and ``batch.py`` need the same config-redaction and
batch-file-limit coercion.  Extracting them here prevents drift.
"""

from __future__ import annotations

DEFAULT_REVIEW_BATCH_MAX_FILES = 80


def redacted_review_config(config: dict | None) -> dict:
    """Return review packet config with target score removed for blind assessment."""
    if not isinstance(config, dict):
        return {}
    return {key: value for key, value in config.items() if key != "target_strict_score"}


def coerce_review_batch_file_limit(config: dict | None) -> int | None:
    """Resolve per-batch review file cap from config (0/negative => unlimited)."""
    raw = (config or {}).get("review_batch_max_files", DEFAULT_REVIEW_BATCH_MAX_FILES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_REVIEW_BATCH_MAX_FILES
    return value if value > 0 else None
