"""Historical review-issue context builders for retrospective review loops."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_RESOLVED_STATUSES = {"fixed", "auto_resolved", "wontfix", "false_positive"}
_KNOWN_STATUSES = ("open", "fixed", "auto_resolved", "wontfix", "false_positive")
_AUTO_RESOLVE_NOTE = "not reported in latest holistic re-import"


@dataclass(frozen=True)
class ReviewHistoryOptions:
    """Sizing controls for historical review-issue context payloads."""

    max_issues: int = 30


def _normalize_int(raw: object, *, default: int, minimum: int = 1) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _trim(text: object, *, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)].rstrip() + "..."


def _timestamp_sort_key(value: object) -> tuple[int, str]:
    raw = str(value or "").strip()
    if not raw:
        return (0, "")
    try:
        return (1, datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat())
    except ValueError:
        return (1, raw)


def _finding_dimension(finding: dict[str, Any]) -> str:
    detail = finding.get("detail")
    if not isinstance(detail, dict):
        return "unknown"
    dimension = str(detail.get("dimension", "")).strip()
    return dimension or "unknown"


def _related_files(finding: dict[str, Any], *, limit: int = 6) -> list[str]:
    detail = finding.get("detail")
    if not isinstance(detail, dict):
        return []
    raw = detail.get("related_files")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        file_path = str(value or "").strip()
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)
        out.append(file_path)
        if len(out) >= limit:
            break
    return out


def _iter_review_findings(state: dict[str, Any]) -> list[dict[str, Any]]:
    findings = state.get("findings")
    if not isinstance(findings, dict):
        return []
    out: list[dict[str, Any]] = []
    for raw in findings.values():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("detector", "")).strip() != "review":
            continue
        out.append(raw)
    return out


def _meaningful_note(finding: dict[str, Any]) -> str:
    """Return the note if it's a real human-written note, not an auto-resolve boilerplate."""
    raw = str(finding.get("note", "") or "").strip()
    if not raw or raw == _AUTO_RESOLVE_NOTE:
        return ""
    return raw


def _shape_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Shape a single finding into the payload format for the reviewer."""
    detail = finding.get("detail") or {}
    return {
        "dimension": _finding_dimension(finding),
        "status": str(finding.get("status", "open")).strip() or "open",
        "summary": _trim(finding.get("summary", ""), limit=200),
        "suggestion": _trim(detail.get("suggestion", ""), limit=200),
        "related_files": _related_files(finding),
        "note": _meaningful_note(finding),
        "confidence": str(finding.get("confidence", "")).strip(),
        "first_seen": str(finding.get("first_seen", "")).strip(),
        "last_seen": str(finding.get("last_seen", "")).strip(),
    }


def build_issue_history_context(
    state: dict[str, Any],
    *,
    options: ReviewHistoryOptions | None = None,
) -> dict[str, Any]:
    """Build flat issue-history context for retrospective subjective review.

    Returns the most recent review findings as a flat list, each with its
    status, summary, suggestion, related files, and any human-written note.
    """
    resolved_options = options or ReviewHistoryOptions()
    max_issues = _normalize_int(resolved_options.max_issues, default=30)

    review_findings = _iter_review_findings(state)
    if not review_findings:
        return {
            "summary": {
                "total_review_findings": 0,
                "open_review_findings": 0,
                "status_counts": {status: 0 for status in _KNOWN_STATUSES},
                "dimension_open_counts": {},
            },
            "recent_issues": [],
        }

    status_counts: Counter[str] = Counter()
    dimension_open_counts: Counter[str] = Counter()

    for finding in review_findings:
        status = str(finding.get("status", "open")).strip() or "open"
        status_counts[status] += 1
        if status == "open":
            dimension_open_counts[_finding_dimension(finding)] += 1

    # Sort by last_seen descending, take the most recent N.
    sorted_findings = sorted(
        review_findings,
        key=lambda f: _timestamp_sort_key(f.get("last_seen")),
        reverse=True,
    )

    recent_issues = [_shape_finding(f) for f in sorted_findings[:max_issues]]

    return {
        "summary": {
            "total_review_findings": len(review_findings),
            "open_review_findings": int(status_counts.get("open", 0)),
            "status_counts": {
                status: int(status_counts.get(status, 0)) for status in _KNOWN_STATUSES
            },
            "dimension_open_counts": {
                dim: count
                for dim, count in sorted(
                    dimension_open_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            },
        },
        "recent_issues": recent_issues,
    }


def _normalize_dimensions(dimensions: object) -> list[str]:
    if not isinstance(dimensions, list | tuple | set):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in dimensions:
        dim = str(value or "").strip()
        if not dim or dim in seen:
            continue
        seen.add(dim)
        out.append(dim)
    return out


def build_batch_issue_focus(
    history: dict[str, Any],
    *,
    dimensions: object,
    max_items: int = 20,
) -> dict[str, Any]:
    """Build a dimension-scoped issue slice for one review batch.

    Filters the flat recent_issues list to only those matching the batch
    dimensions, capped at max_items.
    """
    dim_list = _normalize_dimensions(dimensions)
    dim_set = set(dim_list)
    limit = _normalize_int(max_items, default=20, minimum=1)

    all_issues = history.get("recent_issues", [])
    if not isinstance(all_issues, list):
        all_issues = []

    filtered: list[dict[str, Any]] = []
    for issue in all_issues:
        if not isinstance(issue, dict):
            continue
        dim = str(issue.get("dimension", "")).strip()
        if dim and dim in dim_set:
            filtered.append(issue)
            if len(filtered) >= limit:
                break

    return {
        "dimensions": dim_list,
        "max_items": limit,
        "selected_count": len(filtered),
        "issues": filtered,
    }


__all__ = [
    "ReviewHistoryOptions",
    "build_issue_history_context",
    "build_batch_issue_focus",
]
