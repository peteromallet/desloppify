"""Focused public plan API for triage orchestration surfaces."""

from __future__ import annotations

from desloppify.engine._plan.constants import (
    TRIAGE_IDS,
    TRIAGE_PREFIX,
    TRIAGE_STAGE_IDS,
    TRIAGE_STAGE_ORDER,
    TRIAGE_STAGE_SPECS,
)
from desloppify.engine._plan.triage.core import (
    TriageInput,
    build_triage_prompt,
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
)
from desloppify.engine._plan.triage.playbook import (
    StagePrerequisite,
    StageReadiness,
    TriageProgress,
    TRIAGE_CMD_CLUSTER_ADD,
    TRIAGE_CMD_CLUSTER_CREATE,
    TRIAGE_CMD_CLUSTER_ENRICH,
    TRIAGE_CMD_CLUSTER_ENRICH_COMPACT,
    TRIAGE_CMD_CLUSTER_STEPS,
    TRIAGE_CMD_COMPLETE,
    TRIAGE_CMD_COMPLETE_VERBOSE,
    TRIAGE_CMD_CONFIRM_EXISTING,
    TRIAGE_CMD_ENRICH,
    TRIAGE_CMD_OBSERVE,
    TRIAGE_CMD_ORGANIZE,
    TRIAGE_CMD_REFLECT,
    TRIAGE_CMD_RUN_STAGES_CLAUDE,
    TRIAGE_CMD_RUN_STAGES_CODEX,
    TRIAGE_CMD_SENSE_CHECK,
    TRIAGE_CMD_STRATEGIZE,
    TRIAGE_STAGE_DEPENDENCIES,
    TRIAGE_STAGE_LABELS,
    TRIAGE_STAGE_PREREQUISITES,
    compute_triage_progress,
    triage_manual_stage_command,
    triage_run_stages_command,
    triage_runner_commands,
)
from desloppify.engine._plan.triage.snapshot import (
    TriageSnapshot,
    active_triage_issue_ids,
    build_triage_snapshot,
    coverage_open_ids,
    find_cluster_for,
    live_active_triage_issue_ids,
    manual_clusters_with_issues,
    plan_review_ids,
    triage_coverage,
    undispositioned_triage_issue_ids,
)
from desloppify.engine._plan.sync.triage_start_policy import (
    TriageStartDecision,
    decide_triage_start,
)
from desloppify.engine._plan.sync.context import has_objective_backlog, is_mid_cycle
from desloppify.engine.plan_state import PlanModel, ensure_plan_defaults


def triage_phase_banner(
    plan: PlanModel,
    state: dict | None = None,
    *,
    snapshot: TriageSnapshot | None = None,
) -> str:
    """Return a banner string describing triage status."""
    ensure_plan_defaults(plan)
    meta = plan.get("epic_triage_meta", {})
    run_hint = (
        f"Run: {TRIAGE_CMD_RUN_STAGES_CODEX} "
        f"(or {TRIAGE_CMD_RUN_STAGES_CLAUDE})"
    )
    resolved_state = state or {}
    resolved_snapshot = snapshot or build_triage_snapshot(plan, resolved_state)

    if not resolved_snapshot.has_triage_in_queue:
        if (
            resolved_state
            and resolved_snapshot.is_triage_stale
            and is_mid_cycle(plan)
            and has_objective_backlog(resolved_state, None)
        ):
            return (
                "TRIAGE PENDING — review issues changed since last triage and will "
                "activate after objective work is complete."
            )
        undispositioned = len(resolved_snapshot.undispositioned_ids)
        if undispositioned:
            return (
                "TRIAGE RECOVERY NEEDED — "
                f"{undispositioned} review work item(s) still need cluster/skip dispositions. "
                f"{run_hint}"
            )
        if resolved_snapshot.is_triage_stale or meta.get("triage_recommended"):
            return (
                "TRIAGE RECOMMENDED — review work items changed since last triage. "
                f"{run_hint}"
            )
        return ""

    if resolved_state and has_objective_backlog(resolved_state, None):
        undispositioned = len(resolved_snapshot.undispositioned_ids)
        if undispositioned:
            return (
                "TRIAGE PENDING — "
                f"{undispositioned} review work item(s) still need cluster/skip dispositions after current work. "
                f"{run_hint}"
            )
        return (
            "TRIAGE PENDING — queued and will activate after objective work "
            "is complete."
        )
    progress = resolved_snapshot.progress
    if progress.completed_count:
        total_stages = len(TRIAGE_STAGE_LABELS)
        return (
            f"TRIAGE MODE ({progress.completed_count}/{total_stages} stages recorded) — "
            f"complete all stages to exit. {run_hint}"
        )
    return (
        "TRIAGE MODE — review work items need analysis before fixing. "
        f"{run_hint}"
    )

__all__ = [
    "TRIAGE_CMD_CLUSTER_ADD",
    "TRIAGE_CMD_CLUSTER_CREATE",
    "TRIAGE_CMD_CLUSTER_ENRICH",
    "TRIAGE_CMD_CLUSTER_ENRICH_COMPACT",
    "TRIAGE_CMD_CLUSTER_STEPS",
    "TRIAGE_CMD_COMPLETE",
    "TRIAGE_CMD_COMPLETE_VERBOSE",
    "TRIAGE_CMD_CONFIRM_EXISTING",
    "TRIAGE_CMD_ENRICH",
    "TRIAGE_CMD_OBSERVE",
    "TRIAGE_CMD_ORGANIZE",
    "TRIAGE_CMD_REFLECT",
    "TRIAGE_CMD_RUN_STAGES_CLAUDE",
    "TRIAGE_CMD_RUN_STAGES_CODEX",
    "TRIAGE_CMD_SENSE_CHECK",
    "TRIAGE_CMD_STRATEGIZE",
    "TRIAGE_IDS",
    "TRIAGE_PREFIX",
    "TRIAGE_STAGE_PREREQUISITES",
    "TRIAGE_STAGE_DEPENDENCIES",
    "TRIAGE_STAGE_IDS",
    "TRIAGE_STAGE_LABELS",
    "StagePrerequisite",
    "StageReadiness",
    "TriageProgress",
    "TriageSnapshot",
    "active_triage_issue_ids",
    "TRIAGE_STAGE_ORDER",
    "TRIAGE_STAGE_SPECS",
    "TriageStartDecision",
    "TriageInput",
    "build_triage_snapshot",
    "build_triage_prompt",
    "collect_triage_input",
    "compute_triage_progress",
    "coverage_open_ids",
    "decide_triage_start",
    "detect_recurring_patterns",
    "extract_issue_citations",
    "find_cluster_for",
    "live_active_triage_issue_ids",
    "manual_clusters_with_issues",
    "plan_review_ids",
    "triage_coverage",
    "triage_phase_banner",
    "triage_manual_stage_command",
    "triage_run_stages_command",
    "triage_runner_commands",
    "undispositioned_triage_issue_ids",
]
