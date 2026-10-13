"""Per-file review issue import workflow."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.merge import MergeScanOptions, merge_scan
from desloppify.engine._state.schema import StateModel, utc_now
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.importing.assessments import store_assessments
from desloppify.intelligence.review.importing.cache import (
    refresh_review_file_cache,
    resolve_import_project_root,
)
from desloppify.intelligence.review.importing.contracts_types import (
    ReviewImportPayload,
    ReviewIssuePayload,
)
from desloppify.intelligence.review.importing.payload import (
    ReviewImportEnvelope,
    normalize_review_confidence,
    parse_review_import_payload,
    review_tier,
)
from desloppify.intelligence.review.importing.resolution import (
    auto_resolve_review_issues,
)
from desloppify.intelligence.review.importing.state_helpers import (
    ensure_lang_potentials,
)
from desloppify.intelligence.review.selection import hash_file


def parse_per_file_import_payload(
    data: ReviewImportPayload | dict[str, Any],
) -> tuple[list[ReviewIssuePayload], dict[str, Any] | None]:
    """Parse strict per-file import payload object."""
    payload = parse_review_import_payload(data, mode_name="Per-file")
    return payload.issues, payload.assessments


def _absolutize_review_path(file_path: str, *, project_root: Path) -> str:
    """Return a stable absolute file path for per-file review import matching."""
    candidate = Path(file_path)
    if candidate.is_absolute():
        return str(candidate.resolve())
    return str((project_root / candidate).resolve())


def _resolve_per_file_project_root(project_root: Path | str | None) -> Path:
    """Resolve import root for per-file review imports."""
    return resolve_import_project_root(project_root)


def import_review_issues(
    issues_data: ReviewImportPayload,
    state: StateModel,
    lang_name: str,
    *,
    project_root: Path | str | None = None,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Import agent-produced per-file review issues into state."""
    payload: ReviewImportEnvelope = parse_review_import_payload(
        issues_data, mode_name="Per-file"
    )
    issues_list = payload.issues
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

    review_issues: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for idx, issue in enumerate(issues_list):
        missing = [key for key in required_fields if key not in issue]
        if missing:
            skipped.append(
                {
                    "index": idx,
                    "missing": missing,
                    "identifier": issue.get("identifier", "<none>"),
                }
            )
            continue

        confidence = normalize_review_confidence(issue.get("confidence", "low"))

        dimension = issue["dimension"]
        if dimension not in per_file_prompts:
            skipped.append(
                {
                    "index": idx,
                    "missing": [f"invalid dimension: {dimension}"],
                    "identifier": issue.get("identifier", "<none>"),
                }
            )
            continue

        content_hash = hashlib.sha256(issue["summary"].encode()).hexdigest()[:8]
        imported_file = _absolutize_review_path(
            str(issue["file"]),
            project_root=resolved_project_root,
        )
        imported = make_issue(
            detector="review",
            file=imported_file,
            name=f"{dimension}::{issue['identifier']}",
            tier=review_tier(confidence, holistic=False),
            confidence=confidence,
            summary=issue["summary"],
            detail={
                "dimension": dimension,
                "evidence": issue.get("evidence", []),
                "suggestion": issue.get("suggestion", ""),
                "reasoning": issue.get("reasoning", ""),
                "evidence_lines": issue.get("evidence_lines", []),
                "content_hash": content_hash,
            },
        )
        imported["lang"] = lang_name
        review_issues.append(imported)

    # Build accepted-file set from successfully imported issues only,
    # not from all issues_list entries (which may include invalid dimensions).
    valid_reviewed_files_abs = {
        issue["file"] for issue in review_issues
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

    potentials = ensure_lang_potentials(state, lang_name)
    potentials["review"] = len(review_potential_files)

    diff = merge_scan(
        state,
        review_issues,
        options=MergeScanOptions(
            lang=lang_name,
            scan_path=state.get("scan_path"),
            potentials={"review": potentials.get("review", 0)},
            merge_potentials=True,
        ),
    )

    new_ids = {issue["id"] for issue in review_issues}
    reimported_files = valid_reviewed_files
    auto_resolve_review_issues(
        state,
        new_ids=new_ids,
        diff=diff,
        note="not reported in latest per-file re-import",
        should_resolve=lambda issue: (
            issue.get("detector") == "review"
            and not issue.get("detail", {}).get("holistic")
            and issue.get("file", "") in reimported_files
        ),
        utc_now_fn=utc_now_fn,
    )

    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped

    update_review_cache(
        state,
        issues_list,
        reviewed_files=reviewed_files,
        project_root=resolved_project_root,
        utc_now_fn=utc_now_fn,
    )
    return diff


def update_review_cache(
    state: StateModel,
    issues_data: list[ReviewIssuePayload],
    *,
    reviewed_files: list[str] | None = None,
    project_root: Path | str | None = None,
    utc_now_fn=utc_now,
) -> None:
    """Update per-file review cache with timestamps and content hashes."""
    issues_by_file: dict[str, int] = {}
    for issue in issues_data:
        file_path = issue.get("file")
        if not isinstance(file_path, str):
            continue
        issues_by_file[file_path] = issues_by_file.get(file_path, 0) + 1

    refresh_review_file_cache(
        state,
        reviewed_files=reviewed_files,
        issues_by_file=issues_by_file,
        project_root=project_root,
        hash_file_fn=hash_file,
        utc_now_fn=utc_now_fn,
    )
