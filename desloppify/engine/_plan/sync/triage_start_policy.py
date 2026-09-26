"""Shared triage-start policy used by sync and command entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from desloppify.engine._plan.constants import (
    TRIAGE_IDS,
    recorded_unconfirmed_triage_stage_names,
)
from desloppify.engine._plan.schema import PlanModel
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility
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
    triage_stages = (
        meta.get("triage_stages", {})
        if isinstance(meta, dict)
        else {}
    )
    return bool(recorded_unconfirmed_triage_stage_names(triage_stages))


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

    has_objective = has_objective_backlog(state, policy)
    # Postflight objectives remain backlog until planning completes; blocking
    # triage on them would prevent the workflow needed to plan those objectives.
    refresh_state = plan.get("refresh_state")
    planning_mode = (
        isinstance(refresh_state, dict)
        and refresh_state.get("lifecycle_phase") == "plan"
    )
    if not planning_mode and is_mid_cycle(plan) and has_objective:
        if explicit_start and attested_override:
            return TriageStartDecision(action="inject", reason="attested_override")
        return TriageStartDecision(action="defer", reason="objective_backlog_mid_cycle")

    return TriageStartDecision(action="inject", reason="default")


__all__ = ["TriageStartAction", "TriageStartDecision", "decide_triage_start"]
