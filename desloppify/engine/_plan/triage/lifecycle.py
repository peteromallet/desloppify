"""Engine-owned triage lifecycle helpers.

These helpers mutate plan queue and triage metadata without depending on app
command modules so reconcile can own postflight triage kickoff.
"""

from __future__ import annotations

from typing import cast

from desloppify.engine._plan.constants import (
    TRIAGE_IDS,
    TRIAGE_STAGE_IDS,
    normalize_queue_workflow_and_triage_prefix,
)
from desloppify.engine._plan.triage.protection import clear_protected_triage_artifacts
from desloppify.engine._plan.triage.snapshot import coverage_open_ids
from desloppify.engine._state.schema import StateModel
from desloppify.engine.plan_state import EpicTriageMeta, PlanModel, SkipEntry

_ACTIVE_TRIAGE_ISSUE_IDS_KEY = "active_triage_issue_ids"
_UNDISPOSITIONED_TRIAGE_ISSUES_KEY = "undispositioned_issue_ids"
_UNDISPOSITIONED_TRIAGE_COUNT_KEY = "undispositioned_issue_count"


def ensure_queue_order(plan: PlanModel) -> list[str]:
    """Return queue order, creating the stored list when missing."""
    order = plan.get("queue_order")
    if isinstance(order, list):
        return order
    normalized: list[str] = []
    plan["queue_order"] = normalized
    return normalized


def ensure_skipped_map(plan: PlanModel) -> dict[str, SkipEntry]:
    """Return skipped metadata, creating the stored map when missing."""
    skipped = plan.get("skipped")
    if isinstance(skipped, dict):
        return cast(dict[str, SkipEntry], skipped)
    normalized: dict[str, SkipEntry] = {}
    plan["skipped"] = normalized
    return normalized


def ensure_triage_meta(plan: PlanModel) -> EpicTriageMeta:
    """Return triage metadata, creating the stored map when missing."""
    meta = plan.get("epic_triage_meta")
    if isinstance(meta, dict):
        return cast(EpicTriageMeta, meta)
    normalized: EpicTriageMeta = {}
    plan["epic_triage_meta"] = normalized
    return normalized


def has_triage_in_queue(plan: PlanModel) -> bool:
    """Return True when any triage stage IDs are currently queued."""
    order = set(ensure_queue_order(plan))
    return bool(order & TRIAGE_IDS)


def clear_triage_stage_skips(plan: PlanModel) -> None:
    """Remove skipped markers for triage stages before reinjection."""
    skipped = ensure_skipped_map(plan)
    for sid in TRIAGE_STAGE_IDS:
        skipped.pop(sid, None)


def inject_triage_stages(plan: PlanModel) -> list[str]:
    """Inject the canonical triage stage IDs at the queue front.

    Returns the stage IDs that were newly inserted.
    """
    order = ensure_queue_order(plan)
    injected = [sid for sid in TRIAGE_STAGE_IDS if sid not in order]
    clear_triage_stage_skips(plan)
    remaining = [issue_id for issue_id in order if issue_id not in TRIAGE_IDS]
    order[:] = [*remaining, *TRIAGE_STAGE_IDS]
    normalize_queue_workflow_and_triage_prefix(order)
    return injected


def ensure_active_triage_issue_ids(plan: PlanModel, state: StateModel) -> list[str]:
    """Freeze the current triage issue set for validation across stage reruns."""
    clear_protected_triage_artifacts(plan, state)
    meta = ensure_triage_meta(plan)
    active_ids = sorted(coverage_open_ids(plan, state))
    meta[_ACTIVE_TRIAGE_ISSUE_IDS_KEY] = active_ids
    meta.pop(_UNDISPOSITIONED_TRIAGE_ISSUES_KEY, None)
    meta.pop(_UNDISPOSITIONED_TRIAGE_COUNT_KEY, None)
    return active_ids


__all__ = [
    "clear_triage_stage_skips",
    "ensure_active_triage_issue_ids",
    "ensure_queue_order",
    "ensure_skipped_map",
    "ensure_triage_meta",
    "has_triage_in_queue",
    "inject_triage_stages",
]
