"""State persistence and migration routines."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

from desloppify.engine.state_internal.schema import (
    CURRENT_VERSION,
    STATE_FILE,
    empty_state,
    ensure_state_defaults,
    json_default,
    validate_state_invariants,
)
from desloppify.engine.state_internal.scoring import _recompute_stats
from desloppify.utils import safe_write_text

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("state file root must be a JSON object")
    return data


def _normalize_loaded_state(data: dict[str, object]) -> dict[str, object]:
    normalized = ensure_state_defaults(data)
    validate_state_invariants(normalized)
    return normalized


def load_state(path: Path | None = None) -> dict[str, object]:
    """Load state from disk, or return empty state on missing/corruption."""
    state_path = path or STATE_FILE
    if not state_path.exists():
        return empty_state()

    try:
        data = _load_json(state_path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as ex:
        backup = state_path.with_suffix(".json.bak")
        if backup.exists():
            try:
                backup_data = _load_json(backup)
                print(
                    f"  ⚠ State file corrupted ({ex}), loaded from backup.",
                    file=sys.stderr,
                )
                return _normalize_loaded_state(backup_data)
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                OSError,
                ValueError,
            ) as backup_ex:
                backup_data = {}
                logger.debug("Backup state load failed from %s: %s", backup, backup_ex)

        print(f"  ⚠ State file corrupted ({ex}). Starting fresh.", file=sys.stderr)
        rename_failed = False
        try:
            state_path.rename(state_path.with_suffix(".json.corrupted"))
        except OSError as rename_ex:
            rename_failed = True
            logger.debug(
                "Failed to rename corrupted state file %s: %s", state_path, rename_ex
            )
        if rename_failed:
            logger.debug(
                "Corrupted state file retained at original path: %s", state_path
            )
        return empty_state()

    version = data.get("version", 1)
    if version > CURRENT_VERSION:
        print(
            "  ⚠ State file version "
            f"{version} is newer than supported ({CURRENT_VERSION}). "
            "Some features may not work correctly.",
            file=sys.stderr,
        )

    return _normalize_loaded_state(data)


def _coerce_integrity_target(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(0.0, min(100.0, float(value)))


def _resolve_integrity_target(
    state: dict[str, object],
    explicit_target: float | None,
) -> float | None:
    target = _coerce_integrity_target(explicit_target)
    if target is not None:
        return target

    integrity = state.get("subjective_integrity")
    if not isinstance(integrity, dict):
        return None
    return _coerce_integrity_target(integrity.get("target_score"))


def save_state(
    state: dict[str, object],
    path: Path | None = None,
    *,
    subjective_integrity_target: float | None = None,
) -> None:
    """Recompute stats/score and save to disk atomically."""
    ensure_state_defaults(state)
    _recompute_stats(
        state,
        scan_path=state.get("scan_path"),
        subjective_integrity_target=_resolve_integrity_target(
            state,
            subjective_integrity_target,
        ),
    )
    validate_state_invariants(state)

    state_path = path or STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(state, indent=2, default=json_default) + "\n"

    if state_path.exists():
        backup = state_path.with_suffix(".json.bak")
        try:
            shutil.copy2(str(state_path), str(backup))
        except OSError as backup_ex:
            backup = state_path
            logger.debug("Failed to create state backup %s: %s", backup, backup_ex)

    try:
        safe_write_text(state_path, content)
    except OSError as ex:
        print(f"  Warning: Could not save state: {ex}", file=sys.stderr)
        raise
