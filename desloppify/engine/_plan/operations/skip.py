"""Skip/unskip mutations for plan operations."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.engine._plan.operations.lifecycle import clear_focus_if_cluster_empty
from desloppify.engine._plan.operations.queue import _remove_id_from_lists
from desloppify.engine._plan.promoted_ids import prune_promoted_ids
from desloppify.engine._plan.schema import PlanModel, SkipEntry, ensure_plan_defaults
from desloppify.engine._plan.skip_policy import skip_kind_needs_state_reopen
from desloppify.engine._plan.triage.protection import (
    clear_protected_triage_artifacts,
    protected_review_issue_ids,
)
from desloppify.engine._state.schema import utc_now


@dataclass(frozen=True)
class SkipOptions:
    """Optional fields used when skipping issue IDs."""

    kind: str = "temporary"
    reason: str | None = None
    note: str | None = None
    attestation: str | None = None
    review_after: int | None = None
    scan_count: int = 0


def _skip_options(
    *,
    options: SkipOptions | None,
    legacy_kwargs: dict[str, object],
) -> SkipOptions:
    """Resolve skip options from a config object or legacy kwargs."""
    allowed_keys = {
        "kind",
        "reason",
        "note",
        "attestation",
        "review_after",
        "scan_count",
    }
    unknown = sorted(set(legacy_kwargs) - allowed_keys)
    if unknown:
        joined = ", ".join(unknown)
        raise TypeError(f"Unexpected keyword argument(s): {joined}")
    if options is not None and legacy_kwargs:
        raise TypeError("Pass either options=... or legacy keyword args, not both")
    if options is not None:
        return options
    kind = legacy_kwargs.get("kind")
    reason = legacy_kwargs.get("reason")
    note = legacy_kwargs.get("note")
    attestation = legacy_kwargs.get("attestation")
    review_after = legacy_kwargs.get("review_after")
    scan_count = legacy_kwargs.get("scan_count")
    return SkipOptions(
        kind=str(kind) if kind is not None else "temporary",
        reason=None if reason is None else str(reason),
        note=None if note is None else str(note),
        attestation=None if attestation is None else str(attestation),
        review_after=int(review_after) if isinstance(review_after, int) else None,
        scan_count=int(scan_count) if isinstance(scan_count, int) else 0,
    )


def skip_items(
    plan: PlanModel,
    issue_ids: list[str],
    *,
    options: SkipOptions | None = None,
    **legacy_kwargs,
) -> int:
    """Move issue IDs to the skipped dict. Returns count skipped."""
    skip_options = _skip_options(
        options=options,
        legacy_kwargs=legacy_kwargs,
    )
    ensure_plan_defaults(plan)
    clear_protected_triage_artifacts(plan)
    protected_ids = protected_review_issue_ids(plan)
    issue_ids = [issue_id for issue_id in issue_ids if issue_id not in protected_ids]
    now = utc_now()
    count = 0
    skipped: dict[str, SkipEntry] = plan["skipped"]
    skip_set = set(issue_ids)
    prune_promoted_ids(plan, skip_set)
    for fid in issue_ids:
        _remove_id_from_lists(plan, fid)
        skipped[fid] = {
            "issue_id": fid,
            "kind": skip_options.kind,
            "reason": skip_options.reason,
            "note": skip_options.note,
            "attestation": skip_options.attestation,
            "created_at": now,
            "review_after": skip_options.review_after,
            "skipped_at_scan": skip_options.scan_count,
        }
        count += 1
    clear_focus_if_cluster_empty(plan)
    return count


def _is_protected_skip(entry: SkipEntry) -> bool:
    """A skip is protected if it was permanent/false_positive AND has a note.

    Protected skips represent deliberate human judgment and should not be
    silently undone by bulk unskip operations.
    """
    kind = str(entry.get("kind", ""))
    has_note = bool(entry.get("note", ""))
    return kind in ("permanent", "false_positive") and has_note


def unskip_items(
    plan: PlanModel,
    issue_ids: list[str],
    *,
    include_protected: bool = False,
) -> tuple[int, list[str], list[str]]:
    """Bring issue IDs back from skipped to the end of queue_order.

    Returns ``(count_unskipped, permanent_ids_needing_state_reopen, protected_ids_kept)``
    where the second list contains IDs that were permanent or false_positive
    and need their state-layer status reopened by the caller, and the third
    list contains protected IDs that were NOT unskipped (unless
    ``include_protected=True``).
    """
    ensure_plan_defaults(plan)
    clear_protected_triage_artifacts(plan)
    protected_ids = protected_review_issue_ids(plan)
    count = 0
    need_reopen: list[str] = []
    protected_kept: list[str] = []
    skipped: dict[str, SkipEntry] = plan["skipped"]
    for fid in issue_ids:
        if fid in protected_ids:
            protected_kept.append(fid)
            continue
        entry = skipped.get(fid)
        if entry is None:
            continue
        if not include_protected and _is_protected_skip(entry):
            protected_kept.append(fid)
            continue
        skipped.pop(fid)
        if skip_kind_needs_state_reopen(str(entry.get("kind", ""))):
            need_reopen.append(fid)
        if fid not in plan["queue_order"]:
            plan["queue_order"].append(fid)
        count += 1
    return count, need_reopen, protected_kept


def resurface_stale_skips(
    plan: PlanModel, current_scan_count: int
) -> list[str]:
    """Move temporary skips past their review_after threshold back to queue.

    Returns list of resurfaced issue IDs.
    """
    ensure_plan_defaults(plan)
    clear_protected_triage_artifacts(plan)
    protected_ids = protected_review_issue_ids(plan)
    skipped: dict[str, SkipEntry] = plan["skipped"]
    resurfaced: list[str] = []
    for fid in list(skipped):
        if fid in protected_ids:
            continue
        entry = skipped[fid]
        if entry.get("kind") != "temporary":
            continue
        review_after = entry.get("review_after")
        if review_after is None:
            continue
        skipped_at = entry.get("skipped_at_scan", 0)
        if current_scan_count >= skipped_at + review_after:
            skipped.pop(fid)
            if fid not in plan["queue_order"]:
                plan["queue_order"].append(fid)
            resurfaced.append(fid)
    return resurfaced


def backlog_items(plan: PlanModel, issue_ids: list[str]) -> list[str]:
    """Remove from plan.skipped without adding to queue_order.

    Issues stay open in state but are no longer plan-tracked.
    Returns the IDs that were actually removed.
    """
    ensure_plan_defaults(plan)
    clear_protected_triage_artifacts(plan)
    removed: list[str] = []
    for fid in issue_ids:
        if fid in plan["skipped"]:
            plan["skipped"].pop(fid)
            removed.append(fid)
    return removed


__all__ = ["backlog_items", "resurface_stale_skips", "skip_items", "unskip_items"]
