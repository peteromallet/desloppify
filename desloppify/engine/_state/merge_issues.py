"""Issue upsert/verification helpers for scan merge."""

from __future__ import annotations

import os

from desloppify.base.discovery.file_paths import matches_exclusion
from desloppify.engine._state.filtering import matched_ignore_pattern
from desloppify.engine._state.issue_semantics import (
    is_import_only_issue,
    is_assessment_request,
)


def find_suspect_detectors(
    existing: dict,
    current_by_detector: dict[str, int],
    force_resolve: bool,
    ran_detectors: set[str] | None = None,
) -> set[str]:
    """Detectors that had open issues but likely did not actually run this scan."""
    if force_resolve:
        return set()

    previous_open_by_detector: dict[str, int] = {}
    for issue in existing.values():
        if issue["status"] != "open":
            continue
        detector = issue.get("detector", "unknown")
        previous_open_by_detector[detector] = (
            previous_open_by_detector.get(detector, 0) + 1
        )

    suspect: set[str] = {
        str(issue.get("detector", "unknown"))
        for issue in existing.values()
        if isinstance(issue, dict) and is_import_only_issue(issue)
    }

    for detector, previous_count in previous_open_by_detector.items():
        if detector in suspect:
            continue
        if current_by_detector.get(detector, 0) > 0:
            continue
        if ran_detectors is not None:
            if detector not in ran_detectors:
                suspect.add(detector)
            continue
        if previous_count >= 3:
            suspect.add(detector)

    return suspect


def _mark_scan_verified(
    issue: dict,
    now: str,
    *,
    note: str,
    attestation_text: str,
) -> None:
    """Record scan corroboration without changing the manual disposition."""
    issue["suppressed"] = False
    issue["suppressed_at"] = None
    issue["suppression_pattern"] = None
    issue["note"] = note
    existing = issue.get("resolution_attestation")
    if not isinstance(existing, dict):
        existing = {}
        issue["resolution_attestation"] = existing
    existing["scan_verified"] = True
    existing["scan_verified_at"] = now
    existing["scan_verification_text"] = attestation_text


def verify_disappeared(
    existing: dict,
    current_ids: set[str],
    suspect_detectors: set[str],
    now: str,
    *,
    lang: str | None,
    scan_path: str | None,
    exclude: tuple[str, ...] = (),
    project_root: str | None = None,
) -> tuple[int, int, int, set[str]]:
    """Update scan corroboration for issues absent from scan.

    Returns (resolved_count, skipped_other_lang, resolved_out_of_scope, changed_detectors).
    Queue-tracked work stays user-controlled: disappearing from scan does not
    change an open issue to resolved — *unless* the source file no longer exists
    on disk, in which case the issue is auto-resolved.  Manually resolved items
    can be marked as scan-verified when they remain absent.
    """
    resolved = skipped_other_lang = resolved_out_of_scope = 0
    resolved_detectors: set[str] = set()

    for issue_id, previous in existing.items():
        previous_status = previous.get("status")
        if issue_id in current_ids or previous_status not in (
            "open",
            "wontfix",
            "fixed",
            "false_positive",
        ):
            continue

        if lang and previous.get("lang") and previous["lang"] != lang:
            skipped_other_lang += 1
            continue

        # Suspect detectors (e.g. 'review') are import-only and must never
        # be auto-resolved by a scan — check this BEFORE the scope filter
        # so that review issues with file="." aren't wrongly resolved as
        # "out of current scan scope".
        if previous.get("detector", "unknown") in suspect_detectors:
            continue

        if scan_path and scan_path != ".":
            prefix = scan_path.rstrip("/") + "/"
            if (
                not previous["file"].startswith(prefix)
                and previous["file"] != scan_path
            ):
                if previous_status != "open":
                    scope_note = f"Still absent in current scan scope ({scan_path})"
                    _mark_scan_verified(
                        previous,
                        now,
                        note=scope_note,
                        attestation_text=scope_note,
                    )
                    resolved_detectors.add(previous.get("detector", "unknown"))
                    resolved_out_of_scope += 1
                continue

        if exclude and any(matches_exclusion(previous["file"], ex) for ex in exclude):
            continue

        if previous_status == "open":
            # If the source file no longer exists on disk, auto-resolve:
            # the issue cannot be actionable for a deleted file.
            file_path = previous.get("file", "")
            file_deleted = False
            if project_root and file_path and file_path != ".":
                file_deleted = not os.path.exists(
                    os.path.join(project_root, file_path)
                )
            if not file_deleted:
                continue
            previous["status"] = "auto_resolved"
            previous["resolved_at"] = now
            previous["note"] = "Auto-resolved: source file no longer exists"
            resolved_detectors.add(previous.get("detector", "unknown"))
            resolved += 1
            continue

        # Wontfix items from clippy/cargo that disappeared after inline-test
        # filtering was introduced should be auto-resolved: the filter now
        # correctly excludes test-only diagnostics, so the wontfix decision
        # is obsolete.
        if previous_status == "wontfix" and previous.get("detector", "") in (
            "clippy_warning",
            "cargo_error",
        ):
            previous["status"] = "auto_resolved"
            previous["resolved_at"] = now
            previous["note"] = (
                "Auto-resolved: absent from scan after inline cfg(test) "
                "filtering was introduced"
            )
            resolved_detectors.add(previous.get("detector", "unknown"))
            resolved += 1
            continue

        verification_note = (
            "Still absent from scan after manual wontfix"
            if previous_status == "wontfix"
            else "Still absent from scan after manual resolution"
        )
        _mark_scan_verified(
            previous,
            now,
            note=verification_note,
            attestation_text="Absent from detector output in latest scan",
        )
        resolved_detectors.add(previous.get("detector", "unknown"))
        resolved += 1

    return resolved, skipped_other_lang, resolved_out_of_scope, resolved_detectors


def upsert_issues(
    existing: dict,
    current_issues: list[dict],
    ignore: list[str],
    now: str,
    *,
    lang: str | None,
) -> tuple[set[str], int, int, dict[str, int], int, set[str]]:
    """Insert new issues and update existing ones.

    Returns (current_ids, new_count, reopened_count, by_detector, ignored_count, changed_detectors).
    """
    current_ids: set[str] = set()
    new_count = reopened_count = ignored_count = 0
    by_detector: dict[str, int] = {}
    changed_detectors: set[str] = set()

    for issue in current_issues:
        issue_id = issue["id"]
        detector = issue.get("detector", "unknown")
        current_ids.add(issue_id)
        by_detector[detector] = by_detector.get(detector, 0) + 1
        matched_ignore = matched_ignore_pattern(issue_id, issue["file"], ignore)
        if matched_ignore:
            ignored_count += 1

        if lang:
            issue["lang"] = lang

        if issue_id not in existing:
            existing[issue_id] = dict(issue)
            if matched_ignore:
                existing[issue_id]["suppressed"] = True
                existing[issue_id]["suppressed_at"] = now
                existing[issue_id]["suppression_pattern"] = matched_ignore
                continue
            new_count += 1
            changed_detectors.add(detector)
            continue

        previous = existing[issue_id]
        previous.update(
            last_seen=now,
            tier=issue["tier"],
            confidence=issue["confidence"],
            summary=issue["summary"],
            detail=issue.get("detail", {}),
        )
        if "zone" in issue:
            previous["zone"] = issue["zone"]
        if lang and not previous.get("lang"):
            previous["lang"] = lang

        if matched_ignore:
            previous["suppressed"] = True
            previous["suppressed_at"] = now
            previous["suppression_pattern"] = matched_ignore
            continue

        previous["suppressed"] = False
        previous["suppressed_at"] = None
        previous["suppression_pattern"] = None

        if previous["status"] in ("fixed", "auto_resolved", "false_positive"):
            # Review-request issues are condition-based. When just
            # completed by an agent import, skip reopening to avoid a
            # resolve-then-reopen loop on the same scan cycle.
            if (
                is_assessment_request(previous)
                and previous["status"] in {"fixed", "auto_resolved"}
                and (previous.get("resolution_attestation") or {}).get("kind") == "agent_import"
            ):
                continue
            previous_status = previous["status"]
            previous["reopen_count"] = previous.get("reopen_count", 0) + 1
            previous.pop("resolution_attestation", None)
            previous.update(
                status="open",
                resolved_at=None,
                note=(
                    f"Reopened (×{previous['reopen_count']}) "
                    f"— reappeared in scan (was {previous_status})"
                ),
            )
            reopened_count += 1
            changed_detectors.add(detector)

    return current_ids, new_count, reopened_count, by_detector, ignored_count, changed_detectors


__all__ = [
    "verify_disappeared",
    "find_suspect_detectors",
    "upsert_issues",
]
