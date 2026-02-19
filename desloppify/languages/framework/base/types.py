"""Core language-framework dataclasses and contracts."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from desloppify.engine.state_internal.schema import Finding


@dataclass
class DetectorPhase:
    """A single phase in the scan pipeline.

    Each phase runs one or more detectors and returns normalized findings.
    The `run` function handles both detection AND normalization (converting
    raw detector output to findings with tiers/confidence).
    """

    label: str
    run: Callable[[Path, object], tuple[list[Finding], dict[str, int]]]
    slow: bool = False


@dataclass
class FixResult:
    """Return type for fixer wrappers that need to carry metadata."""

    entries: list[dict]
    skip_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class FixerConfig:
    """Configuration for an auto-fixer."""

    label: str
    detect: Callable
    fix: Callable
    detector: str  # finding detector name (for state resolution)
    verb: str = "Fixed"
    dry_verb: str = "Would fix"
    post_fix: Callable | None = None


@dataclass
class BoundaryRule:
    """A coupling boundary: `protected` dir should not be imported from `forbidden_from`."""

    protected: str  # e.g. "shared/"
    forbidden_from: str  # e.g. "tools/"
    label: str  # e.g. "shared→tools"


@dataclass(frozen=True)
class LangValueSpec:
    """Typed language option/setting schema entry."""

    type: type
    default: object
    description: str = ""


@dataclass
class LangConfig:
    """Language configuration — everything the pipeline needs to scan a codebase."""

    name: str
    extensions: list[str]
    exclusions: list[str]
    default_src: str  # relative to PROJECT_ROOT

    # Dep graph builder (language-specific import parsing)
    build_dep_graph: Callable[[Path], dict]

    # Entry points (not orphaned even with 0 importers)
    entry_patterns: list[str]
    barrel_names: set[str]

    # Detector phases (ordered)
    phases: list[DetectorPhase] = field(default_factory=list)

    # Fixer registry
    fixers: dict[str, FixerConfig] = field(default_factory=dict)

    # Area classification (project-specific grouping)
    get_area: Callable[[str], str] | None = None

    # Commands for `detect` subcommand (language-specific overrides)
    # Keys serve as the valid detector name list.
    detect_commands: dict[str, Callable] = field(default_factory=dict)

    # Function extractor (for duplicate detection). Returns a list of FunctionInfo items.
    extract_functions: Callable[[Path], list] | None = None

    # Coupling boundaries (optional, project-specific)
    boundaries: list[BoundaryRule] = field(default_factory=list)

    # Unused detection tool command (for post-fix checklist)
    typecheck_cmd: str = ""

    # File finder: (path) -> list[str]
    file_finder: Callable | None = None

    # Structural analysis thresholds
    large_threshold: int = 500
    complexity_threshold: int = 15
    default_scan_profile: str = "full"

    # Language-specific persisted settings and per-run runtime options.
    setting_specs: dict[str, LangValueSpec] = field(default_factory=dict)
    runtime_option_specs: dict[str, LangValueSpec] = field(default_factory=dict)

    # Project-level files that indicate this language is present
    detect_markers: list[str] = field(default_factory=list)

    # External test discovery (outside scanned path)
    external_test_dirs: list[str] = field(default_factory=lambda: ["tests", "test"])
    test_file_extensions: list[str] = field(default_factory=list)

    # Review-context language hooks
    review_module_patterns_fn: Callable[[str], list[str]] | None = None
    review_api_surface_fn: Callable[[dict[str, str]], dict] | None = None
    review_guidance: dict = field(default_factory=dict)
    review_low_value_pattern: object | None = None
    holistic_review_dimensions: list[str] = field(default_factory=list)
    migration_pattern_pairs: list[tuple[str, object, object]] = field(
        default_factory=list
    )
    migration_mixed_extensions: set[str] = field(default_factory=set)

    # Zone classification rules
    zone_rules: list = field(default_factory=list)

    # Runtime state set during scan (not config-time)
    zone_map: object | None = field(default=None, init=False, repr=False)
    dep_graph: dict | None = field(default=None, init=False, repr=False)
    _default_runtime_settings: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )
    _default_runtime_options: dict[str, object] = field(
        default_factory=dict, init=False, repr=False
    )

    @staticmethod
    def _clone_default(default: object) -> object:
        return copy.deepcopy(default)

    @classmethod
    def _coerce_value(cls, raw: object, expected: type, default: object) -> object:
        """Best-effort coercion for config/CLI values."""
        fallback = cls._clone_default(default)
        if raw is None:
            return fallback

        if expected is bool:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
                return fallback
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                return bool(raw)
            return fallback

        if expected is int:
            if isinstance(raw, bool):
                return fallback
            try:
                return int(raw)
            except (TypeError, ValueError):
                return fallback

        if expected is float:
            if isinstance(raw, bool):
                return fallback
            try:
                return float(raw)
            except (TypeError, ValueError):
                return fallback

        if expected is str:
            return raw if isinstance(raw, str) else str(raw)

        if expected is list:
            return raw if isinstance(raw, list) else fallback

        if expected is dict:
            return raw if isinstance(raw, dict) else fallback

        return raw if isinstance(raw, expected) else fallback

    def normalize_settings(self, values: dict[str, object] | None) -> dict[str, object]:
        values = values if isinstance(values, dict) else {}
        normalized: dict[str, object] = {}
        for key, spec in self.setting_specs.items():
            raw = values.get(key, spec.default)
            normalized[key] = self._coerce_value(raw, spec.type, spec.default)
        return normalized

    def normalize_runtime_options(
        self,
        values: dict[str, object] | None,
        *,
        strict: bool = False,
    ) -> dict[str, object]:
        values = values if isinstance(values, dict) else {}
        specs = self.runtime_option_specs
        if strict:
            unknown = sorted(set(values) - set(specs))
            if unknown:
                raise KeyError(
                    f"Unknown runtime option(s) for {self.name}: {', '.join(unknown)}"
                )
        normalized: dict[str, object] = {}
        for key, spec in specs.items():
            raw = values.get(key, spec.default)
            normalized[key] = self._coerce_value(raw, spec.type, spec.default)
        return normalized

    def set_runtime_context(
        self,
        *,
        settings: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
    ) -> None:
        """Set default runtime settings/options for future LangRun creation."""
        if settings is not None:
            self._default_runtime_settings = self.normalize_settings(settings)
        if options is not None:
            self._default_runtime_options = self.normalize_runtime_options(options)

    def runtime_setting(self, key: str, default: object | None = None) -> object:
        """Read setting from config-level runtime defaults."""
        if key in self._default_runtime_settings:
            return copy.deepcopy(self._default_runtime_settings[key])
        spec = self.setting_specs.get(key)
        if spec:
            return copy.deepcopy(spec.default)
        return default

    def runtime_option(self, key: str, default: object | None = None) -> object:
        """Read option from config-level runtime defaults."""
        if key in self._default_runtime_options:
            return copy.deepcopy(self._default_runtime_options[key])
        spec = self.runtime_option_specs.get(key)
        if spec:
            return copy.deepcopy(spec.default)
        return default


__all__ = [
    "BoundaryRule",
    "DetectorPhase",
    "FixerConfig",
    "FixResult",
    "LangConfig",
    "LangValueSpec",
]
