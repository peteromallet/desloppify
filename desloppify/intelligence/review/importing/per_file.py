"""Per-file review finding import workflow."""

from __future__ import annotations

import hashlib
import importlib
from typing import Any

from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.importing.shared import (
    _lang_potentials,
    _review_file_cache,
    extract_reviewed_files,
    store_assessments,
)
from desloppify.state import MergeScanOptions, make_finding, merge_scan, utc_now
from desloppify.core._internal.text_utils import PROJECT_ROOT


def parse_per_file_import_payload(data: dict) -> tuple[list[dict], dict | None]:
    """Parse strict per-file import payload object."""
    if not isinstance(data, dict):
        raise ValueError("Per-file review import payload must be a JSON object")

    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Per-file review import payload 'findings' must be a list")

    assessments = data.get("assessments")
    if assessments is not None and not isinstance(assessments, dict):
        raise ValueError(
            "Per-file review import payload 'assessments' must be an object"
        )
    return findings, assessments


def import_review_findings(
    findings_data: dict,
    state: dict[str, Any],
    lang_name: str,
    *,
    project_root=PROJECT_ROOT,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Import agent-produced per-file review findings into state."""
    findings_list, assessments = parse_per_file_import_payload(findings_data)
    reviewed_files = extract_reviewed_files(findings_data)
    if assessments:
        store_assessments(
            state,
            assessments,
            source="per_file",
            utc_now_fn=utc_now_fn,
        )

    _, per_file_prompts, _ = load_dimensions_for_lang(lang_name)
    required_fields = ("file", "dimension", "identifier", "summary", "confidence")

    review_findings: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for idx, finding in enumerate(findings_list):
        missing = [key for key in required_fields if key not in finding]
        if missing:
            skipped.append(
                {
                    "index": idx,
                    "missing": missing,
                    "identifier": finding.get("identifier", "<none>"),
                }
            )
            continue

        confidence = finding.get("confidence", "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        dimension = finding["dimension"]
        if dimension not in per_file_prompts:
            skipped.append(
                {
                    "index": idx,
                    "missing": [f"invalid dimension: {dimension}"],
                    "identifier": finding.get("identifier", "<none>"),
                }
            )
            continue

        content_hash = hashlib.sha256(finding["summary"].encode()).hexdigest()[:8]
        imported = make_finding(
            detector="review",
            file=str(project_root / finding["file"]),
            name=f"{dimension}::{finding['identifier']}::{content_hash}",
            tier=3,
            confidence=confidence,
            summary=finding["summary"],
            detail={
                "dimension": dimension,
                "evidence": finding.get("evidence", []),
                "suggestion": finding.get("suggestion", ""),
                "reasoning": finding.get("reasoning", ""),
                "evidence_lines": finding.get("evidence_lines", []),
            },
        )
        imported["lang"] = lang_name
        review_findings.append(imported)

    valid_reviewed_files = {
        finding["file"]
        for finding in findings_list
        if all(key in finding for key in required_fields)
    }
    review_potential_files = valid_reviewed_files | set(reviewed_files)

    potentials = _lang_potentials(state, lang_name)
    potentials["review"] = len(review_potential_files)

    diff = merge_scan(
        state,
        review_findings,
        options=MergeScanOptions(
            lang=lang_name,
            potentials={"review": potentials.get("review", 0)},
            merge_potentials=True,
        ),
    )

    new_ids = {finding["id"] for finding in review_findings}
    reimported_files = valid_reviewed_files
    for finding_id, finding in state.get("findings", {}).items():
        if (
            finding["status"] == "open"
            and finding.get("detector") == "review"
            and not finding.get("detail", {}).get("holistic")
            and finding.get("file", "") in reimported_files
            and finding_id not in new_ids
        ):
            finding["status"] = "auto_resolved"
            finding["resolved_at"] = utc_now_fn()
            finding["note"] = "not reported in latest per-file re-import"
            diff["auto_resolved"] = diff.get("auto_resolved", 0) + 1

    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped

    update_review_cache(
        state,
        findings_list,
        reviewed_files=reviewed_files,
        project_root=project_root,
        utc_now_fn=utc_now_fn,
    )
    return diff


def update_review_cache(
    state: dict[str, Any],
    findings_data: list[dict],
    *,
    reviewed_files: list[str] | None = None,
    project_root=PROJECT_ROOT,
    utc_now_fn=utc_now,
) -> None:
    """Update per-file review cache with timestamps and content hashes."""
    selection_mod = importlib.import_module("desloppify.intelligence.review.selection")

    file_cache = _review_file_cache(state)
    now = utc_now_fn()

    findings_by_file: dict[str, list[dict]] = {}
    for finding in findings_data:
        file_path = finding.get("file")
        if not isinstance(file_path, str):
            continue
        findings_by_file.setdefault(file_path, []).append(finding)

    reviewed_set = set(findings_by_file)
    if reviewed_files:
        reviewed_set.update(file_path for file_path in reviewed_files if file_path)

    for file_path in reviewed_set:
        absolute = project_root / file_path
        content_hash = (
            selection_mod.hash_file(str(absolute)) if absolute.exists() else ""
        )
        file_cache[file_path] = {
            "content_hash": content_hash,
            "reviewed_at": now,
            "finding_count": len(findings_by_file.get(file_path, [])),
        }
