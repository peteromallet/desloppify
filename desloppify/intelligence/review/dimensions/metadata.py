"""Subjective-dimension metadata derived from review dimension payloads."""

from __future__ import annotations

import logging
from functools import lru_cache

from desloppify.core._internal.text_utils import is_numeric
from desloppify.intelligence.review.dimensions.data import (
    load_dimensions,
    load_dimensions_for_lang,
)
from desloppify.languages import available_langs
from desloppify.scoring import DISPLAY_NAMES

logger = logging.getLogger(__name__)

# Canonical display names — imported from engine/_scoring/subjective/core.py.
_LEGACY_DISPLAY_NAMES: dict[str, str] = DISPLAY_NAMES

_LEGACY_SUBJECTIVE_WEIGHTS_BY_DISPLAY: dict[str, float] = {
    "high elegance": 22.0,
    "mid elegance": 22.0,
    "low elegance": 12.0,
    "contracts": 12.0,
    "type safety": 12.0,
    "abstraction fit": 8.0,
    "logic clarity": 6.0,
    "structure nav": 5.0,
    "error consistency": 3.0,
    "naming quality": 2.0,
    "ai generated debt": 1.0,
}

_LEGACY_RESET_ON_SCAN_DIMENSIONS: frozenset[str] = frozenset(
    {
        "naming_quality",
        "error_consistency",
        "abstraction_fitness",
        "logic_clarity",
        "ai_generated_debt",
        "type_safety",
        "contract_coherence",
        "package_organization",
        "high_level_elegance",
        "mid_level_elegance",
        "low_level_elegance",
    }
)

_LEGACY_WEIGHT_BY_DIMENSION: dict[str, float] = {}
for _dimension_key, _display_name in _LEGACY_DISPLAY_NAMES.items():
    _weight = _LEGACY_SUBJECTIVE_WEIGHTS_BY_DISPLAY.get(
        " ".join(_display_name.strip().lower().split())
    )
    if _weight is not None:
        _LEGACY_WEIGHT_BY_DIMENSION[_dimension_key] = _weight


def _normalize_dimension_name(name: str) -> str:
    return "_".join(str(name).strip().lower().replace("-", "_").split())


def _title_display_name(dimension_key: str) -> str:
    return dimension_key.replace("_", " ").title()


def _normalize_lang_name(lang_name: str | None) -> str | None:
    if not isinstance(lang_name, str):
        return None
    cleaned = lang_name.strip().lower()
    return cleaned or None


def _extract_prompt_meta(entry: object) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {}
    meta = entry.get("meta")
    if not isinstance(meta, dict):
        return {}
    out: dict[str, object] = {}

    if isinstance(meta.get("display_name"), str) and meta["display_name"].strip():
        out["display_name"] = meta["display_name"].strip()

    weight = meta.get("weight")
    if is_numeric(weight):
        out["weight"] = max(0.0, float(weight))

    enabled = meta.get("enabled_by_default")
    if isinstance(enabled, bool):
        out["enabled_by_default"] = enabled

    reset_on_scan = meta.get("reset_on_scan")
    if isinstance(reset_on_scan, bool):
        out["reset_on_scan"] = reset_on_scan

    return out


def _merge_dimension_meta(
    target: dict[str, dict[str, object]],
    *,
    dimensions: list[str],
    prompts: dict[str, dict[str, object]],
    override_existing: bool = False,
) -> None:
    """Merge one payload's prompt metadata into the shared registry."""
    defaults = {
        _normalize_dimension_name(dim)
        for dim in dimensions
        if isinstance(dim, str) and dim.strip()
    }

    for raw_dim, entry in prompts.items():
        dim = _normalize_dimension_name(raw_dim)
        if not dim:
            continue

        payload = target.setdefault(dim, {})
        prompt_meta = _extract_prompt_meta(entry)

        if "display_name" in prompt_meta and (
            override_existing or "display_name" not in payload
        ):
            payload["display_name"] = prompt_meta["display_name"]
        if "weight" in prompt_meta and (override_existing or "weight" not in payload):
            payload["weight"] = prompt_meta["weight"]
        if "reset_on_scan" in prompt_meta and (
            override_existing or "reset_on_scan" not in payload
        ):
            payload["reset_on_scan"] = prompt_meta["reset_on_scan"]

        if dim in defaults:
            payload["enabled_by_default"] = True
        if "enabled_by_default" in prompt_meta:
            if override_existing:
                payload["enabled_by_default"] = bool(prompt_meta["enabled_by_default"])
            else:
                payload["enabled_by_default"] = bool(
                    payload.get("enabled_by_default", False)
                    or prompt_meta["enabled_by_default"]
                )


def _available_languages() -> list[str]:
    try:
        return list(available_langs())
    except (ImportError, ValueError, TypeError, RuntimeError):
        return []


def _build_subjective_dimension_metadata(
    *,
    lang_name: str | None,
) -> dict[str, dict[str, object]]:
    """Build merged metadata for subjective dimensions."""
    out: dict[str, dict[str, object]] = {}

    shared_defaults, shared_prompts, _ = load_dimensions()
    _merge_dimension_meta(out, dimensions=shared_defaults, prompts=shared_prompts)

    langs = [lang_name] if isinstance(lang_name, str) and lang_name.strip() else _available_languages()
    for name in langs:
        try:
            lang_defaults, lang_prompts, _ = load_dimensions_for_lang(name)
            _merge_dimension_meta(
                out,
                dimensions=lang_defaults,
                prompts=lang_prompts,
                override_existing=bool(lang_name),
            )
        except (ValueError, RuntimeError) as exc:
            logger.debug("Failed to load dimensions for lang %s: %s", name, exc)
            continue

    for dim, payload in out.items():
        payload.setdefault(
            "display_name",
            _LEGACY_DISPLAY_NAMES.get(dim, _title_display_name(dim)),
        )
        payload.setdefault("weight", _LEGACY_WEIGHT_BY_DIMENSION.get(dim, 1.0))
        payload.setdefault("enabled_by_default", False)
        if dim in _LEGACY_DISPLAY_NAMES:
            payload.setdefault(
                "reset_on_scan", dim in _LEGACY_RESET_ON_SCAN_DIMENSIONS
            )
        else:
            payload.setdefault("reset_on_scan", True)

    # Preserve legacy dimensions even if a payload temporarily drops one.
    for dim, display in _LEGACY_DISPLAY_NAMES.items():
        payload = out.setdefault(dim, {})
        payload.setdefault("display_name", display)
        payload.setdefault("weight", _LEGACY_WEIGHT_BY_DIMENSION.get(dim, 1.0))
        payload.setdefault("enabled_by_default", True)
        payload.setdefault("reset_on_scan", dim in _LEGACY_RESET_ON_SCAN_DIMENSIONS)

    return out


@lru_cache(maxsize=1)
def load_subjective_dimension_metadata() -> dict[str, dict[str, object]]:
    """Return merged metadata across all known dimensions/languages."""
    return _build_subjective_dimension_metadata(lang_name=None)


@lru_cache(maxsize=16)
def load_subjective_dimension_metadata_for_lang(
    lang_name: str | None,
) -> dict[str, dict[str, object]]:
    """Return merged metadata for one language (with language overrides)."""
    normalized = _normalize_lang_name(lang_name)
    return _build_subjective_dimension_metadata(lang_name=normalized)


def _metadata_registry(lang_name: str | None) -> dict[str, dict[str, object]]:
    normalized = _normalize_lang_name(lang_name)
    if normalized is None:
        return load_subjective_dimension_metadata()
    return load_subjective_dimension_metadata_for_lang(normalized)


def get_dimension_metadata(
    dimension_name: str, *, lang_name: str | None = None
) -> dict[str, object]:
    """Return metadata for one dimension key (with sane defaults)."""
    dim = _normalize_dimension_name(dimension_name)
    all_meta = _metadata_registry(lang_name)
    payload = dict(all_meta.get(dim, {}))

    payload.setdefault("display_name", _title_display_name(dim))
    payload.setdefault("weight", 1.0)
    payload.setdefault("enabled_by_default", False)
    payload.setdefault("reset_on_scan", True)
    return payload


def dimension_display_name(dimension_name: str, *, lang_name: str | None = None) -> str:
    meta = get_dimension_metadata(dimension_name, lang_name=lang_name)
    return str(meta.get("display_name", _title_display_name(dimension_name)))


def dimension_weight(dimension_name: str, *, lang_name: str | None = None) -> float:
    meta = get_dimension_metadata(dimension_name, lang_name=lang_name)
    raw = meta.get("weight", 1.0)
    if is_numeric(raw):
        return max(0.0, float(raw))
    return 1.0


def default_display_names_map(*, lang_name: str | None = None) -> dict[str, str]:
    """Display-name map for default subjective dimensions."""
    out: dict[str, str] = {}
    for dim, payload in _metadata_registry(lang_name).items():
        if not bool(payload.get("enabled_by_default", False)):
            continue
        out[dim] = str(payload.get("display_name", _title_display_name(dim)))
    return out


def resettable_default_dimensions(*, lang_name: str | None = None) -> tuple[str, ...]:
    """Default subjective dimensions that should be reset by scan reset."""
    out = []
    for dim, payload in _metadata_registry(lang_name).items():
        if not bool(payload.get("enabled_by_default", False)):
            continue
        if not bool(payload.get("reset_on_scan", True)):
            continue
        out.append(dim)
    return tuple(sorted(set(out)))


__all__ = [
    "default_display_names_map",
    "dimension_display_name",
    "dimension_weight",
    "get_dimension_metadata",
    "load_subjective_dimension_metadata",
    "load_subjective_dimension_metadata_for_lang",
    "resettable_default_dimensions",
]
