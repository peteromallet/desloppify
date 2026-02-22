"""Language-derived review dimensions and guidance helpers."""

from __future__ import annotations

import logging

from desloppify.languages import available_langs, get_lang

logger = logging.getLogger(__name__)


def _collect_holistic_dims_by_lang() -> dict[str, list[str]]:
    """Collect per-language holistic dimension defaults from language plugins."""
    out: dict[str, list[str]] = {}
    for lang_name in available_langs():
        try:
            dims = list(
                getattr(get_lang(lang_name), "holistic_review_dimensions", [])
                or []
            )
        except (ValueError, TypeError, AttributeError, ImportError) as exc:
            logger.debug("Skipping holistic dimensions for %s: %s", lang_name, exc)
            dims = []
        if dims:
            out[lang_name] = dims
    return out


HOLISTIC_DIMENSIONS_BY_LANG: dict[str, list[str]] = _collect_holistic_dims_by_lang()


def _collect_lang_guidance() -> dict[str, dict[str, object]]:
    """Collect review guidance from registered language plugins."""
    out: dict[str, dict[str, object]] = {}
    for lang_name in available_langs():
        try:
            guide = getattr(get_lang(lang_name), "review_guidance", {}) or {}
        except (ValueError, TypeError, AttributeError, ImportError) as exc:
            logger.debug("Skipping review guidance for %s: %s", lang_name, exc)
            guide = {}
        if guide:
            out[lang_name] = guide
    return out


LANG_GUIDANCE: dict[str, dict[str, object]] = _collect_lang_guidance()


def get_lang_guidance(lang_name: str) -> dict[str, object]:
    """Return language-specific review guidance from plugin configuration."""
    if lang_name in LANG_GUIDANCE:
        return LANG_GUIDANCE[lang_name]

    try:
        guide = getattr(get_lang(lang_name), "review_guidance", {}) or {}
    except (ImportError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("Failed to load review guidance for %s: %s", lang_name, exc)
        guide = {}

    if guide:
        LANG_GUIDANCE[lang_name] = guide
    return guide
