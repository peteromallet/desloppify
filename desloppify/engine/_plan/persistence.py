"""Plan persistence — load/save with atomic writes."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

from desloppify.core.discovery_api import safe_write_text
from desloppify.engine._plan.schema import (
    PLAN_VERSION,
    PlanModel,
    empty_plan,
    ensure_plan_defaults,
    validate_plan,
)
from desloppify.engine._state.schema import STATE_DIR, json_default
from desloppify.engine._state.schema import utc_now

logger = logging.getLogger(__name__)

PLAN_FILE = STATE_DIR / "plan.json"


def load_plan(path: Path | None = None) -> PlanModel:
    """Load plan from disk, or return empty plan on missing/corruption."""
    plan_path = path or PLAN_FILE
    if not plan_path.exists():
        return empty_plan()

    try:
        data = json.loads(plan_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as ex:
        # Try backup before giving up
        backup = plan_path.with_suffix(".json.bak")
        if backup.exists():
            try:
                data = json.loads(backup.read_text())
                logger.warning("Plan file corrupted (%s), loaded from backup.", ex)
                print(f"  Warning: Plan file corrupted ({ex}), loaded from backup.", file=sys.stderr)
                # Fall through to validation below
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as backup_ex:
                logger.warning("Plan file and backup both corrupted: %s / %s", ex, backup_ex)
                print(f"  Warning: Plan file corrupted ({ex}). Starting fresh.", file=sys.stderr)
                return empty_plan()
        else:
            logger.warning("Plan file corrupted (%s). Starting fresh.", ex)
            print(f"  Warning: Plan file corrupted ({ex}). Starting fresh.", file=sys.stderr)
            return empty_plan()

    if not isinstance(data, dict):
        logger.warning("Plan file root is not a JSON object. Starting fresh.")
        print("  Warning: Plan file root must be a JSON object. Starting fresh.", file=sys.stderr)
        return empty_plan()

    version = data.get("version", 1)
    if version > PLAN_VERSION:
        logger.warning("Plan file version %d > supported %d.", version, PLAN_VERSION)
        print(
            f"  Warning: Plan file version {version} is newer than supported "
            f"({PLAN_VERSION}). Some features may not work correctly.",
            file=sys.stderr,
        )

    ensure_plan_defaults(data)
    try:
        validate_plan(data)
    except ValueError as ex:
        logger.warning("Plan invariants invalid (%s). Starting fresh.", ex)
        print(f"  Warning: Plan invariants invalid ({ex}). Starting fresh.", file=sys.stderr)
        return empty_plan()

    return data  # type: ignore[return-value]


def save_plan(plan: PlanModel | dict, path: Path | None = None) -> None:
    """Validate and save plan to disk atomically."""
    ensure_plan_defaults(plan)
    plan["updated"] = utc_now()
    validate_plan(plan)

    plan_path = path or PLAN_FILE
    plan_path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(plan, indent=2, default=json_default) + "\n"

    if plan_path.exists():
        backup = plan_path.with_suffix(".json.bak")
        try:
            shutil.copy2(str(plan_path), str(backup))
        except OSError as backup_ex:
            logger.debug("Failed to create plan backup: %s", backup_ex)

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
