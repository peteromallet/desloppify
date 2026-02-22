"""Dimension selection policy for review preparation.

This module exists to keep precedence rules explicit and centralized.
"""

from __future__ import annotations

from desloppify.intelligence.review.dimensions.holistic import DIMENSIONS
from desloppify.intelligence.review.dimensions.lang import HOLISTIC_DIMENSIONS_BY_LANG


def _non_empty(values: list[str] | None) -> list[str] | None:
    """Return ``values`` only when it is a non-empty list."""
    if values and isinstance(values, list):
        return values
    return None


def resolve_dimensions(
    *,
    cli_dimensions: list[str] | None,
    lang_name: str | None = None,
    config_dimensions: list[str] | None = None,
    default_dimensions: list[str] | None = None,
) -> list[str]:
    """Resolve review dimensions using a single precedence policy.

    Precedence (highest to lowest):
    1) CLI ``--dimensions``
    2) Language-curated defaults (if *lang_name* provided)
    3) Config ``review_dimensions``
    4) Caller-supplied *default_dimensions*
    5) Global defaults from ``dimensions.json``
    """
    lang_dims = (
        _non_empty(HOLISTIC_DIMENSIONS_BY_LANG.get(lang_name))
        if lang_name
        else None
    )
    return list(
        _non_empty(cli_dimensions)
        or lang_dims
        or _non_empty(config_dimensions)
        or _non_empty(default_dimensions)
        or DIMENSIONS
    )


# Backward-compat aliases
def resolve_per_file_dimensions(
    *,
    cli_dimensions: list[str] | None,
    config_dimensions: list[str] | None = None,
    default_dimensions: list[str] | None = None,
) -> list[str]:
    return resolve_dimensions(
        cli_dimensions=cli_dimensions,
        config_dimensions=config_dimensions,
        default_dimensions=default_dimensions,
    )


def resolve_holistic_dimensions(
    *,
    lang_name: str,
    cli_dimensions: list[str] | None,
    default_dimensions: list[str] | None = None,
) -> list[str]:
    return resolve_dimensions(
        cli_dimensions=cli_dimensions,
        lang_name=lang_name,
        default_dimensions=default_dimensions,
    )
