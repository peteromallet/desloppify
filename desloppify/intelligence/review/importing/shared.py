"""Shared parsing/assessment helpers for review finding imports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.core._internal.text_utils import get_project_root
from desloppify.core._internal.text_utils import is_numeric
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.intelligence.review.importing.contracts import (
    ReviewFindingPayload,
    ReviewImportPayload,
)
from desloppify.state import utc_now


@dataclass(frozen=True)
class ReviewImportEnvelope:
    """Validated shared payload shape for review imports."""

    findings: list[ReviewFindingPayload]
    assessments: dict[str, Any] | None
    reviewed_files: list[str]


def _review_file_cache(state: dict[str, Any]) -> dict:
    """Access ``state["review_cache"]["files"]``, creating if absent."""
    return state.setdefault("review_cache", {}).setdefault("files", {})


def _lang_potentials(state: dict[str, Any], lang_name: str) -> dict:
    """Access ``state["potentials"][lang_name]``, creating if absent."""
    return state.setdefault("potentials", {}).setdefault(lang_name, {})


def store_assessments(
    state: dict[str, Any],
    assessments: dict[str, Any],
    source: str,
    *,
    utc_now_fn=utc_now,
) -> None:
    """Store dimension assessments in state.

    *assessments*: ``{dim_name: score}`` or ``{dim_name: {score, ...}}``.
    *source*: ``"per_file"`` or ``"holistic"``.

    Holistic assessments overwrite per-file for the same dimension.
    Per-file assessments don't overwrite holistic.
    """
    store = state.setdefault("subjective_assessments", {})
    now = utc_now_fn()

    for dimension_name, value in assessments.items():
        value_obj = value if isinstance(value, dict) else {}
        score = value if is_numeric(value) else value_obj.get("score", 0)
        score = max(0, min(100, score))
        dimension_key = normalize_dimension_name(str(dimension_name))
        if not dimension_key:
            continue

        existing = store.get(dimension_key)
        if existing and existing.get("source") == "holistic" and source == "per_file":
            continue

        cleaned_components: list[str] = []
        components = value_obj.get("components")
        if isinstance(components, list):
            cleaned_components = [
                str(item).strip()
                for item in components
                if isinstance(item, str) and item.strip()
            ]

        component_scores = value_obj.get("component_scores")
        cleaned_scores: dict[str, float] = {}
        if isinstance(component_scores, dict):
            for key, raw in component_scores.items():
                if not isinstance(key, str) or not key.strip():
                    continue
                if not is_numeric(raw):
                    continue
                cleaned_scores[key.strip()] = round(max(0.0, min(100.0, float(raw))), 1)

        store[dimension_key] = {
            "score": score,
            "source": source,
            "assessed_at": now,
            **({"components": cleaned_components} if cleaned_components else {}),
            **({"component_scores": cleaned_scores} if cleaned_scores else {}),
        }


def extract_reviewed_files(data: list[dict] | dict) -> list[str]:
    """Parse optional reviewed-file list from import payload."""
    if not isinstance(data, dict):
        return []
    raw = data.get("reviewed_files")
    if not isinstance(raw, list):
        return []

    reviewed: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        path = item.strip()
        if not path or path in seen:
            continue
        seen.add(path)
        reviewed.append(path)
    return reviewed


def parse_review_import_payload(
    data: ReviewImportPayload | dict[str, Any],
    *,
    mode_name: str,
) -> ReviewImportEnvelope:
    """Parse shared review import payload shape for per-file/holistic flows."""
    if not isinstance(data, dict):
        raise ValueError(f"{mode_name} review import payload must be a JSON object")

    if "findings" not in data:
        raise ValueError(f"{mode_name} review import payload must contain 'findings'")
    findings = data["findings"]
    if not isinstance(findings, list):
        raise ValueError(f"{mode_name} review import payload 'findings' must be a list")
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValueError(
                f"{mode_name} review import payload 'findings[{idx}]' must be an object"
            )

    assessments = data.get("assessments")
    if assessments is not None and not isinstance(assessments, dict):
        raise ValueError(
            f"{mode_name} review import payload 'assessments' must be an object"
        )
    return ReviewImportEnvelope(
        findings=findings,
        assessments=assessments,
        reviewed_files=extract_reviewed_files(data),
    )


def normalize_review_confidence(value: object) -> str:
    """Normalize review confidence labels to high/medium/low."""
    confidence = str(value).strip().lower()
    return confidence if confidence in {"high", "medium", "low"} else "low"


def review_tier(confidence: str, *, holistic: bool) -> int:
    """Derive natural tier from review confidence and scope."""
    if confidence == "high":
        return 1 if holistic else 3
    if confidence == "medium":
        return 2 if holistic else 3
    return 3


def resolve_import_project_root(project_root: Path | str | None) -> Path:
    """Resolve optional import project root to an absolute path."""
    if project_root is None:
        return get_project_root()
    return Path(project_root).resolve()


def upsert_review_cache_entry(
    file_cache: dict[str, Any],
    file_path: str,
    *,
    project_root: Path,
    hash_file_fn,
    utc_now_fn=utc_now,
    finding_count: int | None = None,
) -> None:
    """Write one normalized review-cache entry for a reviewed file."""
    absolute = project_root / file_path
    content_hash = hash_file_fn(str(absolute)) if absolute.exists() else ""
    if finding_count is None:
        previous = file_cache.get(file_path, {})
        count = previous.get("finding_count", 0) if isinstance(previous, dict) else 0
        finding_count = count if isinstance(count, int) else 0
    file_cache[file_path] = {
        "content_hash": content_hash,
        "reviewed_at": utc_now_fn(),
        "finding_count": max(0, int(finding_count)),
    }


def refresh_review_file_cache(
    state: dict[str, Any],
    *,
    reviewed_files: list[str] | None,
    findings_by_file: dict[str, int | None] | None = None,
    project_root: Path | str | None = None,
    hash_file_fn,
    utc_now_fn=utc_now,
) -> None:
    """Refresh normalized review cache entries for all reviewed files."""
    file_cache = _review_file_cache(state)
    resolved_project_root = resolve_import_project_root(project_root)
    counts = findings_by_file or {}

    reviewed_set = set(counts)
    if reviewed_files:
        reviewed_set.update(
            str(file_path).strip()
            for file_path in reviewed_files
            if isinstance(file_path, str) and str(file_path).strip()
        )

    for file_path in reviewed_set:
        upsert_review_cache_entry(
            file_cache,
            file_path,
            project_root=resolved_project_root,
            hash_file_fn=hash_file_fn,
            utc_now_fn=utc_now_fn,
            finding_count=counts.get(file_path),
        )


def auto_resolve_review_findings(
    state: dict[str, Any],
    *,
    new_ids: set[str],
    diff: dict[str, Any],
    note: str,
    should_resolve: Callable[[dict[str, Any]], bool],
    utc_now_fn=utc_now,
) -> None:
    """Auto-resolve stale open review findings that match a scope predicate."""
    diff.setdefault("auto_resolved", 0)
    for finding_id, finding in state.get("findings", {}).items():
        if finding_id in new_ids or finding.get("status") != "open":
            continue
        if not should_resolve(finding):
            continue
        finding["status"] = "auto_resolved"
        finding["resolved_at"] = utc_now_fn()
        finding["note"] = note
        diff["auto_resolved"] += 1
