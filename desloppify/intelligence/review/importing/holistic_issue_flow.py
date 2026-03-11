"""Issue validation and stale-resolution helpers for holistic review imports."""

from __future__ import annotations

import hashlib
from typing import Any

from desloppify.engine._state.filtering import make_issue
from desloppify.engine._state.schema import Issue, StateModel
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.intelligence.review.importing.contracts_types import (
    ReviewIssuePayload,
    ReviewScopePayload,
)
from desloppify.intelligence.review.importing.contracts_validation import (
    validate_review_issue_payload,
)
from desloppify.intelligence.review.importing.payload import (
    normalize_review_confidence,
    review_tier,
)
from desloppify.intelligence.review.importing.resolution import (
    auto_resolve_review_issues,
)

_POSITIVE_PREFIXES = (
    "good ",
    "well ",
    "strong ",
    "clean ",
    "excellent ",
    "nice ",
    "solid ",
)


def _build_holistic_detail(
    *,
    content_hash: str,
    dimension: str,
    related_files: list[str],
    evidence: list[str],
    suggestion: str,
    reasoning: str,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "holistic": True,
        "dimension": dimension,
        "related_files": related_files,
        "evidence": evidence,
        "suggestion": suggestion,
        "reasoning": reasoning,
    }
    detail["summary_hash"] = content_hash
    return detail


def validate_and_build_issues(
    issues_list: list[ReviewIssuePayload],
    holistic_prompts: dict[str, Any],
    lang_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate raw holistic issues and build state-ready issue dicts.

    Returns (review_issues, skipped, dismissed_concerns).
    """
    review_issues: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    dismissed_concerns: list[dict[str, Any]] = []
    allowed_dimensions = {
        dim for dim in holistic_prompts if isinstance(dim, str) and dim.strip()
    }

    for idx, raw_issue in enumerate(issues_list):
        issue, issue_errors = validate_review_issue_payload(
            raw_issue,
            label=f"issues[{idx}]",
            allowed_dimensions=allowed_dimensions,
            allow_dismissed=True,
        )
        if issue_errors:
            skipped.append(
                {
                    "index": idx,
                    "missing": issue_errors,
                    "identifier": (
                        raw_issue.get("identifier", "<none>")
                        if isinstance(raw_issue, dict)
                        else "<none>"
                    ),
                }
            )
            continue
        if issue is None:
            raise ValueError(
                "review issue payload missing after validation succeeded"
            )

        if issue.get("concern_verdict") == "dismissed":
            fingerprint = issue.get("concern_fingerprint", "")
            if fingerprint:
                dismissed_concerns.append(
                    {
                        "fingerprint": fingerprint,
                        "concern_type": issue.get("concern_type", ""),
                        "concern_file": issue.get("concern_file", ""),
                        "reasoning": issue.get("reasoning", ""),
                    }
                )
            continue

        summary_text = str(issue.get("summary", ""))
        if summary_text.lower().startswith(_POSITIVE_PREFIXES):
            skipped.append(
                {
                    "index": idx,
                    "missing": ["positive observation (not a defect)"],
                    "identifier": issue.get("identifier", "<none>"),
                }
            )
            continue

        dimension = issue["dimension"]

        is_confirmed_concern = issue.get("concern_verdict") == "confirmed"
        detector = "concerns" if is_confirmed_concern else "review"

        content_hash = hashlib.sha256(summary_text.encode()).hexdigest()[:8]
        detail = _build_holistic_detail(
            content_hash=content_hash,
            dimension=dimension,
            related_files=issue["related_files"],
            evidence=issue["evidence"],
            suggestion=issue.get("suggestion", ""),
            reasoning=issue.get("reasoning", ""),
        )
        if is_confirmed_concern:
            detail["concern_type"] = issue.get("concern_type", "")
            detail["concern_verdict"] = "confirmed"

        prefix = "concern" if is_confirmed_concern else "holistic"
        issue_file = issue.get("concern_file", "") if is_confirmed_concern else ""
        confidence = normalize_review_confidence(issue.get("confidence", "low"))
        imported = make_issue(
            detector=detector,
            file=issue_file,
            name=f"{prefix}::{dimension}::{issue['identifier']}",
            tier=review_tier(confidence, holistic=True),
            confidence=confidence,
            summary=summary_text,
            detail=detail,
        )
        imported["lang"] = lang_name
        review_issues.append(imported)

    return review_issues, skipped, dismissed_concerns


def collect_imported_dimensions(
    *,
    issues_list: list[ReviewIssuePayload],
    review_issues: list[dict[str, Any]],
    assessments: dict[str, Any] | None,
    review_scope: ReviewScopePayload | dict[str, Any] | None,
    valid_dimensions: set[str],
) -> set[str]:
    """Return normalized dimensions this import explicitly covered."""
    imported_dimensions: set[str] = set()

    if isinstance(review_scope, dict):
        scope_dims = review_scope.get("imported_dimensions")
        if isinstance(scope_dims, list):
            for raw_dim in scope_dims:
                normalized = normalize_dimension_name(str(raw_dim))
                if normalized in valid_dimensions:
                    imported_dimensions.add(normalized)

    for issue in issues_list:
        if not isinstance(issue, dict):
            continue
        normalized = normalize_dimension_name(str(issue.get("dimension", "")))
        if normalized in valid_dimensions:
            imported_dimensions.add(normalized)

    for issue in review_issues:
        detail = issue.get("detail")
        if not isinstance(detail, dict):
            continue
        normalized = normalize_dimension_name(str(detail.get("dimension", "")))
        if normalized in valid_dimensions:
            imported_dimensions.add(normalized)

    for raw_dim in (assessments or {}):
        normalized = normalize_dimension_name(str(raw_dim))
        if normalized in valid_dimensions:
            imported_dimensions.add(normalized)

    return imported_dimensions


def auto_resolve_stale_holistic(
    state: StateModel,
    new_ids: set[str],
    diff: dict[str, Any],
    utc_now_fn,
    *,
    imported_dimensions: set[str] | None = None,
    full_sweep_included: bool | None = None,
) -> None:
    """Auto-resolve open holistic issues not present in the latest import."""
    scope_dimensions = {
        normalize_dimension_name(dim)
        for dim in (imported_dimensions or set())
        if isinstance(dim, str) and dim.strip()
    }
    scoped_reimport = full_sweep_included is False
    if scoped_reimport and not scope_dimensions:
        return

    def _should_resolve(issue: Issue) -> bool:
        if issue.get("detector") not in ("review", "concerns"):
            return False
        detail = issue.get("detail")
        if not isinstance(detail, dict) or not detail.get("holistic"):
            return False
        if not scoped_reimport:
            return True
        dimension = normalize_dimension_name(str(detail.get("dimension", "")))
        return dimension in scope_dimensions

    auto_resolve_review_issues(
        state,
        new_ids=new_ids,
        diff=diff,
        note="not reported in latest holistic re-import",
        should_resolve=_should_resolve,
        utc_now_fn=utc_now_fn,
    )


__all__ = [
    "auto_resolve_stale_holistic",
    "collect_imported_dimensions",
    "validate_and_build_issues",
]
