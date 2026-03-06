"""Base-layer compatibility shim for subjective-dimension metadata."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from desloppify.base.subjective_dimension_catalog import DISPLAY_NAMES
from desloppify.base.subjective_dimension_catalog import (
    RESET_ON_SCAN_DIMENSIONS,
)
from desloppify.base.subjective_dimension_catalog import WEIGHT_BY_DIMENSION
from desloppify.base.text_utils import is_numeric


def _normalize_dimension_name(name: str) -> str:
    return "_".join(str(name).strip().lower().replace("-", "_").split())


def _title_display_name(dimension_key: str) -> str:
    return dimension_key.replace("_", " ").title()


def _normalize_lang_name(lang_name: str | None) -> str | None:
    if not isinstance(lang_name, str):
        return None
    cleaned = lang_name.strip().lower()
    return cleaned or None


def _clear_subjective_dimension_caches() -> None:
    default_dimension_keys.cache_clear()
    default_dimension_keys_for_lang.cache_clear()
    load_subjective_dimension_metadata.cache_clear()
    load_subjective_dimension_metadata_for_lang.cache_clear()


def configure_subjective_dimension_providers(
    *,
    available_languages_provider: Callable[[], list[str]] | None = None,
    load_dimensions_payload_provider: Callable | None = None,
    load_dimensions_payload_for_lang_provider: Callable | None = None,
) -> None:
    """Compatibility no-op.

    Base layer no longer owns dynamic dimension provider wiring.
    """
    _ = (
        available_languages_provider,
        load_dimensions_payload_provider,
        load_dimensions_payload_for_lang_provider,
    )
    _clear_subjective_dimension_caches()


def reset_subjective_dimension_providers() -> None:
    """Compatibility no-op for older callsites/tests."""
    _clear_subjective_dimension_caches()


@lru_cache(maxsize=1)
def default_dimension_keys() -> tuple[str, ...]:
    """Return canonical default subjective dimension keys."""
    return tuple(sorted(DISPLAY_NAMES.keys()))


@lru_cache(maxsize=16)
def default_dimension_keys_for_lang(lang_name: str | None) -> tuple[str, ...]:
    """Return default subjective dimension keys for a language.

    Language-specific filtering now happens in intelligence-layer metadata APIs.
    """
    _ = _normalize_lang_name(lang_name)
    return default_dimension_keys()


def _build_metadata_registry() -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for dim, display in DISPLAY_NAMES.items():
        out[dim] = {
            "display_name": display,
            "weight": WEIGHT_BY_DIMENSION.get(dim, 1.0),
            "enabled_by_default": True,
            "reset_on_scan": dim in RESET_ON_SCAN_DIMENSIONS,
        }
    return out


@lru_cache(maxsize=1)
def load_subjective_dimension_metadata() -> dict[str, dict[str, object]]:
    """Return canonical subjective metadata map."""
    return _build_metadata_registry()


@lru_cache(maxsize=16)
def load_subjective_dimension_metadata_for_lang(
    lang_name: str | None,
) -> dict[str, dict[str, object]]:
    """Return canonical metadata for a language."""
    _ = _normalize_lang_name(lang_name)
    return _build_metadata_registry()


def _metadata_registry(lang_name: str | None) -> dict[str, dict[str, object]]:
    if _normalize_lang_name(lang_name) is None:
        return load_subjective_dimension_metadata()
    return load_subjective_dimension_metadata_for_lang(lang_name)


def get_dimension_metadata(
    dimension_name: str, *, lang_name: str | None = None,
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
    "DISPLAY_NAMES",
    "configure_subjective_dimension_providers",
    "default_dimension_keys",
    "default_dimension_keys_for_lang",
    "default_display_names_map",
    "dimension_display_name",
    "dimension_weight",
    "get_dimension_metadata",
    "load_subjective_dimension_metadata",
    "load_subjective_dimension_metadata_for_lang",
    "reset_subjective_dimension_providers",
    "resettable_default_dimensions",
]
