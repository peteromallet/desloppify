"""State persistence and migration routines."""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import shutil
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import cast


try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS

__all__ = [
    "load_state",
    "save_state",
    "state_lock",
]

from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.text_utils import is_numeric
from desloppify.engine._plan.persistence import load_plan as load_plan_state
from desloppify.engine._plan.persistence import plan_path_for_state
from desloppify.engine.plan_state import PlanLoadStatus
from desloppify.engine._state.recovery import (
    has_saved_plan_without_scan,
    reconstruct_state_from_saved_plan,
)
from desloppify.engine._state.schema import (
    CURRENT_VERSION,
    StateModel,
    empty_state,
    ensure_state_defaults,
    get_state_file,
    json_default,
    scan_source,
    validate_state_invariants,
)

logger = logging.getLogger(__name__)

_STATE_FILE_SENTINEL = object()
STATE_FILE = _STATE_FILE_SENTINEL


from desloppify.engine._state import _recompute_stats


def _default_state_file() -> Path:
    """Resolve the default state path, honoring runtime context overrides.

    If tests monkeypatch ``STATE_FILE`` in this module, use that override.
    """
    if STATE_FILE is not _STATE_FILE_SENTINEL:
        return Path(STATE_FILE)
    return get_state_file()


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


def _reconstruct_from_saved_plan_if_available(
    state_path: Path,
    state: StateModel,
) -> StateModel:
    plan_status = _saved_plan_load_status(state_path)
    if plan_status.degraded:
        logger.warning(
            "Saved plan load degraded during state recovery for %s: %s",
            state_path,
            plan_status.error_kind,
        )
        if scan_source(state) == "plan_reconstruction":
            return cast(StateModel, _normalize_loaded_state(empty_state()))
        return state
    plan = plan_status.plan
    if plan is None:
        if scan_source(state) == "plan_reconstruction":
            return cast(StateModel, _normalize_loaded_state(empty_state()))
        return state
    if has_saved_plan_without_scan(state, plan):
        reconstructed = reconstruct_state_from_saved_plan(empty_state(), plan)
        return cast(StateModel, _normalize_loaded_state(reconstructed))
    if scan_source(state) == "plan_reconstruction":
        return cast(StateModel, _normalize_loaded_state(empty_state()))
    return state


def _saved_plan_load_status(state_path: Path) -> PlanLoadStatus:
    plan_path = plan_path_for_state(state_path)
    if not plan_path.exists():
        return PlanLoadStatus(plan=None, degraded=False, error_kind=None)
    try:
        return PlanLoadStatus(
            plan=load_plan_state(plan_path),
            degraded=False,
            error_kind=None,
        )
    except PLAN_LOAD_EXCEPTIONS as exc:
        return PlanLoadStatus(
            plan=None,
            degraded=True,
            error_kind=exc.__class__.__name__,
        )


def load_state(path: Path | None = None) -> StateModel:
    """Load state from disk, or return empty state on missing/corruption."""
    state_path = path or _default_state_file()
    if not state_path.exists():
        return _reconstruct_from_saved_plan_if_available(state_path, empty_state())

    try:
        data = _load_json(state_path)
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
                return _reconstruct_from_saved_plan_if_available(
                    state_path,
                    normalized_backup,
                )
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

        logger.warning(
            "State file load failed for %s and backup recovery was unavailable. "
            "Falling back to empty state: %s",
            state_path,
            ex,
        )
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
        return _reconstruct_from_saved_plan_if_available(state_path, empty_state())

    version = data.get("version", 1)
    if version > CURRENT_VERSION:
        print(
            "  ⚠ State file version "
            f"{version} is newer than supported ({CURRENT_VERSION}). "
            "Some features may not work correctly.",
            file=sys.stderr,
        )

    try:
        normalized = _normalize_loaded_state(data)
        return _reconstruct_from_saved_plan_if_available(state_path, normalized)
    except (ValueError, TypeError, AttributeError) as normalize_ex:
        logger.warning(
            "State invariants invalid for %s; falling back to empty state: %s",
            state_path,
            normalize_ex,
        )
        print(
            f"  ⚠ State invariants invalid ({normalize_ex}). Starting fresh.",
            file=sys.stderr,
        )
        return _reconstruct_from_saved_plan_if_available(state_path, empty_state())


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

    state_path = path or _default_state_file()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(state, indent=2, default=json_default) + "\n"

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


@contextlib.contextmanager
def state_lock(
    path: Path | None = None,
    *,
    timeout: float = 30.0,
    subjective_integrity_target: float | None = None,
) -> Generator[StateModel, None, None]:
    """Context manager that locks the state file for exclusive read-modify-write.

    Acquires an exclusive file lock, reloads state from disk (to pick up the
    latest version), yields it for mutation, then saves on clean exit.

    Usage::

        with state_lock(state_file) as state:
            state["issues"]["foo"] = "fixed"
        # state is saved automatically on clean exit
    """
    state_path = path or _default_state_file()
    lock_path = state_path.with_suffix(".json.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(lock_fd, msvcrt.LK_LOCK, 1)
                elif fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(lock_fd)
                    raise
                if time.monotonic() >= deadline:
                    os.close(lock_fd)
                    raise TimeoutError(
                        f"Could not acquire state lock within {timeout}s. "
                        "Another desloppify command may be running."
                    ) from None
                time.sleep(0.1)

        # Reload state inside the lock to get the latest version.
        state = load_state(state_path)
        yield state
        save_state(
            state,
            state_path,
            subjective_integrity_target=subjective_integrity_target,
        )
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)
