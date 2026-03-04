"""State persistence and migration routines."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import cast

__all__ = [
    "load_state",
    "save_state",
]

from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import PersistenceSafetyError
from desloppify.base.runtime_state import current_runtime_context
from desloppify.base.text_utils import is_numeric
from desloppify.engine._state.schema import (
    CURRENT_VERSION,
    STATE_FILE,
    StateModel,
    empty_state,
    ensure_state_defaults,
    json_default,
    utc_now,
    validate_state_invariants,
)

logger = logging.getLogger(__name__)


from desloppify.engine._state import _recompute_stats

_UNSAFE_MARKER_KEY = "_unsafe_load_reasons"
_QUARANTINE_KEY = "_load_quarantine"
_SAFE_ERROR_PREFIX = "DLP_PERSISTENCE_STATE"


def _allow_unsafe_coerce(allow_unsafe_coerce: bool | None) -> bool:
    if allow_unsafe_coerce is not None:
        return bool(allow_unsafe_coerce)
    return bool(current_runtime_context().allow_unsafe_coerce)


def _quarantine_path(state_path: Path) -> Path:
    ts = utc_now().replace(":", "-")
    return state_path.with_name(f"{state_path.stem}.quarantine.{ts}{state_path.suffix}")


def _write_quarantine_snapshot(
    state_path: Path,
    *,
    raw_text: str,
    reason: str,
) -> Path | None:
    quarantine_path = _quarantine_path(state_path)
    payload = {
        "source_path": str(state_path),
        "reason": reason,
        "raw_text": raw_text,
    }
    try:
        safe_write_text(quarantine_path, json.dumps(payload, indent=2, default=json_default) + "\n")
    except OSError as exc:
        logger.debug("Failed writing state quarantine snapshot for %s: %s", state_path, exc)
        return None
    return quarantine_path


def _raise_state_safety_error(*, code: str, detail: str, quarantine_path: Path | None = None) -> None:
    message = f"[{_SAFE_ERROR_PREFIX}_{code}] {detail}"
    if quarantine_path is not None:
        message += f" Recovery snapshot: {quarantine_path}"
    raise PersistenceSafetyError(message, exit_code=2)


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("state file root must be a JSON object")
    return data


def _normalize_loaded_state(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("state file root must be a JSON object")
    ensure_state_defaults(data)
    normalized = cast(StateModel, data)
    validate_state_invariants(normalized)
    return normalized


def load_state(
    path: Path | None = None,
    *,
    allow_unsafe_coerce: bool | None = None,
) -> StateModel:
    """Load state from disk with explicit safety checks."""
    state_path = path or STATE_FILE
    unsafe_allowed = _allow_unsafe_coerce(allow_unsafe_coerce)
    if not state_path.exists():
        return empty_state()

    raw_primary = ""
    try:
        raw_primary = state_path.read_text()
        data = json.loads(raw_primary)
        if not isinstance(data, dict):
            raise ValueError("state file root must be a JSON object")
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as ex:
        backup = state_path.with_suffix(".json.bak")
        if backup.exists():
            logger.warning(
                "Primary state load failed for %s; attempting backup %s: %s",
                state_path,
                backup,
                ex,
            )
            try:
                backup_data = _load_json(backup)
                logger.warning(
                    "Recovered state from backup %s after primary load failure at %s",
                    backup,
                    state_path,
                )
                print(
                    f"  ⚠ State file corrupted ({ex}), loaded from backup.",
                    file=sys.stderr,
                )
                normalized_backup = _normalize_loaded_state(backup_data)
                if isinstance(normalized_backup.get(_QUARANTINE_KEY), dict) and normalized_backup.get(_QUARANTINE_KEY):
                    normalized_backup[_UNSAFE_MARKER_KEY] = ["normalized_malformed_sections"]
                return normalized_backup
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                OSError,
                ValueError,
                TypeError,
                AttributeError,
            ) as backup_ex:
                logger.warning(
                    "Backup state load failed from %s after corruption in %s: %s",
                    backup,
                    state_path,
                    backup_ex,
                )
                logger.debug("Backup state load failed from %s: %s", backup, backup_ex)

        quarantine_path = _write_quarantine_snapshot(
            state_path,
            raw_text=raw_primary,
            reason=f"primary parse error: {ex}",
        )
        _raise_state_safety_error(
            code="PARSE_FAILED",
            detail="State file is unreadable and backup recovery failed.",
            quarantine_path=quarantine_path,
        )

    version = data.get("version", 1)
    if version > CURRENT_VERSION:
        if not unsafe_allowed:
            _raise_state_safety_error(
                code="FUTURE_VERSION",
                detail=(
                    f"State schema version {version} is newer than supported ({CURRENT_VERSION}). "
                    "Re-run with --allow-unsafe-coerce only for manual recovery."
                ),
            )
        logger.warning(
            "Unsafe state coercion enabled for future schema version %s (supported=%s).",
            version,
            CURRENT_VERSION,
        )

    try:
        normalized = _normalize_loaded_state(data)
    except (ValueError, TypeError, AttributeError) as normalize_ex:
        quarantine_path = _write_quarantine_snapshot(
            state_path,
            raw_text=raw_primary,
            reason=f"state invariants invalid: {normalize_ex}",
        )
        _raise_state_safety_error(
            code="INVALID_INVARIANTS",
            detail=f"State invariants invalid: {normalize_ex}",
            quarantine_path=quarantine_path,
        )

    reasons: list[str] = []
    if version > CURRENT_VERSION:
        reasons.append("future_schema_version")
    if isinstance(normalized.get(_QUARANTINE_KEY), dict) and normalized.get(_QUARANTINE_KEY):
        reasons.append("normalized_malformed_sections")
    if reasons:
        normalized[_UNSAFE_MARKER_KEY] = reasons
    return normalized


def _coerce_integrity_target(value: object) -> float | None:
    if not is_numeric(value):
        return None
    return max(0.0, min(100.0, float(value)))


def _resolve_integrity_target(
    state: StateModel,
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
    state: StateModel,
    path: Path | None = None,
    *,
    subjective_integrity_target: float | None = None,
    allow_unsafe_coerce: bool | None = None,
) -> None:
    """Recompute stats/score and save to disk atomically."""
    unsafe_allowed = _allow_unsafe_coerce(allow_unsafe_coerce)
    unsafe_reasons = state.get(_UNSAFE_MARKER_KEY)
    if not unsafe_allowed and isinstance(unsafe_reasons, list) and unsafe_reasons:
        _raise_state_safety_error(
            code="UNSAFE_SAVE_BLOCKED",
            detail=(
                "State payload contains unsafe normalization markers "
                f"({', '.join(str(item) for item in unsafe_reasons)}). "
                "Use --allow-unsafe-coerce only after manual verification."
            ),
        )

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

    serializable_state = dict(state)
    serializable_state.pop(_UNSAFE_MARKER_KEY, None)
    content = json.dumps(serializable_state, indent=2, default=json_default) + "\n"

    if state_path.exists():
        backup = state_path.with_suffix(".json.bak")
        try:
            shutil.copy2(str(state_path), str(backup))
        except OSError as backup_ex:
            logger.debug(
                "Failed to create state backup %s: %s",
                state_path.with_suffix(".json.bak"),
                backup_ex,
            )

    try:
        safe_write_text(state_path, content)
    except OSError as ex:
        print(f"  Warning: Could not save state: {ex}", file=sys.stderr)
        raise
