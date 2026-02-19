"""Shared parsing/assessment helpers for review finding imports."""

from __future__ import annotations

from typing import Any

from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.state import utc_now


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
        score = value if isinstance(value, int | float) else value_obj.get("score", 0)
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
                if isinstance(raw, bool) or not isinstance(raw, int | float):
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
