"""Backward-compat shim — all constants now live in holistic.py."""

from desloppify.intelligence.review.dimensions.holistic import (  # noqa: F401
    DIMENSION_PROMPTS,
    DIMENSIONS as DEFAULT_DIMENSIONS,
    REVIEW_SYSTEM_PROMPT,
)
