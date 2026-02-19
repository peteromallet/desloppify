"""Runtime wrappers for per-invocation language scan state."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from desloppify.languages.framework.base.types import LangConfig

_UNSET = object()


@dataclass
class LangRuntimeState:
    """Ephemeral, per-run state for a language config."""

    zone_map: object | None = None
    dep_graph: dict[str, dict[str, Any]] | None = None
    complexity_map: dict[str, float] = field(default_factory=dict)
    review_cache: dict[str, Any] = field(default_factory=dict)
    review_max_age_days: int = 30
    runtime_settings: dict[str, Any] = field(default_factory=dict)
    runtime_options: dict[str, Any] = field(default_factory=dict)
    large_threshold_override: int = 0
    props_threshold_override: int = 0


@dataclass
class LangRunOverrides:
    """Override bundle for mutable per-run runtime fields."""

    zone_map: object | None = _UNSET
    dep_graph: dict[str, dict[str, Any]] | None = _UNSET
    complexity_map: dict[str, float] | None = _UNSET
    review_cache: dict[str, Any] | None = _UNSET
    review_max_age_days: int | None = _UNSET
    runtime_settings: dict[str, Any] | None = _UNSET
    runtime_options: dict[str, Any] | None = _UNSET
    large_threshold_override: int | None = _UNSET
    props_threshold_override: int | None = _UNSET


@dataclass
class LangRun:
    """Runtime facade over an immutable LangConfig."""

    config: LangConfig
    state: LangRuntimeState = field(default_factory=LangRuntimeState)

    def __getattr__(self, name: str):
        return getattr(self.config, name)

    @property
    def zone_map(self):
        return self.state.zone_map

    @zone_map.setter
    def zone_map(self, value) -> None:
        self.state.zone_map = value

    @property
    def dep_graph(self):
        return self.state.dep_graph

    @dep_graph.setter
    def dep_graph(self, value) -> None:
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
        return 14

    def runtime_setting(self, key: str, default: object | None = None) -> object:
        if key in self.state.runtime_settings:
            return self.state.runtime_settings[key]
        spec = self.config.setting_specs.get(key)
        if spec:
            return copy.deepcopy(spec.default)
        return default

    def runtime_option(self, key: str, default: object | None = None) -> object:
        if key in self.state.runtime_options:
            return self.state.runtime_options[key]
        spec = self.config.runtime_option_specs.get(key)
        if spec:
            return copy.deepcopy(spec.default)
        return default


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
    if resolved.zone_map is not _UNSET:
        runtime.zone_map = resolved.zone_map
    if resolved.dep_graph is not _UNSET:
        runtime.dep_graph = resolved.dep_graph
    if resolved.complexity_map is not _UNSET:
        runtime.complexity_map = resolved.complexity_map or {}
    if resolved.review_cache is not _UNSET:
        runtime.review_cache = resolved.review_cache or {}
    if resolved.review_max_age_days is not _UNSET:
        runtime.review_max_age_days = int(resolved.review_max_age_days)
    if resolved.runtime_settings is not _UNSET:
        runtime.state.runtime_settings = resolved.runtime_settings or {}
    if resolved.runtime_options is not _UNSET:
        runtime.state.runtime_options = resolved.runtime_options or {}
    if resolved.large_threshold_override is not _UNSET:
        runtime.state.large_threshold_override = int(
            resolved.large_threshold_override or 0
        )
    if resolved.props_threshold_override is not _UNSET:
        runtime.state.props_threshold_override = int(
            resolved.props_threshold_override or 0
        )

    return runtime


__all__ = [
    "LangRun",
    "LangRunOverrides",
    "LangRuntimeState",
    "make_lang_run",
]
