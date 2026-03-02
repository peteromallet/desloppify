"""Public plan API facade.

Plan internals live in ``desloppify.engine._plan``; this module exposes
the stable, non-private API used by commands and rendering helpers.
"""

from __future__ import annotations

# --- schema -----------------------------------------------------------------
from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    PLAN_VERSION,
    Cluster,
    ItemOverride,
    PlanModel,
    SkipEntry,
    SupersededEntry,
    VALID_EPIC_DIRECTIONS,
    VALID_SKIP_KINDS,
    empty_plan,
    ensure_plan_defaults,
    synthesis_clusters,
    validate_plan,
)

# --- persistence ------------------------------------------------------------
from desloppify.engine._plan.persistence import (
    PLAN_FILE,
    has_living_plan,
    load_plan,
    plan_path_for_state,
    save_plan,
)

# --- operations -------------------------------------------------------------
from desloppify.engine._plan.operations import (
    add_to_cluster,
    annotate_finding,
    clear_focus,
    create_cluster,
    delete_cluster,
    describe_finding,
    move_cluster,
    move_items,
    purge_ids,
    remove_from_cluster,
    reset_plan,
    resurface_stale_skips,
    set_focus,
    skip_items,
    unskip_items,
)

# --- reconcile --------------------------------------------------------------
from desloppify.engine._plan.reconcile import (
    ReconcileResult,
    reconcile_plan_after_scan,
)

# --- auto-clustering --------------------------------------------------------
from desloppify.engine._plan.auto_cluster import (
    AUTO_PREFIX,
    auto_cluster_findings,
)

# --- stale dimensions -------------------------------------------------------
from desloppify.engine._plan.stale_dimensions import (
    SYNTHESIS_ID,
    StaleDimensionSyncResult,
    UnscoredDimensionSyncResult,
    review_finding_snapshot_hash,
    sync_stale_dimensions,
    sync_synthesis_needed,
    sync_unscored_dimensions,
)

def synthesis_phase_banner(plan: PlanModel) -> str:
    """Return a banner string when ``synthesis::pending`` is in the queue."""
    ensure_plan_defaults(plan)
    if SYNTHESIS_ID not in plan.get("queue_order", []):
        return ""
    meta = plan.get("epic_synthesis_meta", {})
    stages = meta.get("synthesis_stages", {})
    completed = [s for s in ("observe", "reflect", "organize") if s in stages]
    if completed:
        return (
            f"Synthesis in progress ({len(completed)}/4 stages complete). "
            "Run: desloppify plan synthesize"
        )
    return (
        "Synthesis needed — review findings require analysis before fixing. "
        "Run: desloppify plan synthesize"
    )


__all__ = [
    # schema
    "EPIC_PREFIX",
    "PLAN_VERSION",
    "Cluster",
    "ItemOverride",
    "PlanModel",
    "SkipEntry",
    "SupersededEntry",
    "VALID_EPIC_DIRECTIONS",
    "VALID_SKIP_KINDS",
    "empty_plan",
    "ensure_plan_defaults",
    "synthesis_clusters",
    "validate_plan",
    # persistence
    "PLAN_FILE",
    "has_living_plan",
    "load_plan",
    "plan_path_for_state",
    "save_plan",
    # operations
    "add_to_cluster",
    "annotate_finding",
    "clear_focus",
    "create_cluster",
    "delete_cluster",
    "describe_finding",
    "move_cluster",
    "move_items",
    "purge_ids",
    "remove_from_cluster",
    "reset_plan",
    "resurface_stale_skips",
    "set_focus",
    "skip_items",
    "unskip_items",
    # reconcile
    "ReconcileResult",
    "reconcile_plan_after_scan",
    # auto-clustering
    "AUTO_PREFIX",
    "auto_cluster_findings",
    # stale dimensions
    "SYNTHESIS_ID",
    "StaleDimensionSyncResult",
    "UnscoredDimensionSyncResult",
    "review_finding_snapshot_hash",
    "sync_stale_dimensions",
    "sync_synthesis_needed",
    "sync_unscored_dimensions",
    # synthesis
    "synthesis_phase_banner",
]
