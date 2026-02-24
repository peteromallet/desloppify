"""Holistic review finding import workflow."""

from __future__ import annotations

import hashlib
from typing import Any

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.importing.shared import (
    _lang_potentials,
    _review_file_cache,
    extract_reviewed_files,
    store_assessments,
)
from desloppify.intelligence.review.selection import hash_file
from desloppify.scoring import HOLISTIC_POTENTIAL
from desloppify.state import MergeScanOptions, make_finding, merge_scan, utc_now


def parse_holistic_import_payload(
    data: dict,
) -> tuple[list[dict], dict | None, list[str]]:
    """Parse strict holistic import payload object."""
    if not isinstance(data, dict):
        raise ValueError("Holistic review import payload must be a JSON object")

    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Holistic review import payload 'findings' must be a list")

    assessments = data.get("assessments")
    if assessments is not None and not isinstance(assessments, dict):
        raise ValueError(
            "Holistic review import payload 'assessments' must be an object"
        )
    reviewed_files = extract_reviewed_files(data)
    return findings, assessments, reviewed_files


def update_reviewed_file_cache(
    state: dict[str, Any],
    reviewed_files: list[str],
    *,
    project_root=None,
    utc_now_fn=utc_now,
) -> None:
    """Refresh per-file review cache entries from holistic payload metadata."""
    if not reviewed_files:
        return
    file_cache = _review_file_cache(state)
    now = utc_now_fn()
    resolved_project_root = project_root if project_root is not None else PROJECT_ROOT
    for file_path in reviewed_files:
        absolute = resolved_project_root / file_path
        content_hash = hash_file(str(absolute)) if absolute.exists() else ""
        previous = file_cache.get(file_path, {})
        existing_count = (
            previous.get("finding_count", 0) if isinstance(previous, dict) else 0
        )
        file_cache[file_path] = {
            "content_hash": content_hash,
            "reviewed_at": now,
            "finding_count": existing_count if isinstance(existing_count, int) else 0,
        }


_POSITIVE_PREFIXES = (
    "good ",
    "well ",
    "strong ",
    "clean ",
    "excellent ",
    "nice ",
    "solid ",
)


def _validate_and_build_findings(
    findings_list: list[dict],
    holistic_prompts: dict,
    lang_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate raw holistic findings and build state-ready finding dicts.

    Returns (review_findings, skipped, dismissed_concerns).
    """
    required = ("dimension", "identifier", "summary", "confidence", "suggestion")
    review_findings: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    dismissed_concerns: list[dict[str, Any]] = []

    for idx, finding in enumerate(findings_list):
        # Handle dismissed concern verdicts (no dimension/summary required).
        if finding.get("concern_verdict") == "dismissed":
            fp = finding.get("concern_fingerprint", "")
            if fp:
                dismissed_concerns.append(
                    {
                        "fingerprint": fp,
                        "concern_type": finding.get("concern_type", ""),
                        "concern_file": finding.get("concern_file", ""),
                        "reasoning": finding.get("reasoning", ""),
                    }
                )
            continue

        missing = [key for key in required if key not in finding]
        if missing:
            skipped.append(
                {
                    "index": idx,
                    "missing": missing,
                    "identifier": finding.get("identifier", "<none>"),
                }
            )
            continue

        # Safety net: skip positive observations that slipped past the prompt.
        if finding["summary"].lower().startswith(_POSITIVE_PREFIXES):
            skipped.append(
                {
                    "index": idx,
                    "missing": ["positive observation (not a defect)"],
                    "identifier": finding.get("identifier", "<none>"),
                }
            )
            continue

        confidence = finding.get("confidence", "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        dimension = finding["dimension"]
        if dimension not in holistic_prompts:
            skipped.append(
                {
                    "index": idx,
                    "missing": [f"invalid dimension: {dimension}"],
                    "identifier": finding.get("identifier", "<none>"),
                }
            )
            continue

        # Confirmed concern verdicts become "concerns" detector findings.
        is_confirmed_concern = finding.get("concern_verdict") == "confirmed"
        detector = "concerns" if is_confirmed_concern else "review"

        content_hash = hashlib.sha256(finding["summary"].encode()).hexdigest()[:8]
        detail: dict[str, Any] = {
            "holistic": True,
            "dimension": dimension,
            "related_files": finding.get("related_files", []),
            "evidence": finding.get("evidence", []),
            "suggestion": finding.get("suggestion", ""),
            "reasoning": finding.get("reasoning", ""),
        }
        if is_confirmed_concern:
            detail["concern_type"] = finding.get("concern_type", "")
            detail["concern_verdict"] = "confirmed"

        prefix = "concern" if is_confirmed_concern else "holistic"
        file = finding.get("concern_file", "") if is_confirmed_concern else ""
        imported = make_finding(
            detector=detector,
            file=file,
            name=f"{prefix}::{dimension}::{finding['identifier']}::{content_hash}",
            tier=3,
            confidence=confidence,
            summary=finding["summary"],
            detail=detail,
        )
        imported["lang"] = lang_name
        review_findings.append(imported)

    return review_findings, skipped, dismissed_concerns


def _auto_resolve_stale_holistic(
    state: dict[str, Any],
    new_ids: set[str],
    diff: dict[str, Any],
    utc_now_fn,
) -> None:
    """Auto-resolve open holistic findings not present in the latest import."""
    diff.setdefault("auto_resolved", 0)
    for finding_id, finding in state.get("findings", {}).items():
        if (
            finding["status"] == "open"
            and finding.get("detector") in ("review", "concerns")
            and finding.get("detail", {}).get("holistic")
            and finding_id not in new_ids
        ):
            finding["status"] = "auto_resolved"
            finding["resolved_at"] = utc_now_fn()
            finding["note"] = "not reported in latest holistic re-import"
            diff["auto_resolved"] += 1


def import_holistic_findings(
    findings_data: dict,
    state: dict[str, Any],
    lang_name: str,
    *,
    project_root=None,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Import holistic (codebase-wide) findings into state."""
    findings_list, assessments, reviewed_files = parse_holistic_import_payload(
        findings_data
    )
    review_scope = (
        findings_data.get("review_scope", {})
        if isinstance(findings_data, dict)
        else {}
    )
    if not isinstance(review_scope, dict):
        review_scope = {}
    if assessments:
        store_assessments(
            state,
            assessments,
            source="holistic",
            utc_now_fn=utc_now_fn,
        )

    _, holistic_prompts, _ = load_dimensions_for_lang(lang_name)
    review_findings, skipped, dismissed_concerns = _validate_and_build_findings(
        findings_list, holistic_prompts, lang_name
    )

    # Store dismissed concern verdicts for suppression in future concern generation.
    if dismissed_concerns:
        from desloppify.engine.concerns import generate_concerns

        store = state.setdefault("concern_dismissals", {})
        now = utc_now_fn()
        # Compute current concerns to get source_finding_ids for each fingerprint.
        current_concerns = generate_concerns(state, lang_name=lang_name)
        concern_sources = {
            c.fingerprint: list(c.source_findings) for c in current_concerns
        }
        for dc in dismissed_concerns:
            fp = dc["fingerprint"]
            store[fp] = {
                "dismissed_at": now,
                "reasoning": dc.get("reasoning", ""),
                "concern_type": dc.get("concern_type", ""),
                "concern_file": dc.get("concern_file", ""),
                "source_finding_ids": concern_sources.get(fp, []),
            }

    potentials = _lang_potentials(state, lang_name)
    existing_review = potentials.get("review", 0)
    potentials["review"] = max(existing_review, HOLISTIC_POTENTIAL)

    concern_count = sum(1 for f in review_findings if f.get("detector") == "concerns")
    if concern_count:
        potentials["concerns"] = max(potentials.get("concerns", 0), concern_count)

    merge_potentials_dict: dict[str, int] = {"review": potentials.get("review", 0)}
    if potentials.get("concerns", 0) > 0:
        merge_potentials_dict["concerns"] = potentials["concerns"]

    diff = merge_scan(
        state,
        review_findings,
        options=MergeScanOptions(
            lang=lang_name,
            potentials=merge_potentials_dict,
            merge_potentials=True,
        ),
    )

    new_ids = {finding["id"] for finding in review_findings}
    _auto_resolve_stale_holistic(state, new_ids, diff, utc_now_fn)

    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped

    update_reviewed_file_cache(
        state,
        reviewed_files,
        project_root=project_root,
        utc_now_fn=utc_now_fn,
    )
    resolve_reviewed_file_coverage_findings(
        state,
        diff,
        reviewed_files,
        utc_now_fn=utc_now_fn,
    )
    update_holistic_review_cache(
        state,
        findings_list,
        lang_name=lang_name,
        review_scope=review_scope,
        utc_now_fn=utc_now_fn,
    )
    resolve_holistic_coverage_findings(state, diff, utc_now_fn=utc_now_fn)

    # Clean up dismissals whose source findings were all resolved — runs after
    # all finding mutations (merge_scan, auto_resolve, coverage resolve) so it
    # sees the final state.
    from desloppify.engine.concerns import cleanup_stale_dismissals

    cleanup_stale_dismissals(state)

    return diff


def _resolve_total_files(state: dict[str, Any], lang_name: str | None) -> int:
    """Best-effort total file count from codebase_metrics or review cache."""
    review_cache = state.get("review_cache", {})
    fallback = len(review_cache.get("files", {}))

    codebase_metrics = state.get("codebase_metrics", {})
    if not isinstance(codebase_metrics, dict):
        return fallback

    # Try language-specific metrics first, then global.
    sources = []
    if lang_name:
        lang_metrics = codebase_metrics.get(lang_name)
        if isinstance(lang_metrics, dict):
            sources.append(lang_metrics)
    sources.append(codebase_metrics)

    for source in sources:
        metric_total = source.get("total_files")
        if isinstance(metric_total, int) and metric_total > 0:
            return metric_total

    return fallback


def update_holistic_review_cache(
    state: dict[str, Any],
    findings_data: list[dict],
    *,
    lang_name: str | None = None,
    review_scope: dict[str, Any] | None = None,
    utc_now_fn=utc_now,
) -> None:
    """Store holistic review metadata in review_cache."""
    review_cache = state.setdefault("review_cache", {})
    now = utc_now_fn()
    _, holistic_prompts, _ = load_dimensions_for_lang(lang_name or "")

    valid = [
        finding
        for finding in findings_data
        if all(
            key in finding
            for key in ("dimension", "identifier", "summary", "confidence")
        )
        and finding["dimension"] in holistic_prompts
    ]

    resolved_total_files: int
    total_override = (
        review_scope.get("total_files")
        if isinstance(review_scope, dict)
        else None
    )
    if (
        isinstance(total_override, int)
        and not isinstance(total_override, bool)
        and total_override > 0
    ):
        resolved_total_files = total_override
    else:
        resolved_total_files = _resolve_total_files(state, lang_name)

    holistic_entry: dict[str, Any] = {
        "reviewed_at": now,
        "file_count_at_review": resolved_total_files,
        "finding_count": len(valid),
    }
    if isinstance(review_scope, dict):
        reviewed_files_count = review_scope.get("reviewed_files_count")
        if (
            isinstance(reviewed_files_count, int)
            and not isinstance(reviewed_files_count, bool)
            and reviewed_files_count >= 0
        ):
            holistic_entry["reviewed_files_count"] = reviewed_files_count
        full_sweep_included = review_scope.get("full_sweep_included")
        if isinstance(full_sweep_included, bool):
            holistic_entry["full_sweep_included"] = full_sweep_included

    review_cache["holistic"] = holistic_entry


def resolve_holistic_coverage_findings(
    state: dict[str, Any],
    diff: dict[str, Any],
    *,
    utc_now_fn=utc_now,
) -> None:
    """Resolve stale holistic coverage entries after successful holistic import."""
    now = utc_now_fn()
    for finding in state.get("findings", {}).values():
        if finding.get("status") != "open":
            continue
        if finding.get("detector") != "subjective_review":
            continue

        finding_id = finding.get("id", "")
        if (
            "::holistic_unreviewed" not in finding_id
            and "::holistic_stale" not in finding_id
        ):
            continue

        finding["status"] = "auto_resolved"
        finding["resolved_at"] = now
        finding["note"] = "resolved by holistic review import"
        finding["resolution_attestation"] = {
            "kind": "agent_import",
            "text": "Holistic review refreshed; coverage marker superseded",
            "attested_at": now,
            "scan_verified": False,
        }
        diff["auto_resolved"] += 1


def resolve_reviewed_file_coverage_findings(
    state: dict[str, Any],
    diff: dict[str, Any],
    reviewed_files: list[str],
    *,
    utc_now_fn=utc_now,
) -> None:
    """Resolve per-file subjective coverage markers for freshly reviewed files."""
    if not reviewed_files:
        return

    reviewed_set = {path for path in reviewed_files if isinstance(path, str) and path}
    if not reviewed_set:
        return

    now = utc_now_fn()
    for finding in state.get("findings", {}).values():
        if finding.get("status") != "open":
            continue
        if finding.get("detector") != "subjective_review":
            continue

        finding_id = finding.get("id", "")
        if "::holistic_unreviewed" in finding_id or "::holistic_stale" in finding_id:
            continue

        finding_file = finding.get("file", "")
        if finding_file not in reviewed_set:
            continue

        finding["status"] = "auto_resolved"
        finding["resolved_at"] = now
        finding["note"] = "resolved by reviewed_files cache refresh"
        finding["resolution_attestation"] = {
            "kind": "agent_import",
            "text": "Per-file review cache refreshed for this file",
            "attested_at": now,
            "scan_verified": False,
        }
        diff["auto_resolved"] += 1
