"""Scorecard dimension row helpers for the engine/planning layer.

Provides ``scorecard_dimension_rows`` without importing app-layer modules.
The app scorecard surface re-exports this so external call-sites are unaffected.
"""

from __future__ import annotations

from desloppify.scoring import DIMENSIONS


def scorecard_dimension_rows(
    state: dict,
    *,
    dim_scores: dict | None = None,
) -> list[tuple[str, dict]]:
    """Return scorecard rows using canonical dimension ordering.

    Tries ``prepare_scorecard_dimensions`` from the app layer when available
    (deferred import to avoid hard engine -> app dependency), then falls back
    to a simple mechanical-dimension listing.
    """
    if dim_scores is None:
        dim_scores = (
            state.get("dimension_scores", {}) if isinstance(state, dict) else {}
        )
        projected_state = state
    else:
        projected_state = dict(state)
        projected_state["dimension_scores"] = dim_scores

    # Try the full app-layer scorecard projection when it can be imported.
    try:
        from desloppify.app.output.scorecard_parts.dimensions import (
            prepare_scorecard_dimensions,
        )

        rows = prepare_scorecard_dimensions(projected_state)
        if rows:
            return rows
    except ImportError:
        pass

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
