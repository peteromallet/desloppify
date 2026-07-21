"""Lifecycle markers, migration rules, and display-phase derivation.

Persisted markers live in ``plan["refresh_state"]`` and have distinct roles:

``lifecycle_phase``
    Valid persisted values are only ``"plan"`` and ``"execute"``. The single
    writer is ``_set_lifecycle_phase()``, called from
    ``engine._plan.sync.pipeline.reconcile_plan()`` after queue reconciliation.
    Legacy fine-grained phase names are migrated at load time by
    ``migrate_legacy_phase()`` from ``engine._plan.persistence._load_validated_plan()``.
    The coarse mode transitions from ``plan`` to ``execute`` when planning work
    drains, and from ``execute`` back to ``plan`` when
    ``invalidate_postflight_scan()`` clears the postflight scan marker or new
    review/planning work is injected.

``postflight_scan_completed_at_scan_count``
    Set by ``mark_postflight_scan_completed()`` when the current boundary scan
    completes. Cleared by ``invalidate_postflight_scan()`` when objective work
    changes require a fresh postflight scan.

``subjective_review_completed_at_scan_count``
    Set by ``mark_subjective_review_completed()`` when subjective review is done
    for the current postflight scan. Carried forward by
    ``carry_forward_subjective_review()`` only when a force-rescan replaces the
    same cycle boundary.

Display phase is never persisted. ``derive_display_phase()`` computes the
user-visible phase from boolean signals with this strict priority chain:
``promoted_execution > initial_review > prefer_scan > assessment > workflow >
triage > review_postflight > execute > scan``. Explicit promotion is a user
override of the normal planning gates. ``user_facing_mode()`` collapses all
non-``execute`` display phases back to the persisted ``"plan"`` mode.
"""

from __future__ import annotations

from collections.abc import Iterable

from desloppify.engine._plan.constants import SYNTHETIC_PREFIXES
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._state.issue_semantics import counts_toward_objective_backlog

_POSTFLIGHT_SCAN_KEY = "postflight_scan_completed_at_scan_count"
_SUBJECTIVE_REVIEW_KEY = "subjective_review_completed_at_scan_count"
_LIFECYCLE_PHASE_KEY = "lifecycle_phase"

# ── Display-only constants ──────────────────────────────────────────
# These are SHORT display names used by snapshot.py, pipeline.py, and
# consumers for phase-gated rendering.  They are NEVER persisted.
LIFECYCLE_PHASE_REVIEW_INITIAL = "review_initial"
LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT = "assessment"
LIFECYCLE_PHASE_REVIEW_POSTFLIGHT = "review"
LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT = "workflow"
LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT = "triage"
LIFECYCLE_PHASE_EXECUTE = "execute"
LIFECYCLE_PHASE_SCAN = "scan"

# Only these two values are persisted in refresh_state["lifecycle_phase"].
_VALID_PHASES = frozenset({"plan", "execute"})

# Data migration: ALL old phase names (fine-grained and coarse) map to a
# persisted mode.  This is the ONLY place legacy names are tolerated.
_LEGACY_PHASE_TO_MODE: dict[str, str] = {
    "review_initial": "plan",
    "assessment_postflight": "plan",
    "review_postflight": "plan",
    "workflow_postflight": "plan",
    "triage_postflight": "plan",
    "execute": "execute",
    "scan": "plan",
    "review": "plan",
    "workflow": "plan",
    "triage": "plan",
}


def _refresh_state(plan: PlanModel) -> dict[str, object]:
    ensure_plan_defaults(plan)
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        refresh_state = {}
        plan["refresh_state"] = refresh_state
    return refresh_state


def _is_real_queue_issue(issue_id: str) -> bool:
    return not any(str(issue_id).startswith(prefix) for prefix in SYNTHETIC_PREFIXES)


def _touches_objective_issue(
    *,
    issue_ids: Iterable[str] | None,
    state: dict[str, object] | None,
) -> bool:
    if issue_ids is None:
        return True

    real_issue_ids = [
        issue_id for issue_id in issue_ids if _is_real_queue_issue(str(issue_id))
    ]
    if not real_issue_ids:
        return False
    if not isinstance(state, dict):
        return True

    issues = state.get("work_items") or state.get("issues", {})
    if not isinstance(issues, dict):
        return True

    objective_seen = False
    for issue_id in real_issue_ids:
        issue = issues.get(issue_id)
        if not isinstance(issue, dict):
            return True
        if counts_toward_objective_backlog(issue):
            objective_seen = True
    return objective_seen


def user_facing_mode(display_phase: str) -> str:
    """Collapse internal display phases into the user-facing mode label."""
    if display_phase == LIFECYCLE_PHASE_EXECUTE:
        return "execute"
    return "plan"



def migrate_legacy_phase(plan: PlanModel) -> bool:
    """Normalize legacy persisted lifecycle values in-place once per load."""
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        return False

    phase = refresh_state.get(_LIFECYCLE_PHASE_KEY)
    if not isinstance(phase, str):
        return False
    if phase in _VALID_PHASES:
        return False

    migrated = _LEGACY_PHASE_TO_MODE.get(phase)
    if migrated is None:
        return False

    if migrated == "plan" and plan.get("plan_start_scores"):
        queue_order = plan.get("queue_order", [])
        has_plan_work = any(
            isinstance(item_id, str)
            and (item_id.startswith("workflow::") or item_id.startswith("triage::"))
            for item_id in queue_order
        )
        if not has_plan_work:
            migrated = "execute"

    refresh_state[_LIFECYCLE_PHASE_KEY] = migrated
    return True


def current_lifecycle_phase(plan: PlanModel) -> str:
    """Return the persisted lifecycle mode: ``"plan"`` or ``"execute"``.

    Pure reader. Legacy migration is handled by ``migrate_legacy_phase()`` at
    plan-load time.
    """
    refresh_state = plan.get("refresh_state")
    if isinstance(refresh_state, dict):
        phase = refresh_state.get(_LIFECYCLE_PHASE_KEY)
        if isinstance(phase, str) and phase in _VALID_PHASES:
            return phase
    if postflight_scan_pending(plan):
        return "plan"
    if plan.get("plan_start_scores"):
        return "execute"
    return "execute"


def derive_display_phase(
    *,
    has_initial_review: bool,
    has_postflight_assessment: bool,
    has_workflow: bool,
    has_triage: bool,
    has_review_postflight: bool,
    has_execution: bool,
    fresh_boundary: bool,
    prefer_scan: bool,
    has_promoted_execution: bool = False,
) -> str:
    """Return the canonical display phase from normalized boolean signals."""
    if has_execution and has_promoted_execution:
        return LIFECYCLE_PHASE_EXECUTE
    if fresh_boundary and has_initial_review:
        return LIFECYCLE_PHASE_REVIEW_INITIAL
    if prefer_scan:
        return LIFECYCLE_PHASE_SCAN
    if has_postflight_assessment:
        return LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT
    if has_workflow:
        return LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT
    if has_triage:
        return LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT
    if has_review_postflight:
        return LIFECYCLE_PHASE_REVIEW_POSTFLIGHT
    if has_execution:
        return LIFECYCLE_PHASE_EXECUTE
    return LIFECYCLE_PHASE_SCAN



def _set_lifecycle_phase(plan: PlanModel, phase: str) -> bool:
    """Persist the current queue lifecycle mode (``"plan"`` or ``"execute"``)."""
    if phase not in _VALID_PHASES:
        raise ValueError(f"Unsupported lifecycle phase: {phase}")
    refresh_state = _refresh_state(plan)
    if refresh_state.get(_LIFECYCLE_PHASE_KEY) == phase:
        return False
    refresh_state[_LIFECYCLE_PHASE_KEY] = phase
    return True


def postflight_scan_pending(plan: PlanModel) -> bool:
    """Return True when the current empty-queue boundary still needs a scan."""
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        return True
    return not isinstance(refresh_state.get(_POSTFLIGHT_SCAN_KEY), int)


def mark_postflight_scan_completed(
    plan: PlanModel,
    *,
    scan_count: int | None,
) -> bool:
    """Record that the scan stage completed for the current refresh cycle."""
    refresh_state = _refresh_state(plan)
    try:
        normalized_scan_count = int(scan_count or 0)
    except (TypeError, ValueError):
        normalized_scan_count = 0
    if refresh_state.get(_POSTFLIGHT_SCAN_KEY) == normalized_scan_count:
        return False
    refresh_state[_POSTFLIGHT_SCAN_KEY] = normalized_scan_count
    return True


def subjective_review_completed_for_scan(
    plan: PlanModel,
    *,
    scan_count: int | None,
) -> bool:
    """Return True when postflight subjective review finished for *scan_count*."""
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        return False
    try:
        normalized_scan_count = int(scan_count or 0)
    except (TypeError, ValueError):
        normalized_scan_count = 0
    return refresh_state.get(_SUBJECTIVE_REVIEW_KEY) == normalized_scan_count


def mark_subjective_review_completed(
    plan: PlanModel,
    *,
    scan_count: int | None,
) -> bool:
    """Record that subjective review completed for the current postflight scan."""
    refresh_state = _refresh_state(plan)
    try:
        normalized_scan_count = int(scan_count or 0)
    except (TypeError, ValueError):
        normalized_scan_count = 0
    if refresh_state.get(_SUBJECTIVE_REVIEW_KEY) == normalized_scan_count:
        return False
    refresh_state[_SUBJECTIVE_REVIEW_KEY] = normalized_scan_count
    return True


def carry_forward_subjective_review(
    plan: PlanModel,
    *,
    old_postflight_scan_count: int | None,
    new_scan_count: int | None,
) -> bool:
    """Promote the review marker only when it belongs to the replaced cycle."""
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        return False
    if _SUBJECTIVE_REVIEW_KEY not in refresh_state:
        return False
    try:
        normalized_old_postflight = int(old_postflight_scan_count or 0)
    except (TypeError, ValueError):
        normalized_old_postflight = 0
    marker = refresh_state.get(_SUBJECTIVE_REVIEW_KEY)
    if marker != normalized_old_postflight:
        return False
    try:
        normalized_new_scan_count = int(new_scan_count or 0)
    except (TypeError, ValueError):
        normalized_new_scan_count = 0
    if marker == normalized_new_scan_count:
        return False
    refresh_state[_SUBJECTIVE_REVIEW_KEY] = normalized_new_scan_count
    return True


def invalidate_postflight_scan(
    plan: PlanModel,
    *,
    issue_ids: Iterable[str] | None = None,
    state: dict[str, object] | None = None,
) -> bool:
    """Require a fresh scan after queue-changing work on objective issues."""
    if not _touches_objective_issue(issue_ids=issue_ids, state=state):
        return False
    refresh_state = _refresh_state(plan)
    if _POSTFLIGHT_SCAN_KEY not in refresh_state:
        return False
    refresh_state.pop(_POSTFLIGHT_SCAN_KEY, None)
    return True


__all__ = [
    "LIFECYCLE_PHASE_ASSESSMENT_POSTFLIGHT",
    "LIFECYCLE_PHASE_EXECUTE",
    "LIFECYCLE_PHASE_REVIEW_INITIAL",
    "LIFECYCLE_PHASE_REVIEW_POSTFLIGHT",
    "LIFECYCLE_PHASE_SCAN",
    "LIFECYCLE_PHASE_TRIAGE_POSTFLIGHT",
    "LIFECYCLE_PHASE_WORKFLOW_POSTFLIGHT",
    "carry_forward_subjective_review",
    "invalidate_postflight_scan",
    "current_lifecycle_phase",
    "derive_display_phase",
    "mark_postflight_scan_completed",
    "mark_subjective_review_completed",
    "migrate_legacy_phase",
    "postflight_scan_pending",
    "subjective_review_completed_for_scan",
    "user_facing_mode",
]
