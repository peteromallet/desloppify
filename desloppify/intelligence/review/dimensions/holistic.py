"""Review dimension definitions and system prompt (single source of truth)."""

from __future__ import annotations

from desloppify.intelligence.review.dimensions.data import load_dimensions

DIMENSIONS, DIMENSION_PROMPTS, REVIEW_SYSTEM_PROMPT = load_dimensions()

# Backward-compat aliases — prefer the unprefixed names in new code.
HOLISTIC_DIMENSIONS = DIMENSIONS
HOLISTIC_DIMENSION_PROMPTS = DIMENSION_PROMPTS
HOLISTIC_REVIEW_SYSTEM_PROMPT = REVIEW_SYSTEM_PROMPT
DEFAULT_DIMENSIONS = DIMENSIONS
