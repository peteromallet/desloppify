"""Post-scan plan reconciliation — handle finding churn."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from desloppify.engine._plan.schema import PlanModel, SupersededEntry, ensure_plan_defaults
from desloppify.engine._plan.stale_dimensions import SUBJECTIVE_PREFIX
from desloppify.engine._state.schema import StateModel, utc_now


SUPERSEDED_TTL_DAYS = 90


@dataclass
class ReconcileResult:
    """Summary of changes made during reconciliation."""

    superseded: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    resurfaced: list[str] = field(default_factory=list)
    changes: int = 0


def _find_candidates(
    state: StateModel, detector: str, file: str
) -> list[str]:
    """Find open findings that could be remaps for a disappeared finding."""
    candidates: list[str] = []
    for fid, finding in state.get("findings", {}).items():
        if finding.get("status") != "open":
            continue
        if finding.get("detector") == detector and finding.get("file") == file:
            candidates.append(fid)
    return candidates


def _is_finding_alive(state: StateModel, finding_id: str) -> bool:
    """Return True if the finding exists and is open."""
    finding = state.get("findings", {}).get(finding_id)
    if finding is None:
        return False
    return finding.get("status") == "open"


def _supersede_id(
    plan: PlanModel,
    state: StateModel,
    finding_id: str,
    now: str,
) -> bool:
    """Move a disappeared finding to superseded. Returns True if changed."""
    finding = state.get("findings", {}).get(finding_id)
    detector = ""
    file = ""
    summary = ""
    if finding:
        detector = finding.get("detector", "")
        file = finding.get("file", "")
        summary = finding.get("summary", "")

    candidates = _find_candidates(state, detector, file) if detector else []
    # Don't include the original in candidates
    candidates = [c for c in candidates if c != finding_id]

    entry: SupersededEntry = {
        "original_id": finding_id,
        "original_detector": detector,
        "original_file": file,
        "original_summary": summary,
        "status": "superseded",
        "superseded_at": now,
        "remapped_to": None,
        "candidates": candidates[:5],
    }

    # Preserve any existing override note
    override = plan.get("overrides", {}).get(finding_id)
    if override and override.get("note"):
        entry["note"] = override["note"]

    plan["superseded"][finding_id] = entry

    # Remove from queue_order, skipped, cluster finding_ids
    order: list[str] = plan.get("queue_order", [])
    skipped: dict = plan.get("skipped", {})
    if finding_id in order:
        order.remove(finding_id)
    skipped.pop(finding_id, None)
    for cluster in plan.get("clusters", {}).values():
        ids = cluster.get("finding_ids", [])
        if finding_id in ids:
            ids.remove(finding_id)

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

    # Collect all finding IDs referenced by the plan
    referenced_ids: set[str] = set()
    referenced_ids.update(plan.get("queue_order", []))
    referenced_ids.update(plan.get("skipped", {}).keys())
    for override_id in plan.get("overrides", {}):
        referenced_ids.add(override_id)
    for cluster in plan.get("clusters", {}).values():
        referenced_ids.update(cluster.get("finding_ids", []))

    # Exclude already-superseded IDs and synthetic IDs (managed by stale_dimensions)
    already_superseded = set(plan.get("superseded", {}).keys())
    referenced_ids -= already_superseded
    referenced_ids = {
        fid for fid in referenced_ids
        if not fid.startswith(SUBJECTIVE_PREFIX)
    }

    # Check each referenced ID
    for fid in sorted(referenced_ids):
        if not _is_finding_alive(state, fid):
            if _supersede_id(plan, state, fid, now):
                result.superseded.append(fid)
                result.changes += 1

    # Resurface stale temporary skips
    scan_count = state.get("scan_count", 0)
    from desloppify.engine._plan.operations import resurface_stale_skips

    resurfaced = resurface_stale_skips(plan, scan_count)
    if resurfaced:
        result.resurfaced = resurfaced
        result.changes += len(resurfaced)

    # Prune old superseded entries
    pruned = _prune_old_superseded(plan, now_dt)
    result.pruned = pruned
    result.changes += len(pruned)

    return result


__all__ = [
    "ReconcileResult",
    "reconcile_plan_after_scan",
]
