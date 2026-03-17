"""Plan persistence — load/save with atomic writes."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.engine._plan.schema import (
    PLAN_VERSION,
    PlanModel,
    empty_plan,
    ensure_plan_defaults,
    validate_plan,
)
from desloppify.engine._state.schema import (
    get_state_dir,
    json_default,
    utc_now,
)

logger = logging.getLogger(__name__)

_PLAN_FILE_SENTINEL = object()
PLAN_FILE = _PLAN_FILE_SENTINEL
_INITIAL_PLAN_FILE = _PLAN_FILE_SENTINEL


@dataclass(frozen=True)
class PlanLoadStatus:
    """Resolved plan load result with degraded-mode signaling."""

    plan: PlanModel | None
    degraded: bool
    error_kind: str | None = None
    recovery: str | None = None


def get_plan_file() -> Path:
    """Return the default plan file for the current runtime context."""
    return get_state_dir() / "plan.json"


def _default_plan_file() -> Path:
    """Resolve the effective default plan path.

    If tests monkeypatch ``PLAN_FILE`` in this module, use the patched value.
    """
    if PLAN_FILE != _INITIAL_PLAN_FILE:
        return Path(PLAN_FILE)
    return get_plan_file()


@contextmanager
def plan_lock(path: Path | None = None) -> Iterator[None]:
    """Acquire exclusive lock on plan file for read-modify-write safety."""
    plan_path = path or _default_plan_file()
    lock_path = plan_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        if sys.platform == "win32":
            import msvcrt
            import time

            for _attempt in range(50):  # 50 × 0.1s = 5s max
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if _attempt == 49:
                        raise TimeoutError(
                            f"Could not acquire lock on {lock_path} after 5s. "
                            "Close any editors or processes that may have it open."
                        )
                    time.sleep(0.1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass  # Lock may not have been acquired if we timed out
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _load_validated_plan(plan_path: Path) -> PlanModel:
    """Load, normalize, and validate one plan payload from disk."""
    data = json.loads(plan_path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Plan file root must be a JSON object.")

    version = data.get("version", 1)
    if version > PLAN_VERSION:
        logger.warning("Plan file version %d > supported %d.", version, PLAN_VERSION)
        print(
            f"  Warning: Plan file version {version} is newer than supported "
            f"({PLAN_VERSION}). Some features may not work correctly.",
            file=sys.stderr,
        )

    ensure_plan_defaults(data)
    validate_plan(data)
    return cast(PlanModel, data)


def resolve_plan_load_status(path: Path | None = None) -> PlanLoadStatus:
    """Load a plan with explicit degraded-mode metadata."""
    plan_path = path or _default_plan_file()
    if not plan_path.exists():
        return PlanLoadStatus(plan=None, degraded=False, error_kind=None, recovery=None)
    try:
        return PlanLoadStatus(
            plan=_load_validated_plan(plan_path),
            degraded=False,
            error_kind=None,
            recovery=None,
        )
    except PLAN_LOAD_EXCEPTIONS as exc:
        backup = plan_path.with_suffix(".json.bak")
        if backup.exists():
            try:
                plan = _load_validated_plan(backup)
                logger.warning(
                    "Plan file load degraded for %s (%s); recovered from backup %s.",
                    plan_path,
                    exc,
                    backup,
                )
                print(
                    f"  Warning: Plan file load degraded ({exc}); recovered from backup.",
                    file=sys.stderr,
                )
                return PlanLoadStatus(
                    plan=plan,
                    degraded=True,
                    error_kind=exc.__class__.__name__,
                    recovery="backup",
                )
            except PLAN_LOAD_EXCEPTIONS as backup_exc:
                logger.warning(
                    "Plan file and backup both failed for %s: %s / %s",
                    plan_path,
                    exc,
                    backup_exc,
                )

        logger.warning("Plan file load degraded for %s (%s); starting fresh.", plan_path, exc)
        print(f"  Warning: Plan file load degraded ({exc}); starting fresh.", file=sys.stderr)
        return PlanLoadStatus(
            plan=empty_plan(),
            degraded=True,
            error_kind=exc.__class__.__name__,
            recovery="fresh_start",
        )


def load_plan(path: Path | None = None) -> PlanModel:
    """Load plan from disk, or return empty plan on missing/corruption."""
    status = resolve_plan_load_status(path)
    return status.plan or empty_plan()


def save_plan(plan: PlanModel | dict, path: Path | None = None) -> None:
    """Validate and save plan to disk atomically."""
    ensure_plan_defaults(plan)
    plan["updated"] = utc_now()
    validate_plan(plan)

    plan_path = path or _default_plan_file()
    plan_path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(plan, indent=2, default=json_default) + "\n"

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
    plan_path = path or _default_plan_file()
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
    "PlanLoadStatus",
    "get_plan_file",
    "has_living_plan",
    "load_plan",
    "plan_lock",
    "plan_path_for_state",
    "resolve_plan_load_status",
    "save_plan",
]
