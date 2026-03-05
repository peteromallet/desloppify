"""Plan persistence — load/save with atomic writes."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import PersistenceSafetyError
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.runtime_state import current_runtime_context
from desloppify.engine._plan.schema import (
    PLAN_VERSION,
    PlanModel,
    empty_plan,
    ensure_plan_defaults,
    validate_plan,
)
from desloppify.engine._state.schema import STATE_DIR, json_default, utc_now

logger = logging.getLogger(__name__)

PLAN_FILE = STATE_DIR / "plan.json"
_UNSAFE_MARKER_KEY = "_unsafe_load_reasons"
_QUARANTINE_KEY = "_load_quarantine"
_SAFE_ERROR_PREFIX = "DLP_PERSISTENCE_PLAN"


def _allow_unsafe_coerce(allow_unsafe_coerce: bool | None) -> bool:
    if allow_unsafe_coerce is not None:
        return bool(allow_unsafe_coerce)
    return bool(current_runtime_context().allow_unsafe_coerce)


def _quarantine_path(plan_path: Path) -> Path:
    stamp = utc_now().replace(":", "-")
    return plan_path.with_name(f"{plan_path.stem}.quarantine.{stamp}{plan_path.suffix}")


def _write_quarantine_snapshot(plan_path: Path, *, raw_text: str, reason: str) -> Path | None:
    quarantine_path = _quarantine_path(plan_path)
    payload = {
        "source_path": str(plan_path),
        "reason": reason,
        "captured_at": utc_now(),
        "raw_text": raw_text,
    }
    try:
        safe_write_text(quarantine_path, json.dumps(payload, indent=2, default=json_default) + "\n")
    except OSError as exc:
        log_best_effort_failure(logger, "write plan quarantine snapshot", exc)
        return None
    return quarantine_path


def _raise_plan_safety_error(*, code: str, detail: str, quarantine_path: Path | None = None) -> None:
    message = f"[{_SAFE_ERROR_PREFIX}_{code}] {detail}"
    if quarantine_path is not None:
        message += f" Recovery snapshot: {quarantine_path}"
    raise PersistenceSafetyError(message, exit_code=2)


def load_plan(
    path: Path | None = None,
    *,
    allow_unsafe_coerce: bool | None = None,
) -> PlanModel:
    """Load plan from disk with explicit safety checks."""
    plan_path = path or PLAN_FILE
    unsafe_allowed = _allow_unsafe_coerce(allow_unsafe_coerce)
    if not plan_path.exists():
        return empty_plan()

    raw_primary = ""
    try:
        raw_primary = plan_path.read_text()
        data = json.loads(raw_primary)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as ex:
        # Try backup before giving up
        backup = plan_path.with_suffix(".json.bak")
        if backup.exists():
            try:
                raw_backup = backup.read_text()
                data = json.loads(raw_backup)
                logger.warning("Plan file corrupted (%s), loaded from backup.", ex)
                print(f"  Warning: Plan file corrupted ({ex}), loaded from backup.", file=sys.stderr)
                # Fall through to validation below
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as backup_ex:
                logger.warning("Plan file and backup both corrupted: %s / %s", ex, backup_ex)
                quarantine_path = _write_quarantine_snapshot(
                    plan_path,
                    raw_text=raw_primary,
                    reason=f"primary parse error: {ex}; backup parse error: {backup_ex}",
                )
                _raise_plan_safety_error(
                    code="PARSE_FAILED",
                    detail="Plan file and backup are unreadable.",
                    quarantine_path=quarantine_path,
                )
        else:
            logger.warning("Plan file corrupted (%s). Starting fresh.", ex)
            quarantine_path = _write_quarantine_snapshot(
                plan_path,
                raw_text=raw_primary,
                reason=f"primary parse error: {ex}",
            )
            _raise_plan_safety_error(
                code="PARSE_FAILED",
                detail="Plan file is unreadable and no backup is available.",
                quarantine_path=quarantine_path,
            )

    if not isinstance(data, dict):
        logger.warning("Plan file root is not a JSON object. Starting fresh.")
        quarantine_path = _write_quarantine_snapshot(
            plan_path,
            raw_text=raw_primary,
            reason="plan root is not a JSON object",
        )
        _raise_plan_safety_error(
            code="ROOT_NOT_OBJECT",
            detail="Plan file root must be a JSON object.",
            quarantine_path=quarantine_path,
        )

    version = data.get("version", 1)
    if version > PLAN_VERSION:
        if not unsafe_allowed:
            _raise_plan_safety_error(
                code="FUTURE_VERSION",
                detail=(
                    f"Plan schema version {version} is newer than supported ({PLAN_VERSION}). "
                    "Re-run with --allow-unsafe-coerce only for manual recovery."
                ),
            )
        logger.warning(
            "Unsafe plan coercion enabled for future schema version %s (supported=%s).",
            version,
            PLAN_VERSION,
        )

    ensure_plan_defaults(data)
    try:
        validate_plan(data)
    except ValueError as ex:
        quarantine_path = _write_quarantine_snapshot(
            plan_path,
            raw_text=raw_primary,
            reason=f"plan invariants invalid: {ex}",
        )
        _raise_plan_safety_error(
            code="INVALID_INVARIANTS",
            detail=f"Plan invariants invalid: {ex}",
            quarantine_path=quarantine_path,
        )

    reasons: list[str] = []
    if version > PLAN_VERSION:
        reasons.append("future_schema_version")
    quarantine_payload = data.get(_QUARANTINE_KEY)
    if isinstance(quarantine_payload, dict) and quarantine_payload:
        reasons.append("normalized_malformed_sections")
    if reasons:
        data[_UNSAFE_MARKER_KEY] = reasons

    return data  # type: ignore[return-value]


def _assert_safe_to_save(
    plan: PlanModel | dict[str, object],
    *,
    allow_unsafe_coerce: bool | None,
) -> None:
    unsafe_allowed = _allow_unsafe_coerce(allow_unsafe_coerce)
    reasons = plan.get(_UNSAFE_MARKER_KEY)
    if unsafe_allowed:
        return
    if isinstance(reasons, list) and reasons:
        _raise_plan_safety_error(
            code="UNSAFE_SAVE_BLOCKED",
            detail=(
                "Plan payload contains unsafe normalization markers "
                f"({', '.join(str(item) for item in reasons)}). "
                "Use --allow-unsafe-coerce only after manual verification."
            ),
        )


def save_plan(
    plan: PlanModel | dict,
    path: Path | None = None,
    *,
    allow_unsafe_coerce: bool | None = None,
) -> None:
    """Validate and save plan to disk atomically."""
    _assert_safe_to_save(plan, allow_unsafe_coerce=allow_unsafe_coerce)
    ensure_plan_defaults(plan)
    plan["updated"] = utc_now()
    validate_plan(plan)

    plan_path = path or PLAN_FILE
    plan_path.parent.mkdir(parents=True, exist_ok=True)

    serializable_plan = dict(plan)
    serializable_plan.pop(_UNSAFE_MARKER_KEY, None)
    content = json.dumps(serializable_plan, indent=2, default=json_default) + "\n"

    if plan_path.exists():
        backup = plan_path.with_suffix(".json.bak")
        try:
            shutil.copy2(str(plan_path), str(backup))
        except OSError as backup_ex:
            log_best_effort_failure(logger, "create plan backup", backup_ex)

    try:
        safe_write_text(plan_path, content)
    except OSError as ex:
        print(f"  Warning: Could not save plan: {ex}", file=sys.stderr)
        raise


def plan_path_for_state(state_path: Path) -> Path:
    """Derive plan.json path from a state file path."""
    return state_path.parent / "plan.json"


def has_living_plan(path: Path | None = None) -> bool:
    """Return True if a plan.json exists and has user intent."""
    plan_path = path or PLAN_FILE
    if not plan_path.exists():
        return False
    plan = load_plan(plan_path)
    return bool(
        plan.get("queue_order")
        or plan.get("overrides")
        or plan.get("clusters")
    )


__all__ = [
    "PLAN_FILE",
    "has_living_plan",
    "load_plan",
    "plan_path_for_state",
    "save_plan",
]
