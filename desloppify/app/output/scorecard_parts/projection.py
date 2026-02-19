"""Canonical scorecard projection helpers shared by command/reporting surfaces."""

from __future__ import annotations

import re

from desloppify.app.output.scorecard_parts.dimensions import (
    prepare_scorecard_dimensions,
)
from desloppify.scoring import DIMENSIONS, DISPLAY_NAMES


def dimension_cli_key(dimension_name: str) -> str:
    """Map a display name to a review --dimensions CLI key."""
    cleaned = dimension_name.replace(" (subjective)", "").strip()
    lowered = cleaned.lower()
    for key, display in DISPLAY_NAMES.items():
        if display.lower() == lowered:
            return key
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def scorecard_dimension_rows(
    state: dict,
    *,
    dim_scores: dict | None = None,
) -> list[tuple[str, dict]]:
    """Return scorecard rows using the same ordering/collapsing as scorecard.png."""
    if dim_scores is None:
        dim_scores = (
            state.get("dimension_scores", {}) if isinstance(state, dict) else {}
        )
        projected_state = state
    else:
        projected_state = dict(state)
        projected_state["dimension_scores"] = dim_scores

    rows = prepare_scorecard_dimensions(projected_state)
    if rows:
        return rows

    # Fallback for synthetic/unit-test states without full scorecard context.
    fallback_dim_scores = dim_scores or {}
    if not isinstance(fallback_dim_scores, dict):
        return []

    mechanical_names = [dimension.name for dimension in DIMENSIONS]
    fallback_rows: list[tuple[str, dict]] = []
    for name in mechanical_names:
        data = fallback_dim_scores.get(name)
        if isinstance(data, dict):
            fallback_rows.append((name, data))
    fallback_rows.extend(
        sorted(
            [
                (name, data)
                for name, data in fallback_dim_scores.items()
                if name not in mechanical_names and isinstance(data, dict)
            ],
            key=lambda item: item[0].lower(),
        )
    )
    return fallback_rows


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
        entries.append(
            {
                "name": name,
                "score": score,
                "strict": strict,
                "checks": int(data.get("checks", 0) or 0),
                "issues": int(data.get("issues", 0) or 0),
                "tier": int(data.get("tier", 4) or 4),
                "placeholder": placeholder,
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
