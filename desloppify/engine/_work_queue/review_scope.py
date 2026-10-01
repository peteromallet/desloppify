"""Pure dimension scope shared by reassessment gates and executable work."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TypeVar

from desloppify.engine._state.schema import StateModel

_Item = TypeVar("_Item", bound=Mapping[str, object])


def scored_dimensions(state: StateModel) -> list[str]:
    """Return dimension keys that already have a nonzero subjective score."""
    assessments: Mapping[str, object] = state.get("subjective_assessments", {})
    scored: list[str] = []
    for dim_key, assessment in assessments.items():
        if isinstance(assessment, dict):
            if assessment.get("score", 0):
                scored.append(dim_key)
        elif isinstance(assessment, int | float) and assessment:
            scored.append(dim_key)
    return sorted(scored)


def normalize_dimension_key(raw: object) -> str:
    """Normalize a dimension key/name to canonical snake_case."""
    text = str(raw or "").strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_")


def review_blockers(
    items: Iterable[_Item],
    *,
    blocking_dims: Iterable[str],
) -> list[_Item]:
    """Select the existing rerun blockers without changing their semantics."""
    dimensions = {normalize_dimension_key(dim) for dim in blocking_dims}
    blockers: list[_Item] = []
    for item in items:
        if item.get("kind") == "subjective_dimension":
            continue
        detail = item.get("detail")
        if not isinstance(detail, dict):
            continue
        dimension = detail.get("dimension")
        if not isinstance(dimension, str) or not dimension.strip():
            continue
        if normalize_dimension_key(dimension) in dimensions:
            blockers.append(item)
    return blockers
