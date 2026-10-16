"""Unified subjective-visibility policy.

A single frozen dataclass computed once per operation replaces the scattered
``has_objective_items`` / ``objective_count`` computations in
``stale_dimensions`` and ``auto_cluster``.
"""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.base.config import DEFAULT_TARGET_STRICT_SCORE
from desloppify.base.enums import Status
from desloppify.base.registry import DETECTORS
from desloppify.engine._plan.schema import (
    executable_objective_ids as _executable_objective_ids,
)
from desloppify.engine._plan.schema import live_planned_queue_ids
from desloppify.engine._state.filtering import issue_in_scan_scope
from desloppify.engine._state.issue_semantics import counts_toward_objective_backlog
from desloppify.engine._state.schema import StateModel
from desloppify.engine.planning.helpers import CONFIDENCE_ORDER

# Legacy export for modules that still need detector-name display behavior.
# Objective/non-objective semantics should flow through issue_kind helpers.
NON_OBJECTIVE_DETECTORS: frozenset[str] = frozenset({
    "review", "concerns", "subjective_review", "subjective_assessment",
})


@dataclass(frozen=True)
class SubjectiveVisibility:
    """Immutable snapshot of the subjective-vs-objective balance."""

    has_objective_backlog: bool  # any planned open non-subjective issues?
    objective_count: int  # how many (planned only, post-triage)
    unscored_ids: frozenset[str]  # subjective::* IDs needing initial review
    stale_ids: frozenset[str]  # subjective::* IDs needing re-review
    under_target_ids: frozenset[str]  # below target, not stale/unscored

    def should_inject_to_plan(self, fid: str) -> bool:
        """Should this subjective ID be injected into plan queue_order?"""
        if fid in self.unscored_ids:
            return True  # unconditional
        if fid in self.stale_ids:
            return not self.has_objective_backlog
        if fid in self.under_target_ids:
            return not self.has_objective_backlog
        return False

    def should_evict_from_plan(self, fid: str) -> bool:
        """Should this subjective ID be removed from plan queue_order?"""
        if fid in self.unscored_ids:
            return False  # never evict unscored
        if fid in self.stale_ids or fid in self.under_target_ids:
            return self.has_objective_backlog
        return False

    @property
    def backlog_blocks_rerun(self) -> bool:
        """Preflight: should reruns be blocked?"""
        return self.has_objective_backlog


def _is_evidence_only(issue: dict) -> bool:
    """Return True if the issue is below its detector's standalone threshold."""
    detector = issue.get("detector", "")
    meta = DETECTORS.get(detector)
    if meta and meta.standalone_threshold:
        threshold_rank = CONFIDENCE_ORDER.get(meta.standalone_threshold, 9)
        issue_rank = CONFIDENCE_ORDER.get(issue.get("confidence", "low"), 9)
        if issue_rank > threshold_rank:
            return True
    return False


class _ScanPathFromStatePolicy:
    """Sentinel type: resolve scan_path from state."""


_SCAN_PATH_FROM_STATE_POLICY = _ScanPathFromStatePolicy()
ScanPathPolicyOption = str | None | _ScanPathFromStatePolicy


def compute_subjective_visibility(
    state: StateModel,
    *,
    target_strict: float = DEFAULT_TARGET_STRICT_SCORE,
    scan_path: ScanPathPolicyOption = _SCAN_PATH_FROM_STATE_POLICY,
    plan: dict | None = None,
) -> SubjectiveVisibility:
    """Build the policy snapshot from current state.

    *scan_path* defaults to ``state["scan_path"]`` so callers don't need to
    thread it manually.  Pass an explicit ``str`` to override, or ``None``
    to disable scope filtering.  When *plan* is set, issues whose IDs
    appear in ``plan["skipped"]`` are excluded.

    Imports policy helpers from ``stale_policy`` so this module remains
    side-effect free and cycle-safe.
    """
    from desloppify.engine._plan.policy.stale import (
        current_stale_ids,
        current_under_target_ids,
        current_unscored_ids,
    )

    resolved_scan_path: str | None = (
        state.get("scan_path")
        if isinstance(scan_path, _ScanPathFromStatePolicy)
        else scan_path
    )

    issues = (state.get("work_items") or state.get("issues", {}))
    skipped_ids = set((plan or {}).get("skipped", {}).keys())
    forced_ids = live_planned_queue_ids(plan)

    # Count open, non-suppressed, objective issues.
    # Evidence-only issues (below standalone confidence threshold) are
    # excluded unless explicitly queued, matching queue ranking. They still
    # affect scores when they are not actionable queue items.
    # Issues outside scan_path and plan-skipped issues are also excluded
    # so the policy matches what the user actually sees in the queue.
    objective_issue_ids = [
        issue_id
        for issue_id, issue in issues.items()
        if issue.get("status") == Status.OPEN
        and counts_toward_objective_backlog(issue)
        and not issue.get("suppressed")
        and (issue_id in forced_ids or not _is_evidence_only(issue))
        and issue_in_scan_scope(str(issue.get("file", "")), resolved_scan_path)
        and issue_id not in skipped_ids
    ]

    # Only explicitly queued objectives count — backlog items don't block
    # subjective reruns.
    objective_count = len(_executable_objective_ids(set(objective_issue_ids), plan))

    unscored = current_unscored_ids(state)
    stale = current_stale_ids(state)
    under_target = current_under_target_ids(state, target_strict=target_strict)

    return SubjectiveVisibility(
        has_objective_backlog=objective_count > 0,
        objective_count=objective_count,
        unscored_ids=frozenset(unscored),
        stale_ids=frozenset(stale),
        under_target_ids=frozenset(under_target),
    )


__all__ = [
    "NON_OBJECTIVE_DETECTORS",
    "SubjectiveVisibility",
    "compute_subjective_visibility",
]
