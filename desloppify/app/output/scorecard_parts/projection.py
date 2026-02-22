"""Canonical scorecard projection helpers shared by command/reporting surfaces."""

from __future__ import annotations

import re

from desloppify.engine.planning.dimension_rows import (
    scorecard_dimension_rows,
)
from desloppify.scoring import DISPLAY_NAMES


def dimension_cli_key(dimension_name: str) -> str:
    """Map a display name to a review --dimensions CLI key."""
    cleaned = dimension_name.replace(" (subjective)", "").strip()
    lowered = cleaned.lower()
    for key, display in DISPLAY_NAMES.items():
        if display.lower() == lowered:
            return key
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def scorecard_dimension_cli_keys(name: str, data: dict) -> list[str]:
    """Map scorecard subjective display names to review --dimensions keys."""
    if name in ("Elegance", "Elegance (combined)"):
        components = (
            data.get("detectors", {})
            .get("subjective_assessment", {})
            .get("components", [])
        )
        if isinstance(components, list) and components:
            keys = [dimension_cli_key(component) for component in components]
        else:
            keys = [
                "high_level_elegance",
                "mid_level_elegance",
                "low_level_elegance",
            ]
    elif name in ("Abstraction Fit", "Abstraction Fit (combined)"):
        components = (
            data.get("detectors", {})
            .get("subjective_assessment", {})
            .get("components", [])
        )
        if isinstance(components, list) and components:
            keys = [dimension_cli_key(component) for component in components]
        else:
            keys = ["abstraction_fitness"]
    else:
        keys = [dimension_cli_key(name)]

    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if not key or key in seen:
            continue
        ordered.append(key)
        seen.add(key)
    return ordered


def scorecard_subjective_entries(
    state: dict,
    *,
    dim_scores: dict | None = None,
) -> list[dict]:
    """Return scorecard-subjective entries with score/strict/placeholder metadata."""
    rows = scorecard_dimension_rows(state, dim_scores=dim_scores)
    assessments = state.get("subjective_assessments") or {}
    subjective_display_names = {display.lower() for display in DISPLAY_NAMES.values()}
    subjective_display_names.update({"elegance", "elegance (combined)"})

    entries: list[dict] = []
    for name, data in rows:
        detectors = data.get("detectors", {})
        lowered_name = str(name).strip().lower()
        is_subjective = (
            "subjective_assessment" in detectors
            or lowered_name in subjective_display_names
        )
        if not is_subjective:
            continue
        score = float(data.get("score", 0.0))
        strict = float(data.get("strict", score))
        assessment_meta = detectors.get("subjective_assessment", {})
        placeholder = bool(
            assessment_meta.get("placeholder")
            or (
                data.get("score", 0) == 0
                and data.get("issues", 0) == 0
                and data.get("checks", 0) == 0
            )
        )
        dim_key = assessment_meta.get("dimension_key", "")
        stale = bool(
            dim_key
            and isinstance(assessments.get(dim_key), dict)
            and assessments[dim_key].get("needs_review_refresh")
        )
        entries.append(
            {
                "name": name,
                "score": score,
                "strict": strict,
                "checks": int(data.get("checks", 0) or 0),
                "issues": int(data.get("issues", 0) or 0),
                "tier": int(data.get("tier", 4) or 4),
                "placeholder": placeholder,
                "stale": stale,
                "dimension_key": dim_key,
                "cli_keys": scorecard_dimension_cli_keys(name, data),
            }
        )
    return entries


def scorecard_dimensions_payload(
    state: dict,
    *,
    dim_scores: dict | None = None,
) -> list[dict]:
    """Serialize scorecard rows for JSON/query outputs."""
    subjective_by_name = {
        entry["name"]: entry
        for entry in scorecard_subjective_entries(state, dim_scores=dim_scores)
    }
    payload: list[dict] = []
    for name, data in scorecard_dimension_rows(state, dim_scores=dim_scores):
        score = float(data.get("score", 0.0))
        strict = float(data.get("strict", score))
        subjective = name in subjective_by_name
        entry = {
            "name": name,
            "score": score,
            "strict": strict,
            "checks": int(data.get("checks", 0) or 0),
            "issues": int(data.get("issues", 0) or 0),
            "tier": int(
                data.get("tier", 4 if subjective else 3) or (4 if subjective else 3)
            ),
            "subjective": subjective,
        }
        if subjective:
            sub = subjective_by_name[name]
            entry["placeholder"] = bool(sub.get("placeholder"))
            entry["cli_keys"] = list(sub.get("cli_keys", []))
        payload.append(entry)
    return payload
