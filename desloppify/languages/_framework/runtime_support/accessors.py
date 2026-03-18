"""Runtime field accessors shared by LangRun."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from desloppify.languages._framework.base.types import DetectorCoverageRecord

if TYPE_CHECKING:
    from desloppify.engine.policy.zones import FileZoneMap


class LangRunStateAccessors:
    """Property + helper surface for mutable LangRun state."""

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
    def runtime_cache(self) -> dict[str, Any]:
        return self.state.runtime_cache

    @runtime_cache.setter
    def runtime_cache(self, value: dict[str, Any]) -> None:
        self.state.runtime_cache = value

    @property
    def review_cache(self) -> dict[str, Any]:
        return self.state.review_cache

    @review_cache.setter
    def review_cache(self, value: dict[str, Any]) -> None:
        self.state.review_cache = value

    @property
    def subjective_assessments(self) -> dict[str, Any]:
        return self.state.subjective_assessments

    @subjective_assessments.setter
    def subjective_assessments(self, value: dict[str, Any]) -> None:
        self.state.subjective_assessments = value

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


__all__ = ["LangRunStateAccessors"]
