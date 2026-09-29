"""Trusted assessment coverage for the current review/triage cycle."""

from __future__ import annotations


def same_cycle_assessment_coverage(
    state: dict,
    plan: dict | None,
    *,
    review_completed_this_scan: bool,
) -> tuple[dict[str, set[str]], str]:
    """Return covered dimension revisions and a conservative legacy fallback.

    Each partial import covers its own assessment timestamps. A later import
    for another dimension must not expire that coverage. A completed postflight
    scan does expire it, so resolving review findings cannot hide the next review.

    Older audits lack dimension metadata. Their matching review-import log
    entries supply coverage; without a matching log, retain only the existing
    newest-audit fallback rather than trusting the whole historical audit list.
    """
    all_audits = [
        entry
        for entry in state.get("assessment_import_audit", []) or []
        if isinstance(entry, dict)
        and isinstance(entry.get("timestamp"), str)
        and entry["timestamp"].strip()
    ]
    audits = [
        entry
        for entry in all_audits
        if entry.get("mode") in {"trusted_internal", "attested_external"}
        and entry.get("trusted") is not False
    ]
    if not audits:
        return {}, ""
    log = (plan or {}).get("execution_log", []) or []
    boundary = max(
        (
            entry["timestamp"]
            for entry in log
            if isinstance(entry, dict)
            and entry.get("action") == "complete_postflight_scan"
            and isinstance(entry.get("timestamp"), str)
        ),
        default="",
    )
    # Review imports also call merge_scan. Exclude those history entries when
    # locating the last real scan, including untrusted/manual review imports.
    import_scans = {
        entry.get("scan_timestamp") or entry["timestamp"]
        for entry in all_audits
        if isinstance(entry.get("scan_timestamp", ""), str)
    }
    for entry in log:
        if not isinstance(entry, dict) or entry.get("action") != "review_import_sync":
            continue
        detail = entry.get("detail")
        timestamp = detail.get("scan_timestamp") if isinstance(detail, dict) else None
        if not timestamp:
            timestamp = entry.get("timestamp")
        if isinstance(timestamp, str):
            import_scans.add(timestamp)
    for entry in state.get("scan_history", []) or []:
        if not isinstance(entry, dict):
            continue
        timestamp = entry.get("timestamp")
        if isinstance(timestamp, str) and timestamp not in import_scans:
            boundary = max(boundary, timestamp)
    latest_audit = max(audits, key=lambda entry: entry["timestamp"])
    last_scan = state.get("last_scan")
    if (
        isinstance(last_scan, str)
        and last_scan > latest_audit["timestamp"]
        and not review_completed_this_scan
    ):
        # A new scan also expires coverage before its postflight log is appended.
        boundary = max(boundary, last_scan)

    covered: dict[str, set[str]] = {}
    legacy_timestamps: set[str] = set()
    for entry in audits:
        timestamp = entry["timestamp"].strip()
        if timestamp <= boundary:
            continue
        revisions = entry.get("assessment_timestamps")
        if not isinstance(revisions, dict):
            legacy_timestamps.add(timestamp)
            continue
        for dimension, assessed_at in revisions.items():
            if (
                isinstance(dimension, str)
                and isinstance(assessed_at, str)
                and assessed_at.strip() > boundary
            ):
                covered.setdefault(dimension, set()).add(assessed_at.strip())

    for entry in log:
        if not isinstance(entry, dict) or entry.get("action") != "review_import_sync":
            continue
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str) or timestamp not in legacy_timestamps:
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict):
            continue
        dimensions = detail.get("covered_subjective")
        if not isinstance(dimensions, list):
            continue
        for item_id in dimensions:
            if isinstance(item_id, str) and item_id.startswith("subjective::"):
                covered.setdefault(item_id.removeprefix("subjective::"), set()).add(
                    timestamp
                )

    latest_timestamp = latest_audit["timestamp"].strip()
    legacy_latest = latest_timestamp if latest_timestamp in legacy_timestamps else ""
    return covered, legacy_latest
