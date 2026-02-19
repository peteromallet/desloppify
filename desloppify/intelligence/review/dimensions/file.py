"""Per-file review dimension definitions and system prompt."""

from __future__ import annotations

from desloppify.intelligence.review.dimensions.data import load_dimensions

DEFAULT_DIMENSIONS, DIMENSION_PROMPTS, REVIEW_SYSTEM_PROMPT = load_dimensions()
