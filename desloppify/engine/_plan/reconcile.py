"""Post-scan plan reconciliation — handle issue churn."""

from __future__ import annotations

from dataclasses import dataclass, field
from desloppify.base.compatibility import UTC
from datetime import datetime, timedelta

from desloppify.engine._plan.annotations import get_issue_note
from desloppify.engine._plan.operations_meta import append_log_entry
from desloppify.engine._plan.operations_skip import resurface_stale_skips
from desloppify.engine._plan.promoted_ids import prune_promoted_ids
from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    PlanModel,
    SupersededEntry,
    ensure_plan_defaults,
)
from desloppify.engine._plan.stale_dimensions import (
    SYNTHETIC_PREFIXES,
    compute_new_issue_ids,
    sync_triage_needed,
)
from desloppify.engine._state.schema import StateModel, utc_now

SUPERSEDED_TTL_DAYS = 90


@dataclass
class ReconcileResult:
    """Summary of changes made during reconciliation."""

    superseded: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    resurfaced: list[str] = field(default_factory=list)
    clusters_completed: list[str] = field(default_factory=list)
    changes: int = 0


def _find_candidates(
    state: StateModel, detector: str, file: str
) -> list[str]:
    """Find open issues that could be remaps for a disappeared issue."""
    candidates: list[str] = []
    for fid, issue in state.get("issues", {}).items():
        if issue.get("status") != "open":
            continue
        if issue.get("detector") == detector and issue.get("file") == file:
            candidates.append(fid)
    return candidates


def _is_issue_alive(state: StateModel, issue_id: str) -> bool:
    """Return True if the issue exists and is open."""
    issue = state.get("issues", {}).get(issue_id)
    if issue is None:
        return False
    return issue.get("status") == "open"


def _supersede_id(
    plan: PlanModel,
    state: StateModel,
    issue_id: str,
    now: str,
) -> bool:
    """Move a disappeared issue to superseded. Returns True if changed."""
    issue = state.get("issues", {}).get(issue_id)
    detector = ""
    file = ""
    summary = ""
    if issue:
        detector = issue.get("detector", "")
        file = issue.get("file", "")
        summary = issue.get("summary", "")

    candidates = _find_candidates(state, detector, file) if detector else []
    # Don't include the original in candidates
    candidates = [c for c in candidates if c != issue_id]

    entry: SupersededEntry = {
        "original_id": issue_id,
        "original_detector": detector,
        "original_file": file,
        "original_summary": summary,
        "status": "superseded",
        "superseded_at": now,
        "remapped_to": None,
        "candidates": candidates[:5],
    }

    # Preserve any existing override note
    override_note = get_issue_note(plan, issue_id)
    if override_note:
        entry["note"] = override_note

    plan["superseded"][issue_id] = entry

    # Remove from queue_order, skipped, promoted_ids, cluster issue_ids
    order: list[str] = plan.get("queue_order", [])
    skipped: dict = plan.get("skipped", {})
    if issue_id in order:
        order.remove(issue_id)
    skipped.pop(issue_id, None)
    prune_promoted_ids(plan, {issue_id})
    for cluster in plan.get("clusters", {}).values():
        ids = cluster.get("issue_ids", [])
        if issue_id in ids:
            ids.remove(issue_id)

    # Clear stale cluster reference from override
    override = plan.get("overrides", {}).get(issue_id)
    if override and override.get("cluster"):
        override["cluster"] = None
        override["updated_at"] = now

    return True


def _prune_old_superseded(plan: PlanModel, now_dt: datetime) -> list[str]:
    """Remove superseded entries older than TTL. Returns pruned IDs."""
    superseded = plan.get("superseded", {})
    cutoff = now_dt - timedelta(days=SUPERSEDED_TTL_DAYS)
    to_prune: list[str] = []

    for fid, entry in superseded.items():
        ts = entry.get("superseded_at", "")
        try:
            entry_dt = datetime.fromisoformat(ts)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=UTC)
            if entry_dt < cutoff:
                to_prune.append(fid)
        except (ValueError, TypeError):
            to_prune.append(fid)

    for fid in to_prune:
        superseded.pop(fid, None)
        # Also clean up stale overrides
        plan.get("overrides", {}).pop(fid, None)

    return to_prune


def reconcile_plan_after_scan(
    plan: PlanModel,
    state: StateModel,
) -> ReconcileResult:
    """Reconcile plan against current state after a scan.

    Finds IDs referenced in the plan that no longer exist or are no longer
    open, moves them to superseded, and prunes old superseded entries.
    """
    ensure_plan_defaults(plan)
    result = ReconcileResult()
    now = utc_now()
    now_dt = datetime.now(UTC)

    # Collect all issue IDs referenced by the plan
    referenced_ids: set[str] = set()
    referenced_ids.update(plan.get("queue_order", []))
    referenced_ids.update(plan.get("skipped", {}).keys())
    for override_id in plan.get("overrides", {}):
        referenced_ids.add(override_id)
    for cluster in plan.get("clusters", {}).values():
        referenced_ids.update(cluster.get("issue_ids", []))

    # Exclude already-superseded IDs and synthetic IDs (managed by stale_dimensions)
    already_superseded = set(plan.get("superseded", {}).keys())
    referenced_ids -= already_superseded
    referenced_ids = {
        fid for fid in referenced_ids
        if not any(fid.startswith(prefix) for prefix in SYNTHETIC_PREFIXES)
    }

    # Snapshot non-epic cluster sizes before superseding so we can detect
    # clusters that become empty (all issues resolved by scan).
    clusters = plan.get("clusters", {})
    pre_sizes: dict[str, int] = {
        name: len(cluster.get("issue_ids", []))
        for name, cluster in clusters.items()
        if not name.startswith(EPIC_PREFIX)
    }

    # Check each referenced ID
    for fid in sorted(referenced_ids):
        if not _is_issue_alive(state, fid):
            if _supersede_id(plan, state, fid, now):
                result.superseded.append(fid)
                result.changes += 1

    # Detect manual clusters that just became empty (all issues auto-resolved).
    # Log cluster_done so the plan tracks completion the same way as user resolves.
    for name, prev_size in pre_sizes.items():
        if prev_size == 0:
            continue  # was already empty
        cluster = clusters.get(name)
        if cluster is None:
            continue
        if len(cluster.get("issue_ids", [])) == 0:
            result.clusters_completed.append(name)
            append_log_entry(
                plan,
                "cluster_done",
                issue_ids=[],
                cluster_name=name,
                actor="system",
                detail={"reason": "all issues resolved by scan"},
            )
            result.changes += 1

    # Reconcile epic clusters: remove dead issues, delete empty epics
    clusters = plan.get("clusters", {})
    epic_names_to_delete: list[str] = []
    for name, cluster in list(clusters.items()):
        if not name.startswith(EPIC_PREFIX):
            continue
        issue_ids = cluster.get("issue_ids", [])
        alive_ids = [fid for fid in issue_ids if _is_issue_alive(state, fid)]
        if alive_ids != issue_ids:
            cluster["issue_ids"] = alive_ids
            result.changes += 1
        if not alive_ids:
            epic_names_to_delete.append(name)
    for name in epic_names_to_delete:
        clusters.pop(name, None)
        result.changes += 1

    # Resurface stale temporary skips
    scan_count = state.get("scan_count", 0)

    resurfaced = resurface_stale_skips(plan, scan_count)
    if resurfaced:
        result.resurfaced = resurfaced
        result.changes += len(resurfaced)

    # Prune old superseded entries
    pruned = _prune_old_superseded(plan, now_dt)
    result.pruned = pruned
    result.changes += len(pruned)

    # Log reconciliation if any changes were made
    if result.changes > 0:
        append_log_entry(
            plan,
            "reconcile",
            issue_ids=result.superseded,
            actor="system",
            detail={
                "superseded_count": len(result.superseded),
                "pruned_count": len(result.pruned),
                "resurfaced_count": len(result.resurfaced),
                "clusters_completed_count": len(result.clusters_completed),
            },
        )

    return result


@dataclass
class ReviewImportSyncResult:
    """Summary of plan changes after a review import."""

    new_ids: set[str]
    added_to_queue: list[str]
    triage_injected: bool


def sync_plan_after_review_import(
    plan: PlanModel,
    state: StateModel,
) -> ReviewImportSyncResult | None:
    """Sync plan queue after review import. Pure engine function — no I/O.

    Appends new issue IDs to queue_order and injects triage stages
    if needed. Returns None when there are no new issues to sync.
    """
    ensure_plan_defaults(plan)
    new_ids = compute_new_issue_ids(plan, state)
    if not new_ids:
        return None

    # Add new issue IDs to end of queue_order so they have position
    order: list[str] = plan["queue_order"]
    existing = set(order)
    added: list[str] = []
    for fid in sorted(new_ids):
        if fid not in existing:
            order.append(fid)
            added.append(fid)

    # Inject triage stages if needed
    triage_result = sync_triage_needed(plan, state)
    triage_injected = bool(
        triage_result and getattr(triage_result, "injected", False)
    )

    return ReviewImportSyncResult(
        new_ids=new_ids,
        added_to_queue=added,
        triage_injected=triage_injected,
    )


__all__ = [
    "ReconcileResult",
    "ReviewImportSyncResult",
    "reconcile_plan_after_scan",
    "sync_plan_after_review_import",
]
