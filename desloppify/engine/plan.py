"""Public plan API facade.

Plan internals live in ``desloppify.engine._plan``; this module exposes
the stable, non-private API used by commands and rendering helpers.
"""

from __future__ import annotations

# --- auto-clustering --------------------------------------------------------
from desloppify.engine._plan.auto_cluster import (
    AUTO_PREFIX,
    auto_cluster_issues,
)

# --- commit tracking --------------------------------------------------------
from desloppify.engine._plan.commit_tracking import (
    add_uncommitted_issues,
    commit_tracking_summary,
    filter_issue_ids_by_pattern,
    find_commit_for_issue,
    generate_pr_body,
    get_uncommitted_issues,
    purge_uncommitted_ids,
    record_commit,
    suggest_commit_message,
)

# --- epic triage ------------------------------------------------------------
from desloppify.engine._plan.epic_triage import (
    TriageInput,
    build_triage_prompt,
    collect_triage_input,
    detect_recurring_patterns,
    extract_issue_citations,
)
from desloppify.engine._plan.triage_playbook import (
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
    TRIAGE_CMD_SENSE_CHECK,
    TRIAGE_STAGE_DEPENDENCIES,
    TRIAGE_STAGE_LABELS,
)

# --- operations -------------------------------------------------------------
from desloppify.engine._plan.annotations import annotation_counts
from desloppify.engine._plan.operations_cluster import (
    add_to_cluster,
    create_cluster,
    delete_cluster,
    merge_clusters,
    move_cluster,
    remove_from_cluster,
)
from desloppify.engine._plan.operations_lifecycle import (
    clear_focus,
    purge_ids,
    reset_plan,
    set_focus,
)
from desloppify.engine._plan.operations_meta import (
    annotate_issue,
    append_log_entry,
    describe_issue,
)
from desloppify.engine._plan.operations_queue import move_items
from desloppify.engine._plan.operations_skip import (
    resurface_stale_skips,
    skip_items,
    unskip_items,
)
from desloppify.engine._plan.skip_policy import (
    SKIP_KIND_LABELS,
    USER_SKIP_KINDS,
    skip_kind_from_flags,
    skip_kind_requires_attestation,
    skip_kind_requires_note,
    skip_kind_state_status,
)
from desloppify.engine._plan.step_completion import auto_complete_steps
from desloppify.engine._plan.step_parser import (
    format_steps,
    normalize_step,
    parse_steps_file,
    step_summary,
)

# --- persistence ------------------------------------------------------------
from desloppify.engine._plan.persistence import (
    PLAN_FILE,
    has_living_plan,
    load_plan,
    plan_lock,
    plan_path_for_state,
    save_plan,
)

# --- reconcile --------------------------------------------------------------
from desloppify.engine._plan.reconcile import (
    ReconcileResult,
    ReviewImportSyncResult,
    reconcile_plan_after_scan,
    sync_plan_after_review_import,
)

# --- schema -----------------------------------------------------------------
from desloppify.engine._plan.schema import (
    ActionStep,
    EPIC_PREFIX,
    PLAN_VERSION,
    VALID_EPIC_DIRECTIONS,
    VALID_SKIP_KINDS,
    Cluster,
    CommitRecord,
    ExecutionLogEntry,
    ItemOverride,
    PlanModel,
    SkipEntry,
    SupersededEntry,
    empty_plan,
    ensure_plan_defaults,
    triage_clusters,
    validate_plan,
)

# --- stale dimensions -------------------------------------------------------
from desloppify.engine._plan.stale_dimensions import (
    SYNTHETIC_PREFIXES,
    TRIAGE_ID,
    TRIAGE_IDS,
    TRIAGE_PREFIX,
    TRIAGE_STAGE_IDS,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    WORKFLOW_PREFIX,
    CommunicateScoreSyncResult,
    ImportScoresSyncResult,
    StaleDimensionSyncResult,
    TriageSyncResult,
    UnscoredDimensionSyncResult,
    compute_new_issue_ids,
    current_unscored_ids,
    is_triage_stale,
    review_issue_snapshot_hash,
    sync_communicate_score_needed,
    sync_import_scores_needed,
    sync_create_plan_needed,
    sync_score_checkpoint_needed,
    sync_stale_dimensions,
    sync_triage_needed,
    sync_unscored_dimensions,
)
from desloppify.engine._plan.stale_policy import (
    _REVIEW_DETECTORS,
    open_review_ids,
)

# --- subjective policy ------------------------------------------------------
from desloppify.engine._plan.subjective_policy import (
    compute_subjective_visibility,
)


def triage_phase_banner(plan: PlanModel) -> str:
    """Return a banner string when triage stage IDs are in the queue."""
    ensure_plan_defaults(plan)
    order = set(plan.get("queue_order", []))
    has_triage = any(sid in order for sid in TRIAGE_IDS)
    if not has_triage:
        return ""
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    completed = [s for s in ("observe", "reflect", "organize", "enrich", "sense-check") if s in stages]
    if completed:
        return (
            f"TRIAGE MODE ({len(completed)}/5 stages complete) — "
            "complete all stages to exit. Run: desloppify plan triage"
        )
    return (
        "TRIAGE MODE — review issues need analysis before fixing. "
        "Run: desloppify plan triage"
    )


__all__ = [
    # schema
    "EPIC_PREFIX",
    "ExecutionLogEntry",
    "PLAN_VERSION",
    "Cluster",
    "CommitRecord",
    "ItemOverride",
    "PlanModel",
    "SkipEntry",
    "SupersededEntry",
    "VALID_EPIC_DIRECTIONS",
    "VALID_SKIP_KINDS",
    "USER_SKIP_KINDS",
    "empty_plan",
    "ensure_plan_defaults",
    "triage_clusters",
    "validate_plan",
    # persistence
    "PLAN_FILE",
    "has_living_plan",
    "load_plan",
    "plan_lock",
    "plan_path_for_state",
    "save_plan",
    # operations
    "add_to_cluster",
    "annotate_issue",
    "append_log_entry",
    "clear_focus",
    "create_cluster",
    "delete_cluster",
    "describe_issue",
    "merge_clusters",
    "move_cluster",
    "move_items",
    "purge_ids",
    "remove_from_cluster",
    "reset_plan",
    "resurface_stale_skips",
    "set_focus",
    "skip_items",
    "skip_kind_from_flags",
    "skip_kind_requires_attestation",
    "skip_kind_requires_note",
    "skip_kind_state_status",
    "SKIP_KIND_LABELS",
    "unskip_items",
    "annotation_counts",
    "auto_complete_steps",
    "format_steps",
    "normalize_step",
    "parse_steps_file",
    "step_summary",
    # reconcile
    "ReconcileResult",
    "ReviewImportSyncResult",
    "reconcile_plan_after_scan",
    "sync_plan_after_review_import",
    # commit tracking
    "add_uncommitted_issues",
    "commit_tracking_summary",
    "filter_issue_ids_by_pattern",
    "find_commit_for_issue",
    "generate_pr_body",
    "get_uncommitted_issues",
    "purge_uncommitted_ids",
    "record_commit",
    "suggest_commit_message",
    # auto-clustering
    "AUTO_PREFIX",
    "auto_cluster_issues",
    # stale dimensions
    "TRIAGE_ID",
    "TRIAGE_IDS",
    "TRIAGE_PREFIX",
    "TRIAGE_STAGE_IDS",
    "SYNTHETIC_PREFIXES",
    "WORKFLOW_CREATE_PLAN_ID",
    "WORKFLOW_SCORE_CHECKPOINT_ID",
    "WORKFLOW_PREFIX",
    "CommunicateScoreSyncResult",
    "ImportScoresSyncResult",
    "StaleDimensionSyncResult",
    "TriageSyncResult",
    "UnscoredDimensionSyncResult",
    "compute_new_issue_ids",
    "current_unscored_ids",
    "is_triage_stale",
    "review_issue_snapshot_hash",
    "sync_communicate_score_needed",
    "sync_import_scores_needed",
    "sync_create_plan_needed",
    "sync_score_checkpoint_needed",
    "sync_stale_dimensions",
    "sync_triage_needed",
    "sync_unscored_dimensions",
    "open_review_ids",
    "_REVIEW_DETECTORS",
    # epic triage
    "TriageInput",
    "build_triage_prompt",
    "collect_triage_input",
    "detect_recurring_patterns",
    "extract_issue_citations",
    "TRIAGE_STAGE_DEPENDENCIES",
    "TRIAGE_STAGE_LABELS",
    "TRIAGE_CMD_OBSERVE",
    "TRIAGE_CMD_REFLECT",
    "TRIAGE_CMD_ORGANIZE",
    "TRIAGE_CMD_ENRICH",
    "TRIAGE_CMD_SENSE_CHECK",
    "TRIAGE_CMD_COMPLETE",
    "TRIAGE_CMD_COMPLETE_VERBOSE",
    "TRIAGE_CMD_CONFIRM_EXISTING",
    "TRIAGE_CMD_CLUSTER_CREATE",
    "TRIAGE_CMD_CLUSTER_ADD",
    "TRIAGE_CMD_CLUSTER_ENRICH",
    "TRIAGE_CMD_CLUSTER_ENRICH_COMPACT",
    "TRIAGE_CMD_CLUSTER_STEPS",
    # subjective policy
    "compute_subjective_visibility",
    # triage
    "triage_phase_banner",
]
