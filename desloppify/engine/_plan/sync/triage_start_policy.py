"""Shared triage-start policy used by sync and command entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from desloppify.engine._plan.constants import (
    TRIAGE_IDS,
    recorded_unconfirmed_triage_stage_names,
)
from desloppify.engine._plan.policy.stale import open_review_ids
from desloppify.engine._plan.policy.subjective import (
    SubjectiveVisibility,
    _is_evidence_only,
    compute_subjective_visibility,
)
from desloppify.engine._plan.schema import PlanModel, executable_objective_ids
from desloppify.engine._state.filtering import issue_in_scan_scope
from desloppify.engine._state.schema import StateModel

from .context import has_objective_backlog, is_mid_cycle

TriageStartAction = Literal["inject", "defer", "already_active"]


@dataclass(frozen=True)
class TriageStartDecision:
    action: TriageStartAction
    reason: str


def _has_unfinished_stage_records(plan: PlanModel) -> bool:
    """True when stage reports exist but are still unconfirmed."""
    meta = plan.get("epic_triage_meta", {})
    triage_stages = meta.get("triage_stages", {}) if isinstance(meta, dict) else {}
    return bool(recorded_unconfirmed_triage_stage_names(triage_stages))


def _has_existing_repairs_before_triage(
    plan: PlanModel,
    state: StateModel | dict,
    policy: SubjectiveVisibility | None,
) -> bool:
    """Exclude findings awaiting classification from their own triage gate."""
    if not has_objective_backlog(state, policy):
        return False
    meta = plan.get("epic_triage_meta", {})
    owned = set(meta.get("triaged_ids", [])) | set(plan.get("promoted_ids", []))
    for cluster in plan.get("clusters", {}).values():
        if not cluster.get("auto") or cluster.get("user_modified"):
            owned.update(cluster.get("issue_ids", []))
    pending = open_review_ids(state) - owned
    if not pending:
        return True

    # Import sync appends new review findings to queue_order before triage.
    # They remain concrete repairs for other visibility/rerun policy, but
    # cannot block the stage that will decide their execution contracts.
    issues = state.get("work_items") or state.get("issues", {})
    existing = {
        issue_id: issue for issue_id, issue in issues.items() if issue_id not in pending
    }
    filtered_state = {**state, "work_items": existing, "issues": existing}
    remaining = compute_subjective_visibility(filtered_state, plan=plan)
    if remaining.has_objective_backlog:
        return True
    if policy is None:
        return False
    # A supplied policy may count review repairs even when the default
    # producer does not. Subtract only pending IDs eligible for that queue;
    # retain the caller's remaining repair count, including owned reviews.
    eligible_pending = executable_objective_ids(
        {
            issue_id
            for issue_id in pending
            if not issues[issue_id].get("suppressed")
            and not _is_evidence_only(issues[issue_id])
            and issue_in_scan_scope(
                str(issues[issue_id].get("file", "")), state.get("scan_path")
            )
        },
        plan,
    )
    return policy.objective_count > len(eligible_pending)


def decide_triage_start(
    plan: PlanModel,
    state: StateModel | dict | None,
    *,
    policy: SubjectiveVisibility | None = None,
    explicit_start: bool = False,
    attested_override: bool = False,
) -> TriageStartDecision:
    """Return whether triage should inject now, defer, or is already active."""
    order = set(plan.get("queue_order", []))
    if order & TRIAGE_IDS:
        return TriageStartDecision(action="already_active", reason="already_active")
    if _has_unfinished_stage_records(plan):
        if explicit_start and attested_override:
            return TriageStartDecision(action="inject", reason="attested_override")
        return TriageStartDecision(
            action="defer",
            reason="unfinished_triage_stage_records",
        )

    if state is None:
        return TriageStartDecision(action="inject", reason="no_state_available")

    has_objective = _has_existing_repairs_before_triage(plan, state, policy)
    if is_mid_cycle(plan) and has_objective:
        if explicit_start and attested_override:
            return TriageStartDecision(action="inject", reason="attested_override")
        return TriageStartDecision(action="defer", reason="objective_backlog_mid_cycle")

    return TriageStartDecision(action="inject", reason="default")


__all__ = ["TriageStartAction", "TriageStartDecision", "decide_triage_start"]
