"""Post-scan reconciliation for stale or disappeared issue references."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from desloppify.engine._plan.annotations import get_issue_note
from desloppify.engine._plan.constants import SYNTHETIC_PREFIXES
from desloppify.engine._plan.cluster_semantics import EXECUTION_STATUS_DONE, cluster_is_active
from desloppify.engine._plan.operations.lifecycle import clear_focus_if_cluster_empty
from desloppify.engine._plan.operations.meta import append_log_entry
from desloppify.engine._plan.operations.skip import resurface_stale_skips
from desloppify.engine._plan.promoted_ids import prune_promoted_ids
from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    PlanModel,
    SupersededEntry,
    ensure_plan_defaults,
)
from desloppify.engine._plan.skip_policy import skip_kind_state_status
from desloppify.engine._state.schema import StateModel, ensure_state_defaults, utc_now

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
    """Find alive issues that could be remaps for a disappeared issue."""
    candidates: list[str] = []
    for fid, issue in (state.get("work_items") or state.get("issues", {})).items():
        if issue.get("status") not in _ALIVE_STATUSES:
            continue
        if issue.get("detector") == detector and issue.get("file") == file:
            candidates.append(fid)
    return candidates


_ALIVE_STATUSES = frozenset({"open", "deferred", "triaged_out"})


def _is_issue_alive(state: StateModel, issue_id: str) -> bool:
    """Return True if the issue exists and is actionable (open/deferred/triaged_out)."""
    issue = (state.get("work_items") or state.get("issues", {})).get(issue_id)
    if issue is None:
        return False
    return issue.get("status") in _ALIVE_STATUSES


def _supersede_id(
    plan: PlanModel,
    state: StateModel,
    issue_id: str,
    now: str,
) -> bool:
    """Move a disappeared issue to superseded. Returns True if changed."""
    issue = (state.get("work_items") or state.get("issues", {})).get(issue_id)
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


def _referenced_plan_issue_ids(plan: PlanModel) -> set[str]:
    referenced_ids: set[str] = set()
    referenced_ids.update(plan.get("queue_order", []))
    referenced_ids.update(plan.get("skipped", {}).keys())
    referenced_ids.update(plan.get("overrides", {}).keys())
    for cluster in plan.get("clusters", {}).values():
        referenced_ids.update(cluster.get("issue_ids", []))
    already_superseded = set(plan.get("superseded", {}).keys())
    return {
        fid for fid in referenced_ids - already_superseded
        if not any(fid.startswith(prefix) for prefix in SYNTHETIC_PREFIXES)
    }


def _prune_existing_superseded_references(
    plan: PlanModel,
    *,
    result: ReconcileResult,
) -> None:
    superseded_ids = {
        fid for fid in plan.get("superseded", {})
        if isinstance(fid, str) and fid
    }
    if not superseded_ids:
        return

    changes = 0
    order = plan.get("queue_order", [])
    kept_order = [fid for fid in order if fid not in superseded_ids]
    if len(kept_order) != len(order):
        changes += len(order) - len(kept_order)
        order[:] = kept_order

    skipped = plan.get("skipped", {})
    for fid in list(skipped):
        if fid in superseded_ids:
            skipped.pop(fid, None)
            changes += 1

    promoted_before = len(plan.get("promoted_ids", []))
    prune_promoted_ids(plan, superseded_ids)
    changes += max(0, promoted_before - len(plan.get("promoted_ids", [])))

    for cluster in plan.get("clusters", {}).values():
        issue_ids = cluster.get("issue_ids", [])
        kept_issue_ids = [fid for fid in issue_ids if fid not in superseded_ids]
        if len(kept_issue_ids) != len(issue_ids):
            changes += len(issue_ids) - len(kept_issue_ids)
            cluster["issue_ids"] = kept_issue_ids
        for step in cluster.get("action_steps", []):
            if not isinstance(step, dict):
                continue
            refs = step.get("issue_refs", [])
            kept_refs = [fid for fid in refs if fid not in superseded_ids]
            if len(kept_refs) != len(refs):
                changes += len(refs) - len(kept_refs)
                step["issue_refs"] = kept_refs

    for fid in superseded_ids:
        override = plan.get("overrides", {}).get(fid)
        if override and override.get("cluster"):
            override["cluster"] = None
            changes += 1

    result.changes += changes


def _supersede_dead_references(
    plan: PlanModel,
    state: StateModel,
    *,
    referenced_ids: set[str],
    now: str,
    result: ReconcileResult,
) -> None:
    for fid in sorted(referenced_ids):
        if _is_issue_alive(state, fid):
            continue
        if _supersede_id(plan, state, fid, now):
            result.superseded.append(fid)
            result.changes += 1


def _complete_empty_manual_clusters(
    plan: PlanModel,
    *,
    pre_sizes: dict[str, int],
    result: ReconcileResult,
) -> None:
    clusters = plan.get("clusters", {})
    for name, prev_size in pre_sizes.items():
        if prev_size == 0:
            continue
        cluster = clusters.get(name)
        if cluster is None or len(cluster.get("issue_ids", [])) != 0:
            continue
        result.clusters_completed.append(name)
        cluster["execution_status"] = EXECUTION_STATUS_DONE
        append_log_entry(
            plan,
            "cluster_done",
            issue_ids=[],
            cluster_name=name,
            actor="system",
            detail={"reason": "cluster members no longer actionable in state"},
        )
        result.changes += 1


_RESOLVED_STATUSES = frozenset({"fixed", "auto_resolved", "wontfix"})


def _reconcile_active_clusters_by_item_status(
    plan: PlanModel,
    state: StateModel,
    *,
    result: ReconcileResult,
) -> None:
    """Mark active clusters as done when all their items are resolved."""
    clusters = plan.get("clusters", {})
    issues = state.get("work_items") or state.get("issues", {})
    for name, cluster in clusters.items():
        if not cluster_is_active(cluster):
            continue
        issue_ids = cluster.get("issue_ids", [])
        if not issue_ids:
            continue
        all_resolved = all(
            issues.get(fid, {}).get("status") in _RESOLVED_STATUSES
            for fid in issue_ids
        )
        if not all_resolved:
            continue
        cluster["execution_status"] = EXECUTION_STATUS_DONE
        result.clusters_completed.append(name)
        append_log_entry(
            plan,
            "cluster_done",
            issue_ids=issue_ids,
            cluster_name=name,
            actor="system",
            detail={"reason": "all items resolved in state"},
        )
        result.changes += 1


def _reconcile_epic_clusters(
    plan: PlanModel,
    state: StateModel,
    *,
    result: ReconcileResult,
) -> None:
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


def _sync_skipped_issue_statuses(plan: PlanModel, state: StateModel) -> None:
    """Sync state status for skipped issues that are still 'open'.

    Ensures state is authoritative: temporary → deferred, triaged_out → triaged_out.
    Runs on every reconcile so existing data gets migrated on next scan.
    """
    skipped = plan.get("skipped", {})
    issues = (state.get("work_items") or state.get("issues", {}))
    for fid, entry in skipped.items():
        issue = issues.get(fid)
        if issue is None or issue.get("status") != "open":
            continue
        kind = str(entry.get("kind", ""))
        target_status = skip_kind_state_status(kind)
        if target_status and target_status != "open":
            issue["status"] = target_status


def reconcile_plan_after_scan(
    plan: PlanModel,
    state: StateModel,
) -> ReconcileResult:
    """Reconcile plan against current state after a scan.

    Finds IDs referenced in the plan that no longer exist or are no longer
    open, moves them to superseded, and prunes old superseded entries.
    """
    ensure_plan_defaults(plan)
    ensure_state_defaults(state)
    result = ReconcileResult()
    now = utc_now()
    now_dt = datetime.now(UTC)

    _prune_existing_superseded_references(plan, result=result)
    referenced_ids = _referenced_plan_issue_ids(plan)

    # Snapshot non-epic cluster sizes before superseding so we can detect
    # clusters that become empty after state reconciliation.
    clusters = plan.get("clusters", {})
    pre_sizes: dict[str, int] = {
        name: len(cluster.get("issue_ids", []))
        for name, cluster in clusters.items()
        if not name.startswith(EPIC_PREFIX)
    }

    # Sync state status for issues in plan.skipped that are still "open" in state.
    # This migrates existing data: temporary skips → deferred, triaged_out skips → triaged_out.
    _sync_skipped_issue_statuses(plan, state)

    _supersede_dead_references(
        plan,
        state,
        referenced_ids=referenced_ids,
        now=now,
        result=result,
    )
    _complete_empty_manual_clusters(plan, pre_sizes=pre_sizes, result=result)
    _reconcile_active_clusters_by_item_status(plan, state, result=result)
    _reconcile_epic_clusters(plan, state, result=result)

    clear_focus_if_cluster_empty(plan)

    # Resurface stale temporary skips
    scan_count = state.get("scan_count", 0)

    resurfaced = resurface_stale_skips(plan, scan_count)
    if resurfaced:
        result.resurfaced = resurfaced
        result.changes += len(resurfaced)
        # Reopen resurfaced issues in state (they were deferred)
        issues = (state.get("work_items") or state.get("issues", {}))
        for fid in resurfaced:
            issue = issues.get(fid)
            if issue and issue.get("status") == "deferred":
                issue["status"] = "open"

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

__all__ = [
    "ReconcileResult",
    "reconcile_plan_after_scan",
]
