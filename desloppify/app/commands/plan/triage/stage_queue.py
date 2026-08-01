"""Queue/stage mutation helpers for triage workflow."""

from __future__ import annotations

from typing import Any

from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.triage.lifecycle import (
    has_triage_in_queue,
    inject_triage_stages,
)
from desloppify.engine._plan.triage.protection import (
    protected_review_issue_ids_from_meta,
)
from desloppify.engine.plan_ops import purge_ids
from desloppify.engine.plan_state import PlanModel

STAGE_ORDER = ["strategize", "observe", "reflect", "organize", "enrich", "sense-check"]


def purge_triage_stage(plan: PlanModel, stage_name: str) -> None:
    """Remove one triage stage workflow item from the plan."""
    purge_ids(plan, [f"triage::{stage_name}"])


def cascade_clear_dispositions(meta: dict[str, Any], from_stage: str) -> None:
    """Reset issue_dispositions when an earlier stage reruns.

    - observe rerun: wipe the entire disposition map (verdicts change)
    - reflect rerun: clear reflect decision/target/decision_source entries
      (observe verdicts and observe-auto skips remain)
    """
    dispositions = meta.get("issue_dispositions")
    if not dispositions:
        return
    protected_ids = protected_review_issue_ids_from_meta(meta)
    for issue_id in protected_ids:
        dispositions.pop(issue_id, None)
    if from_stage == "observe":
        meta["issue_dispositions"] = {}
    elif from_stage == "reflect":
        for entry in dispositions.values():
            if entry.get("decision_source") == "observe_auto":
                continue
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
    for later in STAGE_ORDER[idx + 1 :]:
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
