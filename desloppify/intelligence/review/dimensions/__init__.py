"""Review dimension constants and helper predicates."""

from __future__ import annotations

from desloppify.intelligence.review.dimensions.file import (
    DEFAULT_DIMENSIONS,
    DIMENSION_PROMPTS,
    REVIEW_SYSTEM_PROMPT,
)
from desloppify.intelligence.review.dimensions.holistic import (
    HOLISTIC_DIMENSION_PROMPTS,
    HOLISTIC_DIMENSIONS,
    HOLISTIC_REVIEW_SYSTEM_PROMPT,
)
from desloppify.intelligence.review.dimensions.lang import (
    HOLISTIC_DIMENSIONS_BY_LANG,
    LANG_GUIDANCE,
    get_lang_guidance,
)

_KNOWN_PER_FILE = frozenset(
    "_".join(str(name).strip().lower().replace("-", "_").split())
    for name in DIMENSION_PROMPTS
)
_KNOWN_HOLISTIC = frozenset(
    "_".join(str(name).strip().lower().replace("-", "_").split())
    for name in HOLISTIC_DIMENSION_PROMPTS
)


def normalize_dimension_name(name: str) -> str:
    """Normalize CLI/state dimension names to canonical snake_case."""
    return "_".join(str(name).strip().lower().replace("-", "_").split())


def is_custom_dimension(name: str) -> bool:
    """Custom dimensions must use the ``custom_`` namespace prefix."""
    return normalize_dimension_name(name).startswith("custom_")


def is_known_dimension(name: str, *, holistic: bool | None = None) -> bool:
    """Return True when *name* is a known per-file/holistic review dimension."""
    key = normalize_dimension_name(name)
    if not key:
        return False
    if holistic is True:
        return key in _KNOWN_HOLISTIC
    if holistic is False:
        return key in _KNOWN_PER_FILE
    return key in _KNOWN_PER_FILE or key in _KNOWN_HOLISTIC


__all__ = [
    "DEFAULT_DIMENSIONS",
    "DIMENSION_PROMPTS",
    "HOLISTIC_DIMENSIONS",
    "HOLISTIC_DIMENSION_PROMPTS",
    "HOLISTIC_DIMENSIONS_BY_LANG",
    "HOLISTIC_REVIEW_SYSTEM_PROMPT",
    "LANG_GUIDANCE",
    "REVIEW_SYSTEM_PROMPT",
    "get_lang_guidance",
    "is_custom_dimension",
    "is_known_dimension",
    "normalize_dimension_name",
]
