"""Runtime wrappers for per-invocation language scan state."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

from desloppify.languages._framework.base.types import (
    DetectorCoverageRecord,
    LangConfig,
    LangRuntimeContract,
)
from .accessors import LangRunStateAccessors

if TYPE_CHECKING:
    from desloppify.engine.policy.zones import FileZoneMap

_UNSET = object()


@dataclass
class LangRuntimeState:
    """Ephemeral, per-run state for a language config."""

    zone_map: FileZoneMap | None = None
    dep_graph: dict[str, dict[str, Any]] | None = None
    complexity_map: dict[str, float] = field(default_factory=dict)
    review_cache: dict[str, Any] = field(default_factory=dict)
    review_max_age_days: int = 30
    subjective_assessments: dict[str, Any] = field(default_factory=dict)
    runtime_settings: dict[str, Any] = field(default_factory=dict)
    runtime_options: dict[str, Any] = field(default_factory=dict)
    large_threshold_override: int = 0
    props_threshold_override: int = 0
    detector_coverage: dict[str, DetectorCoverageRecord] = field(default_factory=dict)
    coverage_warnings: list[DetectorCoverageRecord] = field(default_factory=list)


@dataclass
class LangRunOverrides:
    """Override bundle for mutable per-run runtime fields."""

    zone_map: FileZoneMap | None = _UNSET
    dep_graph: dict[str, dict[str, Any]] | None = _UNSET
    complexity_map: dict[str, float] | None = _UNSET
    review_cache: dict[str, Any] | None = _UNSET
    review_max_age_days: int | None = _UNSET
    subjective_assessments: dict[str, Any] | None = _UNSET
    runtime_settings: dict[str, Any] | None = _UNSET
    runtime_options: dict[str, Any] | None = _UNSET
    large_threshold_override: int | None = _UNSET
    props_threshold_override: int | None = _UNSET
    detector_coverage: dict[str, DetectorCoverageRecord] | None = _UNSET
    coverage_warnings: list[DetectorCoverageRecord] | None = _UNSET


_LANG_RUNTIME_STATE_FIELDS = frozenset(f.name for f in fields(LangRuntimeState))
_LANG_OVERRIDE_FIELDS = tuple(f.name for f in fields(LangRunOverrides))
_LANG_OVERRIDE_DICT_FIELDS = frozenset(
    {
        "complexity_map",
        "review_cache",
        "subjective_assessments",
        "runtime_settings",
        "runtime_options",
        "detector_coverage",
    }
)
_LANG_OVERRIDE_LIST_FIELDS = frozenset({"coverage_warnings"})
_LANG_OVERRIDE_INT_FIELDS = frozenset(
    {
        "large_threshold_override",
        "props_threshold_override",
    }
)
_FORWARDED_CONFIG_ATTRS = frozenset(
    {
        # Explicit delegation surface for LangRun -> LangConfig.
        # New LangConfig fields are intentionally opt-in here.
        "name",
        "extensions",
        "exclusions",
        "default_src",
        "build_dep_graph",
        "entry_patterns",
        "barrel_names",
        "phases",
        "fixers",
        "get_area",
        "detect_commands",
        "extract_functions",
        "boundaries",
        "typecheck_cmd",
        "file_finder",
        "large_threshold",
        "complexity_threshold",
        "default_scan_profile",
        "setting_specs",
        "runtime_option_specs",
        "detect_markers",
        "external_test_dirs",
        "test_file_extensions",
        "review_module_patterns_fn",
        "review_api_surface_fn",
        "review_guidance",
        "review_low_value_pattern",
        "holistic_review_dimensions",
        "migration_pattern_pairs",
        "migration_mixed_extensions",
        "zone_rules",
        "integration_depth",
        "detect_lang_security_detailed",
        "detect_private_imports",
        "normalize_settings",
        "normalize_runtime_options",
        "scan_coverage_prerequisites",
        "set_runtime_context",
    }
)


# LangRuntimeContract is defined in base.types to avoid an import cycle.


@dataclass
class LangRun(LangRunStateAccessors):
    """Runtime facade over an immutable LangConfig."""

    config: LangConfig
    state: LangRuntimeState = field(default_factory=LangRuntimeState)

    def __getattr__(self, name: str):
        if name in _FORWARDED_CONFIG_ATTRS:
            return getattr(self.config, name)
        raise AttributeError(
            f"{self.__class__.__name__!s} has no attribute {name!r}; "
            "access runtime state via explicit LangRun properties"
        )

    def __dir__(self):
        """Expose LangConfig + mutable runtime fields for discoverability."""
        return (
            list(super().__dir__())
            + sorted(_FORWARDED_CONFIG_ATTRS)
            + sorted(_LANG_RUNTIME_STATE_FIELDS)
        )


def _coerce_lang_override(field_name: str, value: object) -> object:
    """Normalize override values to LangRuntimeState-compatible payloads."""
    if field_name in _LANG_OVERRIDE_DICT_FIELDS:
        return value if isinstance(value, dict) else {}
    if field_name in _LANG_OVERRIDE_LIST_FIELDS:
        return value if isinstance(value, list) else []
    if field_name in _LANG_OVERRIDE_INT_FIELDS:
        return int(value or 0)
    if field_name == "review_max_age_days":
        if value is None:
            return None
        return int(value)
    return value


def _apply_lang_overrides(runtime: LangRun, overrides: LangRunOverrides) -> None:
    """Apply override bundle to runtime state via one normalized loop."""
    for field_name in _LANG_OVERRIDE_FIELDS:
        value = getattr(overrides, field_name)
        if value is _UNSET:
            continue
        coerced = _coerce_lang_override(field_name, value)
        if field_name == "review_max_age_days" and coerced is None:
            continue
        setattr(runtime, field_name, coerced)


def make_lang_run(
    lang: LangConfig | LangRun,
    overrides: LangRunOverrides | None = None,
) -> LangRun:
    """Build a fresh LangRun for a command invocation."""

    if isinstance(lang, LangRun):
        runtime = lang
    else:
        runtime = LangRun(config=lang)
        runtime.state.runtime_settings = copy.deepcopy(
            getattr(lang, "_default_runtime_settings", {})
        )
        runtime.state.runtime_options = copy.deepcopy(
            getattr(lang, "_default_runtime_options", {})
        )

    resolved = overrides if overrides is not None else LangRunOverrides()
    _apply_lang_overrides(runtime, resolved)
    return runtime


__all__ = [
    "LangRuntimeContract",
    "LangRun",
    "LangRunOverrides",
    "LangRuntimeState",
    "make_lang_run",
]
