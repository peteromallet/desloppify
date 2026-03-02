"""Runtime wrappers for per-invocation language scan state."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Protocol

from desloppify.languages._framework.base.types import (
    DepGraphBuilder,
    DetectorCoverageStatus,
    DetectorCoverageRecord,
    FileFinder,
    FunctionExtractor,
    LangConfig,
    LangSecurityResult,
)

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


class LangRuntimeContract(Protocol):
    """Explicit runtime interface consumed by detector phases."""

    name: str
    extensions: list[str]
    entry_patterns: list[str]
    barrel_names: set[str]
    external_test_dirs: list[str]
    test_file_extensions: list[str]
    review_low_value_pattern: object | None
    file_finder: FileFinder | None
    extract_functions: FunctionExtractor | None
    get_area: Callable[[str], str] | None
    build_dep_graph: DepGraphBuilder
    detect_lang_security_detailed: Callable[[list[str], FileZoneMap | None], LangSecurityResult]
    detect_private_imports: Callable[[dict, FileZoneMap | None], tuple[list[dict], int]]
    large_threshold: int
    complexity_threshold: int
    props_threshold: int

    zone_map: FileZoneMap | None
    dep_graph: dict[str, dict[str, Any]] | None
    complexity_map: dict[str, float]
    review_cache: dict[str, Any]
    review_max_age_days: int
    detector_coverage: dict[str, DetectorCoverageRecord]
    coverage_warnings: list[DetectorCoverageRecord]

    def runtime_setting(self, key: str, default: Any = None) -> Any: ...

    def runtime_option(self, key: str, default: Any = None) -> Any: ...

    def scan_coverage_prerequisites(self) -> list[DetectorCoverageStatus]: ...


@dataclass
class LangRun:
    """Runtime facade over an immutable LangConfig."""

    config: LangConfig
    state: LangRuntimeState = field(default_factory=LangRuntimeState)

    @property
    def zone_map(self) -> FileZoneMap | None:
        return self.state.zone_map

    @zone_map.setter
    def zone_map(self, value: FileZoneMap | None) -> None:
        self.state.zone_map = value

    @property
    def dep_graph(self) -> dict[str, dict[str, Any]] | None:
        return self.state.dep_graph

    @dep_graph.setter
    def dep_graph(self, value: dict[str, dict[str, Any]] | None) -> None:
        self.state.dep_graph = value

    @property
    def complexity_map(self) -> dict[str, float]:
        return self.state.complexity_map

    @complexity_map.setter
    def complexity_map(self, value: dict[str, float]) -> None:
        self.state.complexity_map = value

    @property
    def review_cache(self) -> dict[str, Any]:
        return self.state.review_cache

    @review_cache.setter
    def review_cache(self, value: dict[str, Any]) -> None:
        self.state.review_cache = value

    @property
    def review_max_age_days(self) -> int:
        return self.state.review_max_age_days

    @review_max_age_days.setter
    def review_max_age_days(self, value: int) -> None:
        self.state.review_max_age_days = int(value)

    @property
    def runtime_settings(self) -> dict[str, Any]:
        return self.state.runtime_settings

    @runtime_settings.setter
    def runtime_settings(self, value: dict[str, Any]) -> None:
        self.state.runtime_settings = value

    @property
    def runtime_options(self) -> dict[str, Any]:
        return self.state.runtime_options

    @runtime_options.setter
    def runtime_options(self, value: dict[str, Any]) -> None:
        self.state.runtime_options = value

    @property
    def large_threshold_override(self) -> int:
        return self.state.large_threshold_override

    @large_threshold_override.setter
    def large_threshold_override(self, value: int) -> None:
        self.state.large_threshold_override = int(value)

    @property
    def props_threshold_override(self) -> int:
        return self.state.props_threshold_override

    @props_threshold_override.setter
    def props_threshold_override(self, value: int) -> None:
        self.state.props_threshold_override = int(value)

    @property
    def detector_coverage(self) -> dict[str, DetectorCoverageRecord]:
        return self.state.detector_coverage

    @detector_coverage.setter
    def detector_coverage(self, value: dict[str, DetectorCoverageRecord]) -> None:
        self.state.detector_coverage = value

    @property
    def coverage_warnings(self) -> list[DetectorCoverageRecord]:
        return self.state.coverage_warnings

    @coverage_warnings.setter
    def coverage_warnings(self, value: list[DetectorCoverageRecord]) -> None:
        self.state.coverage_warnings = value

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

    @property
    def large_threshold(self) -> int:
        override = self.state.large_threshold_override
        if isinstance(override, int) and override > 0:
            return override
        return self.config.large_threshold

    @property
    def props_threshold(self) -> int:
        override = self.state.props_threshold_override
        if isinstance(override, int) and override > 0:
            return override
        return self.config.props_threshold

    def runtime_setting(self, key: str, default: Any = None) -> Any:
        if key in self.state.runtime_settings:
            return self.state.runtime_settings[key]
        spec = self.config.setting_specs.get(key)
        if spec:
            return copy.deepcopy(spec.default)
        return default

    def runtime_option(self, key: str, default: Any = None) -> Any:
        if key in self.state.runtime_options:
            return self.state.runtime_options[key]
        spec = self.config.runtime_option_specs.get(key)
        if spec:
            return copy.deepcopy(spec.default)
        return default


def _coerce_lang_override(field_name: str, value: object) -> object:
    """Normalize override values to LangRuntimeState-compatible payloads."""
    if field_name in _LANG_OVERRIDE_DICT_FIELDS:
        return value or {}
    if field_name in _LANG_OVERRIDE_LIST_FIELDS:
        return value or []
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
