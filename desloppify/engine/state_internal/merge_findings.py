"""Finding upsert/auto-resolve helpers for scan merge."""

from __future__ import annotations

from desloppify.engine.state_internal.filtering import matched_ignore_pattern
from desloppify.utils import matches_exclusion


def find_suspect_detectors(
    existing: dict,
    current_by_detector: dict[str, int],
    force_resolve: bool,
    ran_detectors: set[str] | None = None,
) -> set[str]:
    """Detectors that had open findings but likely did not actually run this scan."""
    if force_resolve:
        return set()

    previous_open_by_detector: dict[str, int] = {}
    for finding in existing.values():
        if finding["status"] != "open":
            continue
        detector = finding.get("detector", "unknown")
        previous_open_by_detector[detector] = (
            previous_open_by_detector.get(detector, 0) + 1
        )

    # 'review' findings enter via `desloppify review --import`, not via scan phases.
    # They are always marked suspect so the scan never auto-resolves them.
    import_only_detectors = {"review"}
    suspect: set[str] = set()

    for detector, previous_count in previous_open_by_detector.items():
        if detector in import_only_detectors:
            suspect.add(detector)
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


def _auto_resolve_disappeared(
    existing: dict,
    current_ids: set[str],
    suspect_detectors: set[str],
    now: str,
    *,
    lang: str | None,
    scan_path: str | None,
    exclude: tuple[str, ...] = (),
) -> tuple[int, int, int]:
    """Auto-resolve open/wontfix findings absent from scan.

    Returns (resolved, skipped_other_lang, skipped_out_of_scope).
    """
    resolved = skipped_other_lang = skipped_out_of_scope = 0

    for finding_id, previous in existing.items():
        if finding_id in current_ids or previous["status"] not in (
            "open",
            "wontfix",
            "fixed",
            "false_positive",
        ):
            continue

        if lang and previous.get("lang") and previous["lang"] != lang:
            skipped_other_lang += 1
            continue

        if scan_path and scan_path != ".":
            prefix = scan_path.rstrip("/") + "/"
            if (
                not previous["file"].startswith(prefix)
                and previous["file"] != scan_path
            ):
                skipped_out_of_scope += 1
                continue

        if exclude and any(matches_exclusion(previous["file"], ex) for ex in exclude):
            continue

        if previous.get("detector", "unknown") in suspect_detectors:
            continue

        previous_status = previous["status"]
        previous["status"] = "auto_resolved"
        previous["resolved_at"] = now
        previous["suppressed"] = False
        previous["suppressed_at"] = None
        previous["suppression_pattern"] = None
        previous["resolution_attestation"] = {
            "kind": "scan_verified",
            "text": "Disappeared from detector output",
            "attested_at": now,
            "scan_verified": True,
        }
        previous["note"] = (
            "Fixed despite wontfix — disappeared from scan (was wontfix)"
            if previous_status == "wontfix"
            else "Disappeared from scan — likely fixed"
        )
        resolved += 1

    return resolved, skipped_other_lang, skipped_out_of_scope


def upsert_findings(
    existing: dict,
    current_findings: list[dict],
    ignore: list[str],
    now: str,
    *,
    lang: str | None,
) -> tuple[set[str], int, int, dict[str, int], int]:
    """Insert new findings and update existing ones.

    Returns (current_ids, new_count, reopened_count, by_detector, ignored_count).
    """
    current_ids: set[str] = set()
    new_count = reopened_count = ignored_count = 0
    by_detector: dict[str, int] = {}

    for finding in current_findings:
        finding_id = finding["id"]
        detector = finding.get("detector", "unknown")
        current_ids.add(finding_id)
        by_detector[detector] = by_detector.get(detector, 0) + 1
        matched_ignore = matched_ignore_pattern(finding_id, finding["file"], ignore)
        if matched_ignore:
            ignored_count += 1

        if lang:
            finding["lang"] = lang

        if finding_id not in existing:
            existing[finding_id] = dict(finding)
            if matched_ignore:
                existing[finding_id]["suppressed"] = True
                existing[finding_id]["suppressed_at"] = now
                existing[finding_id]["suppression_pattern"] = matched_ignore
                continue
            new_count += 1
            continue

        previous = existing[finding_id]
        previous.update(
            last_seen=now,
            tier=finding["tier"],
            confidence=finding["confidence"],
            summary=finding["summary"],
            detail=finding.get("detail", {}),
        )
        if "zone" in finding:
            previous["zone"] = finding["zone"]
        if lang and not previous.get("lang"):
            previous["lang"] = lang

        if matched_ignore:
            previous["suppressed"] = True
            previous["suppressed_at"] = now
            previous["suppression_pattern"] = matched_ignore
            if previous["status"] in ("fixed", "auto_resolved", "false_positive"):
                previous["status"] = "open"
                previous["resolved_at"] = None
                previous["note"] = (
                    "Suppressed by ignore pattern — remains unresolved for score integrity"
                )
            continue

        previous["suppressed"] = False
        previous["suppressed_at"] = None
        previous["suppression_pattern"] = None

        if previous["status"] in ("fixed", "auto_resolved"):
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

    return current_ids, new_count, reopened_count, by_detector, ignored_count


__all__ = [
    "_auto_resolve_disappeared",
    "find_suspect_detectors",
    "upsert_findings",
]
