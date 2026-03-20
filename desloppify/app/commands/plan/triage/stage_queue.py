"""Queue/stage mutation helpers for triage workflow."""

from __future__ import annotations

from typing import Any

from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.constants import normalize_queue_workflow_and_triage_prefix
from desloppify.engine.plan_ops import purge_ids
from desloppify.engine.plan_state import PlanModel
from desloppify.engine.plan_triage import TRIAGE_IDS, TRIAGE_STAGE_IDS

from .plan_state_access import ensure_queue_order, ensure_skipped_map

STAGE_ORDER = ["strategize", "observe", "reflect", "organize", "enrich", "sense-check"]


def has_triage_in_queue(plan: PlanModel) -> bool:
    """Return True when any triage stage IDs are currently queued."""
    order = set(ensure_queue_order(plan))
    return bool(order & TRIAGE_IDS)


def clear_triage_stage_skips(plan: PlanModel) -> None:
    """Remove skipped markers for triage stages before reinjection."""
    skipped = ensure_skipped_map(plan)
    for sid in TRIAGE_STAGE_IDS:
        skipped.pop(sid, None)


def inject_triage_stages(plan: PlanModel) -> None:
    """Inject the canonical triage stage IDs at the queue front."""
    order = ensure_queue_order(plan)
    clear_triage_stage_skips(plan)
    remaining = [issue_id for issue_id in order if issue_id not in TRIAGE_IDS]
    order[:] = [*remaining, *TRIAGE_STAGE_IDS]
    normalize_queue_workflow_and_triage_prefix(order)


def purge_triage_stage(plan: PlanModel, stage_name: str) -> None:
    """Remove one triage stage workflow item from the plan."""
    purge_ids(plan, [f"triage::{stage_name}"])


def cascade_clear_dispositions(meta: dict[str, Any], from_stage: str) -> None:
    """Reset issue_dispositions when an earlier stage reruns.

    - observe rerun: wipe the entire disposition map (verdicts change)
    - reflect rerun: clear decision/target/decision_source from all entries
      (observe verdicts remain, but reflect decisions are outdated)
    """
    dispositions = meta.get("issue_dispositions")
    if not dispositions:
        return
    if from_stage == "observe":
        meta["issue_dispositions"] = {}
    elif from_stage == "reflect":
        for entry in dispositions.values():
            entry.pop("decision", None)
            entry.pop("target", None)
            entry.pop("decision_source", None)


def cascade_clear_later_confirmations(
    stages: dict[str, dict[str, Any]],
    from_stage: str,
) -> list[str]:
    """Clear later-stage confirmations after mutating an earlier stage."""
    try:
        idx = STAGE_ORDER.index(from_stage)
    except ValueError:
        return []
    cleared: list[str] = []
    for later in STAGE_ORDER[idx + 1:]:
        if later in stages and stages[later].get("confirmed_at"):
            stages[later].pop("confirmed_at", None)
            stages[later].pop("confirmed_text", None)
            cleared.append(later)
    return cleared


def print_cascade_clear_feedback(
    cleared: list[str],
    stages: dict[str, dict[str, Any]],
) -> None:
    """Render confirmation-clearing feedback after stage rewrites."""
    if not cleared:
        return
    print(colorize(f"  Cleared confirmations on: {', '.join(cleared)}", "yellow"))
    next_unconfirmed = next(
        (
            stage
            for stage in STAGE_ORDER
            if stage in stages and not stages[stage].get("confirmed_at")
        ),
        None,
    )
    if next_unconfirmed:
        print(
            colorize(
                f"  Re-confirm with: desloppify plan triage --confirm {next_unconfirmed}",
                "dim",
            )
        )


__all__ = [
    "STAGE_ORDER",
    "cascade_clear_dispositions",
    "cascade_clear_later_confirmations",
    "has_triage_in_queue",
    "inject_triage_stages",
    "print_cascade_clear_feedback",
    "purge_triage_stage",
]
