"""Holistic review issue import workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from desloppify.engine._state.merge import MergeScanOptions, merge_scan
from desloppify.engine._state.schema import StateModel, utc_now
from desloppify.engine.concerns import cleanup_stale_dismissals, generate_concerns
from desloppify.engine.scoring import HOLISTIC_POTENTIAL
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.importing.assessments import (
    backfill_judgment_strengths,
    store_assessments,
    store_context_updates,
)
from desloppify.intelligence.review.importing.contracts_types import (
    ReviewImportPayload,
    ReviewIssuePayload,
)
from desloppify.intelligence.review.importing.holistic_cache import (
    resolve_holistic_coverage_issues,
    resolve_reviewed_file_coverage_issues,
    update_holistic_review_cache,
    update_reviewed_file_cache,
)
from desloppify.intelligence.review.importing.holistic_issue_flow import (
    auto_resolve_stale_holistic as _auto_resolve_stale_holistic,
)
from desloppify.intelligence.review.importing.holistic_issue_flow import (
    collect_imported_dimensions as _collect_imported_dimensions,
)
from desloppify.intelligence.review.importing.holistic_issue_flow import (
    validate_and_build_issues as _validate_and_build_issues,
)
from desloppify.intelligence.review.importing.payload import (
    ReviewImportEnvelope,
    parse_review_import_payload,
)
from desloppify.intelligence.review.importing.state_helpers import (
    ensure_lang_potentials,
)


def parse_holistic_import_payload(
    data: ReviewImportPayload | dict[str, Any],
) -> tuple[list[ReviewIssuePayload], dict[str, Any] | None, list[str]]:
    """Parse strict holistic import payload object."""
    payload = parse_review_import_payload(data, mode_name="Holistic")
    return payload.issues, payload.assessments, payload.reviewed_files


def import_holistic_issues(
    issues_data: ReviewImportPayload,
    state: StateModel,
    lang_name: str,
    *,
    project_root: Path | str | None = None,
    preserve_open_issue_ids: set[str] | None = None,
    utc_now_fn=utc_now,
) -> dict[str, Any]:
    """Import holistic (codebase-wide) issues into state."""
    payload: ReviewImportEnvelope = parse_review_import_payload(
        issues_data,
        mode_name="Holistic",
    )
    issues_list = payload.issues
    assessments = payload.assessments
    reviewed_files = payload.reviewed_files
    dimension_judgment = payload.dimension_judgment
    context_updates = payload.context_updates
    review_scope = issues_data.get("review_scope", {})
    if not isinstance(review_scope, dict):
        review_scope = {}
    review_scope.setdefault("full_sweep_included", None)
    scope_full_sweep = review_scope.get("full_sweep_included")
    if not isinstance(scope_full_sweep, bool):
        scope_full_sweep = None

    _, holistic_prompts, _ = load_dimensions_for_lang(lang_name)
    valid_dimensions = {
        normalize_dimension_name(dim)
        for dim in holistic_prompts
        if isinstance(dim, str)
    }

    if assessments:
        store_assessments(
            state,
            assessments,
            source="holistic",
            utc_now_fn=utc_now_fn,
            dimension_judgment=dimension_judgment,
        )

    # Store accumulated dimension context updates
    if isinstance(context_updates, dict):
        store_context_updates(
            state,
            context_updates,
            valid_dimensions=valid_dimensions,
            utc_now_fn=utc_now_fn,
        )
        # Derive judgment.strengths from positive context insights
        backfill_judgment_strengths(state, context_updates)

    review_issues, skipped, dismissed_concerns = _validate_and_build_issues(
        issues_list,
        holistic_prompts,
        lang_name,
    )
    imported_dimensions = _collect_imported_dimensions(
        issues_list=issues_list,
        review_issues=review_issues,
        assessments=assessments if isinstance(assessments, dict) else None,
        review_scope=review_scope,
        valid_dimensions=valid_dimensions,
    )

    if dismissed_concerns:
        store = state.setdefault("concern_dismissals", {})
        now = utc_now_fn()
        current_concerns = generate_concerns(state)
        concern_sources = {
            concern.fingerprint: list(concern.source_issues)
            for concern in current_concerns
        }
        for dismissal in dismissed_concerns:
            fingerprint = dismissal["fingerprint"]
            store[fingerprint] = {
                "dismissed_at": now,
                "reasoning": dismissal.get("reasoning", ""),
                "concern_type": dismissal.get("concern_type", ""),
                "concern_file": dismissal.get("concern_file", ""),
                "source_issue_ids": concern_sources.get(fingerprint, []),
            }

    potentials = ensure_lang_potentials(state, lang_name)
    existing_review = potentials.get("review", 0)
    potentials["review"] = max(existing_review, HOLISTIC_POTENTIAL)

    concern_count = sum(1 for issue in review_issues if issue.get("detector") == "concerns")
    if concern_count:
        potentials["concerns"] = max(potentials.get("concerns", 0), concern_count)

    merge_potentials_dict: dict[str, int] = {"review": potentials.get("review", 0)}
    if potentials.get("concerns", 0) > 0:
        merge_potentials_dict["concerns"] = potentials["concerns"]

    diff = merge_scan(
        state,
        review_issues,
        options=MergeScanOptions(
            lang=lang_name,
            potentials=merge_potentials_dict,
            merge_potentials=True,
        ),
    )

    new_ids = {issue["id"] for issue in review_issues}
    _auto_resolve_stale_holistic(
        state,
        new_ids,
        diff,
        utc_now_fn,
        imported_dimensions=imported_dimensions,
        full_sweep_included=scope_full_sweep,
        preserve_open_issue_ids=preserve_open_issue_ids,
    )

    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped

    update_reviewed_file_cache(
        state,
        reviewed_files,
        project_root=project_root,
        utc_now_fn=utc_now_fn,
    )
    resolve_reviewed_file_coverage_issues(
        state,
        diff,
        reviewed_files,
        utc_now_fn=utc_now_fn,
    )
    update_holistic_review_cache(
        state,
        issues_list,
        lang_name=lang_name,
        review_scope=review_scope,
        utc_now_fn=utc_now_fn,
    )
    resolve_holistic_coverage_issues(state, diff, utc_now_fn=utc_now_fn)

    cleanup_stale_dismissals(state)

    return diff


__all__ = [
    "import_holistic_issues",
    "parse_holistic_import_payload",
    "resolve_holistic_coverage_issues",
    "resolve_reviewed_file_coverage_issues",
    "update_holistic_review_cache",
    "update_reviewed_file_cache",
]
