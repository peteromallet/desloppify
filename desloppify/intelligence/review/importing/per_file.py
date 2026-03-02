"""Per-file review finding import workflow."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.importing.contracts import (
    ReviewFindingPayload,
    ReviewImportPayload,
)
from desloppify.intelligence.review.importing.shared import (
    _lang_potentials,
    auto_resolve_review_findings,
    normalize_review_confidence,
    parse_review_import_payload,
    refresh_review_file_cache,
    resolve_import_project_root,
    review_tier,
    ReviewImportEnvelope,
    store_assessments,
)
from desloppify.intelligence.review.selection import hash_file
from desloppify.state import MergeScanOptions, make_finding, merge_scan, utc_now

PROJECT_ROOT: Path | None = None


def parse_per_file_import_payload(
    data: ReviewImportPayload | dict[str, Any],
) -> tuple[list[ReviewFindingPayload], dict[str, Any] | None]:
    """Parse strict per-file import payload object."""
    payload = parse_review_import_payload(data, mode_name="Per-file")
    return payload.findings, payload.assessments


def _absolutize_review_path(file_path: str, *, project_root: Path) -> str:
    """Return a stable absolute file path for per-file review import matching."""
    candidate = Path(file_path)
    if candidate.is_absolute():
        return str(candidate.resolve())
    return str((project_root / candidate).resolve())


def _resolve_per_file_project_root(project_root: Path | str | None) -> Path:
    """Resolve import root with legacy module-level override support for tests."""
    if project_root is None and isinstance(PROJECT_ROOT, Path):
        return PROJECT_ROOT
    return resolve_import_project_root(project_root)


def import_review_findings(
    findings_data: ReviewImportPayload,
    state: dict[str, Any],
    lang_name: str,
    *,
    project_root: Path | str | None = None,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Import agent-produced per-file review findings into state."""
    payload: ReviewImportEnvelope = parse_review_import_payload(
        findings_data, mode_name="Per-file"
    )
    findings_list = payload.findings
    assessments = payload.assessments
    reviewed_files = payload.reviewed_files
    resolved_project_root = _resolve_per_file_project_root(project_root)
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

        confidence = normalize_review_confidence(finding.get("confidence", "low"))

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
        imported_file = _absolutize_review_path(
            str(finding["file"]),
            project_root=resolved_project_root,
        )
        imported = make_finding(
            detector="review",
            file=imported_file,
            name=f"{dimension}::{finding['identifier']}::{content_hash}",
            tier=review_tier(confidence, holistic=False),
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

    # Build accepted-file set from successfully imported findings only,
    # not from all findings_list entries (which may include invalid dimensions).
    valid_reviewed_files_abs = {
        finding["file"] for finding in review_findings
    }
    valid_reviewed_files = valid_reviewed_files_abs
    reviewed_files_rel = {
        str(file_path).strip()
        for file_path in reviewed_files
        if isinstance(file_path, str) and file_path.strip()
    }
    reviewed_files_abs = {
        _absolutize_review_path(file_path, project_root=resolved_project_root)
        for file_path in reviewed_files_rel
    }
    review_potential_files = valid_reviewed_files | {
        *reviewed_files_rel,
        *reviewed_files_abs,
    }

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
    auto_resolve_review_findings(
        state,
        new_ids=new_ids,
        diff=diff,
        note="not reported in latest per-file re-import",
        should_resolve=lambda finding: (
            finding.get("detector") == "review"
            and not finding.get("detail", {}).get("holistic")
            and finding.get("file", "") in reimported_files
        ),
        utc_now_fn=utc_now_fn,
    )

    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped

    update_review_cache(
        state,
        findings_list,
        reviewed_files=reviewed_files,
        project_root=resolved_project_root,
        utc_now_fn=utc_now_fn,
    )
    return diff


def update_review_cache(
    state: dict[str, Any],
    findings_data: list[ReviewFindingPayload],
    *,
    reviewed_files: list[str] | None = None,
    project_root: Path | str | None = None,
    utc_now_fn=utc_now,
) -> None:
    """Update per-file review cache with timestamps and content hashes."""
    findings_by_file: dict[str, int] = {}
    for finding in findings_data:
        file_path = finding.get("file")
        if not isinstance(file_path, str):
            continue
        findings_by_file[file_path] = findings_by_file.get(file_path, 0) + 1

    refresh_review_file_cache(
        state,
        reviewed_files=reviewed_files,
        findings_by_file=findings_by_file,
        project_root=project_root,
        hash_file_fn=hash_file,
        utc_now_fn=utc_now_fn,
    )
