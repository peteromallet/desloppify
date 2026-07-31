"""Dismissal helpers for cluster triage plan mutations."""

from __future__ import annotations

from .prompt import TriageResult


def _triaged_out_payload(
    *,
    issue_id: str,
    reason: str,
    note: str | None,
    now: str,
    scan_count: int,
) -> dict:
    return {
        "issue_id": issue_id,
        "kind": "triaged_out",
        "reason": reason,
        "note": note,
        "attestation": None,
        "created_at": now,
        "review_after": None,
        "skipped_at_scan": scan_count,
    }


def dismiss_triage_issues(
    *,
    triage: TriageResult,
    order: list[str],
    skipped: dict,
    now: str,
    version: int,
    scan_count: int,
    protected_issue_ids: set[str] | None = None,
) -> tuple[list[str], int]:
    """Move triage-dismissed issues out of queue and into skipped metadata."""
    protected_ids = protected_issue_ids or set()
    dismissed_ids: list[str] = []
    dismiss_count = 0
    for dismissed in triage.dismissed_issues:
        issue_id = dismissed.issue_id
        if issue_id in protected_ids:
            continue
        dismissed_ids.append(issue_id)
        if issue_id in order:
            order.remove(issue_id)
        skipped[issue_id] = _triaged_out_payload(
            issue_id=issue_id,
            reason=dismissed.reason,
            note=f"Dismissed by epic triage v{version}",
            now=now,
            scan_count=scan_count,
        )
        dismiss_count += 1

    for epic_data in triage.clusters:
        for issue_id in epic_data.get("dismissed", []):
            if issue_id in protected_ids or issue_id in dismissed_ids or issue_id not in order:
                continue
            order.remove(issue_id)
            dismissed_ids.append(issue_id)
            skipped[issue_id] = _triaged_out_payload(
                issue_id=issue_id,
                reason=f"Dismissed by epic triage v{version}",
                note=None,
                now=now,
                scan_count=scan_count,
            )
            dismiss_count += 1

    return dismissed_ids, dismiss_count


__all__ = ["dismiss_triage_issues"]
